"""CLI entry point: uv run python -m vagas_bot <command>."""

import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from vagas_bot import evaluation
from vagas_bot.archive import archived_jobs, load_archive
from vagas_bot.config import ConfigError, Settings, load_settings, missing_env
from vagas_bot.cv import CVError, load_cv
from vagas_bot.doctor import Status, run_checks
from vagas_bot.embeddings.base import EmbedderUnavailable
from vagas_bot.eval_report import render_report
from vagas_bot.filters import apply_filters, dedupe
from vagas_bot.log import get_logger, setup_logging
from vagas_bot.notify.sample import sample_ranked
from vagas_bot.pipeline import RunOptions, RunStats, run_pipeline, send_notification
from vagas_bot.scoring.prerank import cv_to_text_compact, job_to_text
from vagas_bot.scoring.prompts import prefs_from_config
from vagas_bot.sources.jsearch import JSearchSource
from vagas_bot.storage import StorageError
from vagas_bot.training import dataset, labeling


def _force_utf8_stdio() -> None:
    """Windows consoles/Task Scheduler default to cp1252, which breaks accents and arrows."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


_force_utf8_stdio()

app = typer.Typer(add_completion=False, no_args_is_help=True, help="Bot de vagas PJ de IA/ML.")
console = Console()

ConfigOption = Annotated[
    Path, typer.Option("--config", "-c", help="Caminho do config.yaml (define a raiz do projeto).")
]

_STATUS_STYLE = {
    Status.OK: "[green]ok[/]",
    Status.WARN: "[yellow]aviso[/]",
    Status.FAIL: "[red]falha[/]",
    Status.SKIP: "[dim]pulado[/]",
}


def _load(config: Path) -> Settings:
    try:
        return load_settings(config)
    except (ConfigError, ValidationError) as exc:
        console.print(f"[red]Configuração inválida:[/] {exc}")
        raise typer.Exit(2) from exc


@app.command()
def run(
    config: ConfigOption = Path("config.yaml"),
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Não envia email nem grava estado; salva preview.html.")] = False,
    no_llm: Annotated[bool, typer.Option("--no-llm", help="Só embeddings, sem LLM.")] = False,
    limit: Annotated[int | None, typer.Option("--limit", min=1, help="Limita vagas processadas (debug).")] = None,
    force: Annotated[bool, typer.Option("--force", help="Roda mesmo que já tenha rodado hoje.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Pipeline completo."""
    settings = _load(config)
    log_file = setup_logging(settings.logs_dir, verbose=verbose)
    log = get_logger()
    log.info("Execução iniciada (dry_run=%s, no_llm=%s, limit=%s, force=%s). Log: %s",
             dry_run, no_llm, limit, force, log_file)
    try:
        run_pipeline(settings, RunOptions(dry_run=dry_run, no_llm=no_llm, limit=limit, force=force))
    except (ConfigError, CVError, StorageError, EmbedderUnavailable) as exc:
        log.error("%s", exc)
        raise typer.Exit(1) from exc


@app.command("test-email")
def test_email(config: ConfigOption = Path("config.yaml")) -> None:
    """Envia um email de teste com 3 vagas fictícias (uma por faixa)."""
    settings = _load(config)
    setup_logging(settings.logs_dir)
    missing = missing_env(settings, ["GMAIL_USER", "GMAIL_APP_PASSWORD", "EMAIL_TO"])
    if missing:
        console.print(f"[red]Variáveis ausentes:[/] {', '.join(missing)}")
        raise typer.Exit(1)
    stats = RunStats(collected=42, after_dedupe=30, after_filters=12, sent_to_llm=12, llm_scored=12,
                     jsearch_requests=5, llm_model=f"ollama/{settings.config.llm.ollama.model}",
                     llm_avg_s=2.8, elapsed_s=95.0)
    if not send_notification(sample_ranked(3), stats, settings, subject_prefix="[TESTE] "):
        raise typer.Exit(1)
    console.print(f"[green]Email de teste enviado para {settings.secrets.email_to}.[/]")


@app.command()
def doctor(
    config: ConfigOption = Path("config.yaml"),
    no_smtp: Annotated[bool, typer.Option("--no-smtp", help="Não testar login SMTP.")] = False,
) -> None:
    """Checa env, Ollama no ar, modelos baixados e SMTP."""
    settings = _load(config)
    checks = run_checks(settings, smtp=not no_smtp)

    table = Table(title="vagas-pj-bot · doctor")
    table.add_column("Item")
    table.add_column("Status")
    table.add_column("Detalhe", overflow="fold")
    for check in checks:
        table.add_row(check.name, _STATUS_STYLE[check.status], check.detail)
    console.print(table)

    if any(c.status is Status.FAIL for c in checks):
        raise typer.Exit(1)


