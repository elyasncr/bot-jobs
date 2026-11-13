"""Benchmark steps shared by the CLI (eval-snapshot / eval-models / eval-report) and the dashboard button."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from vagas_bot import evaluation
from vagas_bot.archive import archived_jobs, load_archive
from vagas_bot.config import Settings
from vagas_bot.cv import CVError, load_cv
from vagas_bot.eval_report import render_report
from vagas_bot.models import Job
from vagas_bot.scoring.prompts import prefs_from_config

ARCHIVE_STAGES = {"evaluated", "emailed"}
NO_JOBS_MESSAGE = "Nenhuma vaga em data/eval/jobs/. Rode antes: python -m vagas_bot eval-snapshot"


class EvalRunnerError(Exception):
    """A precondition failed (no jobs, no CV); the message is ready for the user."""


@dataclass(frozen=True)
class AddResult:
    added: int  # vagas gravadas agora em data/eval/jobs/
    total: int  # vagas no conjunto depois de gravar
    new_labels: int  # entradas novas em labels.yaml


def _jobs_dir(settings: Settings) -> Path:
    return settings.eval_dir / "jobs"


def _new_archive_jobs(settings: Settings) -> list[Job]:
    """Evaluated/emailed jobs from data/jobs.jsonl not yet in the benchmark set, newest first."""
    have = {job.id for job in evaluation.load_eval_jobs(_jobs_dir(settings))}
    jobs = archived_jobs(load_archive(settings.jobs_archive_path), ARCHIVE_STAGES)
    return [job for job in reversed(jobs) if job.id not in have]


def pending_archive_jobs(settings: Settings) -> int:
    return len(_new_archive_jobs(settings))


def add_archive_jobs(settings: Settings, n: int | None = None) -> AddResult:
    """n=None: every new job (dashboard). A number: a diverse pick of n (CLI, by score band)."""
    candidates = _new_archive_jobs(settings)
    if n is not None:
        candidates = evaluation.pick_diverse(
            candidates, n, key=lambda j: str(j.score.total // 20) if j.score else "estimativa"
        )
    added = evaluation.save_eval_jobs(candidates, _jobs_dir(settings))
    all_jobs = evaluation.load_eval_jobs(_jobs_dir(settings))
    new_labels = evaluation.ensure_label_entries(settings.eval_dir / "labels.yaml", all_jobs)
    return AddResult(added=added, total=len(all_jobs), new_labels=new_labels)


def run_benchmark(
    settings: Settings,
    models: list[str],
    runs: int = 2,
    warmup: bool = True,
    limit: int | None = None,
    report_path: Path | None = None,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> Path:
    """Score the benchmark set with each model, save data/eval/results/eval_*.json and the report."""
    jobs = evaluation.load_eval_jobs(_jobs_dir(settings))[:limit]
    if not jobs:
        raise EvalRunnerError(NO_JOBS_MESSAGE)
    try:
        cv_md = load_cv(settings.cv_path)
    except CVError as exc:
        raise EvalRunnerError(str(exc)) from exc
    llm = settings.config.llm.ollama
    results = evaluation.run_models(
        settings, models, jobs, cv_md, prefs_from_config(settings.config.filters), runs, warmup,
        make_scorer=evaluation.ollama_scorer_for,  # lido na hora da chamada: os testes trocam esta função
        on_progress=on_progress,
    )
    meta = {
        "date": datetime.now().isoformat(timespec="seconds"),
        "runs": runs,
        "num_ctx": llm.num_ctx,
        "temperature": llm.temperature,
        "think": llm.think,
        "models": models,
    }
    payload = evaluation.results_payload(results, [evaluation.JobMeta.from_job(j) for j in jobs], meta)
    results_path = evaluation.save_results(settings.eval_dir / "results", payload)
    write_report(settings, results_path, report_path or settings.root / "eval_report.md")
    return results_path


def write_report(settings: Settings, results_path: Path, out: Path) -> None:
    runs, metas, meta = evaluation.load_results(results_path)
    labels = evaluation.load_labels(settings.eval_dir / "labels.yaml")
    by_id = {m.id: m for m in metas}
    summaries = [evaluation.summarize(r, by_id, labels) for r in runs]
    meta = meta | {"results_file": results_path.relative_to(settings.root).as_posix()
                   if results_path.is_relative_to(settings.root) else str(results_path)}
    out.write_text(render_report(runs, summaries, metas, labels, meta), encoding="utf-8")
