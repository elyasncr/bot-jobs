"""CLI entry point: uv run python -m vagas_bot <command>."""

import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated

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
from vagas_bot.scoring.prompts import prefs_from_config
from vagas_bot.sources.jsearch import JSearchSource
from vagas_bot.storage import StorageError


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


if __name__ == "__main__":
    app()