# --- Fase 8: comparação de modelos ----------------------------------------------------


def _resolve(settings: Settings, path: Path) -> Path:
    return path if path.is_absolute() else settings.root / path


@app.command("eval-snapshot")
def eval_snapshot(
    config: ConfigOption = Path("config.yaml"),
    n: Annotated[int, typer.Option("--n", min=1, help="Quantas vagas salvar.")] = 15,
    date_posted: Annotated[str, typer.Option(help="Janela da busca na JSearch (today|3days|week|month).")] = "month",
    from_archive: Annotated[bool, typer.Option("--from-archive", help="Usa data/jobs.jsonl (sem gastar cota).")] = False,
) -> None:
    """Salva vagas em data/eval/jobs/ (base fixa do eval-models) e prepara data/eval/labels.yaml."""
    settings = _load(config)
    setup_logging(settings.logs_dir)
    jobs_dir = settings.eval_dir / "jobs"
    if from_archive:
        jobs = archived_jobs(load_archive(settings.jobs_archive_path), {"evaluated", "emailed"})
        picked = evaluation.pick_diverse(
            list(reversed(jobs)), n, key=lambda j: str(j.score.total // 20) if j.score else "estimativa"
        )
    else:
        if missing_env(settings, ["RAPIDAPI_KEY"]):
            console.print("[red]RAPIDAPI_KEY ausente[/] (ou use --from-archive).")
            raise typer.Exit(1)
        key = settings.secrets.rapidapi_key
        assert key is not None
        source = JSearchSource(key.get_secret_value())
        search = settings.config.search.model_copy(update={"date_posted": date_posted})
        jobs = apply_filters(dedupe(source.fetch(search), set()), settings.config.filters)
        picked = evaluation.pick_diverse(jobs, n, key=lambda j: source.origin_by_fingerprint.get(j.fingerprint, "?"))
    written = evaluation.save_eval_jobs(picked, jobs_dir)
    all_jobs = evaluation.load_eval_jobs(jobs_dir)
    added = evaluation.ensure_label_entries(settings.eval_dir / "labels.yaml", all_jobs)
    console.print(f"{written} vagas novas salvas; {len(all_jobs)} no total em {jobs_dir}.")
    console.print(f"{added} entradas novas em data/eval/labels.yaml (preencha score 0-100 para o Spearman).")


@app.command("eval-models")
def eval_models(
    models: Annotated[list[str] | None, typer.Argument(help="Modelos do Ollama. Padrão: o do config.yaml.")] = None,
    config: ConfigOption = Path("config.yaml"),
    runs: Annotated[int, typer.Option(min=1, help="Rodadas por vaga (consistência).")] = 2,
    limit: Annotated[int | None, typer.Option(min=1, help="Usa só as N primeiras vagas.")] = None,
    warmup: Annotated[bool, typer.Option(help="1ª chamada fora da média (carga do modelo).")] = True,
    out: Annotated[Path, typer.Option(help="Relatório markdown.")] = Path("eval_report.md"),
) -> None:
    """Compara modelos nas vagas de data/eval/jobs/ e gera eval_report.md."""
    settings = _load(config)
    setup_logging(settings.logs_dir)
    jobs = evaluation.load_eval_jobs(settings.eval_dir / "jobs")[:limit]
    if not jobs:
        console.print("[red]Nenhuma vaga em data/eval/jobs/.[/] Rode antes: python -m vagas_bot eval-snapshot")
        raise typer.Exit(1)
    try:
        cv_md = load_cv(settings.cv_path)
    except CVError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    names = models or [settings.config.llm.ollama.model]
    llm = settings.config.llm.ollama
    results = evaluation.run_models(
        settings, names, jobs, cv_md, prefs_from_config(settings.config.filters), runs, warmup,
        make_scorer=evaluation.ollama_scorer_for,
    )
    meta = {
        "date": datetime.now().isoformat(timespec="seconds"),
        "runs": runs,
        "num_ctx": llm.num_ctx,
        "temperature": llm.temperature,
        "think": llm.think,
        "models": names,
    }
    payload = evaluation.results_payload(results, [evaluation.JobMeta.from_job(j) for j in jobs], meta)
    results_path = evaluation.save_results(settings.eval_dir / "results", payload)
    _write_report(settings, results_path, _resolve(settings, out))


@app.command("eval-report")
def eval_report(
    config: ConfigOption = Path("config.yaml"),
    results: Annotated[Path | None, typer.Option(help="JSON de data/eval/results/. Padrão: o mais recente.")] = None,
    out: Annotated[Path, typer.Option(help="Relatório markdown.")] = Path("eval_report.md"),
) -> None:
    """Regera o eval_report.md de um resultado salvo (ex.: depois de preencher labels.yaml)."""
    settings = _load(config)
    path = _resolve(settings, results) if results else evaluation.latest_results(settings.eval_dir / "results")
    if path is None or not path.is_file():
        console.print("[red]Nenhum resultado em data/eval/results/.[/] Rode antes: eval-models")
        raise typer.Exit(1)
    _write_report(settings, path, _resolve(settings, out))


def _write_report(settings: Settings, results_path: Path, out: Path) -> None:
    runs, metas, meta = evaluation.load_results(results_path)
    labels = evaluation.load_labels(settings.eval_dir / "labels.yaml")
    by_id = {m.id: m for m in metas}
    summaries = [evaluation.summarize(r, by_id, labels) for r in runs]
    meta = meta | {"results_file": results_path.relative_to(settings.root).as_posix()
                   if results_path.is_relative_to(settings.root) else str(results_path)}
    out.write_text(render_report(runs, summaries, metas, labels, meta), encoding="utf-8")
    console.print(f"[green]Relatório:[/] {out}")


# --- Fase 9: embeddings (sentence-transformers + fine-tuning) -------------------------


def _training_split(settings: Settings, seed: int = 42, gold_weight: int = 3) -> dataset.DatasetSplit:
    history = dataset.load_history(settings.history_path)
    labels = evaluation.load_labels(settings.eval_dir / "labels.yaml")
    eval_jobs = evaluation.load_eval_jobs(settings.eval_dir / "jobs")
    return dataset.split_pairs(
        dataset.silver_pairs(history), dataset.gold_pairs(labels, eval_jobs, history), seed, gold_weight
    )


def _load_cv_or_exit(settings: Settings) -> str:
    try:
        return load_cv(settings.cv_path)
    except CVError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc


@app.command()
def label(
    config: ConfigOption = Path("config.yaml"),
    n: Annotated[int, typer.Option("--n", min=1, help="Máximo de vagas nesta sessão.")] = 10,
    seed: Annotated[int, typer.Option(help="Semente do sorteio.")] = 42,
) -> None:
    """Mostra vagas do histórico e pede sua nota (0-100) → data/eval/labels.yaml (gold)."""
    settings = _load(config)
    labels_path = settings.eval_dir / "labels.yaml"
    labeled = evaluation.load_labels(labels_path)
    history = dataset.load_history(settings.history_path)
    archive = {j.id: j for j in archived_jobs(load_archive(settings.jobs_archive_path))}
    candidates = labeling.pick_candidates(history, set(labeled), n, seed)
    if not candidates:
        console.print("Nenhuma vaga do histórico sem nota. Rode o bot por mais alguns dias.")
        return
    console.print(f"{len(candidates)} vagas (prioridade: nota do LLM entre 40 e 75). Enter pula, q encerra.")
    saved = 0
    for index, record in enumerate(candidates, start=1):
        job = archive.get(record["id"]) or labeling.job_from_history(record)
        console.rule(f"{index}/{len(candidates)}")
        console.print(labeling.describe(record, job), markup=False, highlight=False)
        answer = typer.prompt("Sua nota (0-100)", default="", show_default=False).strip().lower()
        if answer == "q":
            break
        if not answer:
            continue
        if not answer.isdigit() or not 0 <= int(answer) <= 100:
            console.print("[yellow]Nota inválida, vaga pulada.[/]")
            continue
        note = typer.prompt("Comentário (opcional)", default="", show_default=False).strip()
        evaluation.save_eval_jobs([job], settings.eval_dir / "jobs")
        evaluation.set_label(labels_path, job.id, job.title, job.company, int(answer), note)
        saved += 1
    total = len(evaluation.load_labels(labels_path))
    console.print(f"[green]{saved} notas salvas[/] ({total} no total em data/eval/labels.yaml).")


@app.command("finetune-embeddings")
def finetune_embeddings(
    config: ConfigOption = Path("config.yaml"),
    base: Annotated[str, typer.Option(help="Modelo base (Hugging Face ou pasta local).")] = "BAAI/bge-m3",
    out: Annotated[Path, typer.Option(help="Pasta do modelo treinado.")] = Path("models/bge-m3-elyas-v1"),
    epochs: Annotated[int, typer.Option(min=1)] = 2,
    lr: Annotated[float, typer.Option(help="Learning rate.")] = 2e-5,
    batch_size: Annotated[int, typer.Option(min=1)] = 8,
    max_seq_length: Annotated[int, typer.Option(min=64)] = 512,
    gold_weight: Annotated[int, typer.Option(min=1, help="Cópias de cada par gold no treino.")] = 3,
    gradient_checkpointing: Annotated[bool, typer.Option(help="Economiza VRAM (mais lento).")] = False,
    seed: Annotated[int, typer.Option()] = 42,
    force: Annotated[bool, typer.Option("--force", help="Treina mesmo abaixo do mínimo de dados.")] = False,
    report: Annotated[Path, typer.Option(help="Relatório base × fine-tunado.")] = Path("finetune_report.md"),
) -> None:
    """Fine-tuning do embedding com history.jsonl (silver) + labels.yaml (gold)."""
    settings = _load(config)
    setup_logging(settings.logs_dir)
    cv_md = _load_cv_or_exit(settings)
    split = _training_split(settings, seed, gold_weight)
    try:
        warnings = dataset.check_minimums(split, force)
    except dataset.InsufficientData as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    for warning in warnings:
        console.print(f"[yellow]Aviso (--force):[/] {warning}")
    if importlib.util.find_spec("sentence_transformers") is None:
        console.print("[red]Extra 'st' não instalado.[/] Rode: uv sync --extra st")
        raise typer.Exit(1)
    from vagas_bot.training.finetune import FinetuneParams, finetune  # noqa: PLC0415

    params = FinetuneParams(
        base=base, epochs=epochs, learning_rate=lr, batch_size=batch_size, max_seq_length=max_seq_length,
        gradient_checkpointing=gradient_checkpointing, gold_weight=gold_weight, seed=seed,
    )
    out_dir = _resolve(settings, out)
    meta = finetune(params, split, cv_to_text_compact(cv_md), out_dir, warnings)
    rel = out_dir.relative_to(settings.root).as_posix() if out_dir.is_relative_to(settings.root) else str(out_dir)
    _embeddings_report(settings, cv_md, split, [f"st/{base}", f"st/{rel}"], _resolve(settings, report), meta)


@app.command("eval-embeddings")
def eval_embeddings(
    specs: Annotated[list[str], typer.Argument(help="ex.: ollama/bge-m3 st/BAAI/bge-m3 st/models/bge-m3-elyas-v1")],
    config: ConfigOption = Path("config.yaml"),
    top_n: Annotated[int | None, typer.Option(help="Padrão: embeddings.top_n do config.")] = None,
    out: Annotated[Path, typer.Option(help="Relatório markdown.")] = Path("finetune_report.md"),
) -> None:
    """Compara embedders nos mesmos dados de validação e gera finetune_report.md."""
    settings = _load(config)
    setup_logging(settings.logs_dir)
    cv_md = _load_cv_or_exit(settings)
    _embeddings_report(settings, cv_md, _training_split(settings), specs, _resolve(settings, out), None, top_n)


def _embeddings_report(
    settings: Settings,
    cv_md: str,
    split: dataset.DatasetSplit,
    specs: list[str],
    out: Path,
    training_meta: dict[str, Any] | None,
    top_n: int | None = None,
) -> None:
    from vagas_bot.training import eval_embeddings as ee  # noqa: PLC0415

    k = top_n or settings.config.embeddings.top_n
    eval_texts = [job_to_text(j) for j in evaluation.load_eval_jobs(settings.eval_dir / "jobs")]
    results = []
    for raw in specs:
        try:
            spec = ee.resolve_spec(raw, settings)
        except ValueError as exc:
            console.print(f"[red]{exc}[/]")
            raise typer.Exit(2) from exc
        results.append(ee.evaluate_embedder(ee.build_embedder(raw, settings), spec, cv_md, split, eval_texts, k))
    ee.add_agreement(results)
    out.write_text(ee.render_report(results, split, k, len(eval_texts), training_meta), encoding="utf-8")
    console.print(f"[green]Relatório:[/] {out}")


# --- dashboard ------------------------------------------------------------------------


@app.command()
def dashboard(
    config: ConfigOption = Path("config.yaml"),
    port: Annotated[int, typer.Option(min=0, max=65535, help="Porta local.")] = 8765,
    no_browser: Annotated[bool, typer.Option("--no-browser", help="Não abre o navegador.")] = False,
) -> None:
    """Tela local (vagas capturadas + benchmark) em http://127.0.0.1:<porta>."""
    from vagas_bot.dashboard.server import find_dist, make_server  # noqa: PLC0415

    settings = _load(config)
    setup_logging(settings.logs_dir)
    dist = find_dist(settings.root)
    if dist is None:
        console.print("[red]A tela ainda não foi compilada.[/] Rode: cd dashboard && npm ci && npm run build")
        raise typer.Exit(1)
    try:
        httpd = make_server(settings, dist, port=port)
    except OSError as exc:
        console.print(f"[red]Não foi possível usar a porta {port}:[/] {exc}. Tente --port 8766.")
        raise typer.Exit(1) from exc
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    console.print(f"[green]Dashboard em {url}[/] (Ctrl+C para encerrar)")
    if not no_browser:
        import webbrowser  # noqa: PLC0415

        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        console.print("Encerrado.")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    app()
