"""Dashboard API payloads: pure functions over the files in data/ (no HTTP here).

Metrics reuse evaluation.py / eval_report.py, so the page shows the same numbers as
eval_report.md.
"""

import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from vagas_bot import evaluation
from vagas_bot.archive import archived_jobs, load_archive
from vagas_bot.config import Settings
from vagas_bot.eval_report import is_reliable, reading
from vagas_bot.filters import detect_modality
from vagas_bot.models import Job
from vagas_bot.scoring.ranker import WEIGHTS, estimate_totals
from vagas_bot.training.dataset import load_history
from vagas_bot.training.labeling import job_from_history

_RUN_FILE_RE = re.compile(r"^eval_[0-9_]+\.json$")
_MARKDOWN_RE = re.compile(r"\*\*|`")


class DashboardError(Exception):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


# --- vagas ----------------------------------------------------------------------------


def _base_row(job: Job, run_date: str, stage: str, filter_reason: str | None) -> dict[str, Any]:
    return {
        "id": job.id,
        "run_date": run_date,
        "stage": stage,
        "filter_reason": filter_reason,
        "source": job.source,
        "publisher": job.publisher,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "modality": detect_modality(job).value,
        "url": job.url,
        "posted_at": job.posted_at.isoformat() if job.posted_at else None,
        "low_fidelity": job.low_fidelity,
        "pj_status": job.pj_status.value,
        "description": job.description,
        "embedding_score": job.embedding_score,
        "total": None,
        "is_estimate": False,
        "scores": None,
        "strengths": [],
        "gaps": [],
        "summary": None,
        "llm_model": None,
    }


def _archive_rows(settings: Settings) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in load_archive(settings.jobs_archive_path):
        latest[record["id"]] = record
    by_date: dict[str, list[Job]] = {}
    jobs: dict[str, Job] = {}
    for record in latest.values():
        job = Job.model_validate(record)
        jobs[job.id] = job
        by_date.setdefault(record["run_date"], []).append(job)
    estimates = {jid: total for batch in by_date.values() for jid, total in estimate_totals(batch).items()}

    rows = []
    for record in latest.values():
        job = jobs[record["id"]]
        row = _base_row(job, record["run_date"], record["stage"], record.get("filter_reason"))
        if job.score is not None:
            s = job.score
            row |= {
                "total": s.total,
                "scores": {k: getattr(s, k) for k in WEIGHTS},
                "strengths": s.strengths,
                "gaps": s.gaps,
                "summary": s.summary,
                "llm_model": s.model,
            }
        elif job.id in estimates and record["stage"] != "filtered":
            row |= {"total": estimates[job.id], "is_estimate": True}
        rows.append(row)
    return rows


def _history_rows(settings: Settings, known: set[str]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for record in load_history(settings.history_path):
        if record.get("id") and record["id"] not in known:
            latest[record["id"]] = record
    rows = []
    for record in latest.values():
        job = job_from_history(record).model_copy(update={"embedding_score": record.get("embedding_score")})
        row = _base_row(job, record.get("date", ""), "history", None)
        row |= {
            "url": "",
            "low_fidelity": False,
            "pj_status": record.get("pj_status", "uncertain"),
            "total": record.get("total"),
            "scores": {k: record.get(k) for k in WEIGHTS} if record.get("total") is not None else None,
            "llm_model": record.get("llm_model"),
        }
        rows.append(row)
    return rows


def _benchmark_rows(settings: Settings, known: set[str]) -> list[dict[str, Any]]:
    rows = []
    for job in evaluation.load_eval_jobs(settings.eval_dir / "jobs"):
        if job.id not in known:
            day = job.posted_at.date().isoformat() if job.posted_at else ""
            rows.append(_base_row(job, day, "benchmark", None))
    return rows


def job_rows(settings: Settings) -> list[dict[str, Any]]:
    """Every captured job once (latest version), with my label; newest run first, best score first."""
    rows = _archive_rows(settings)
    known = {r["id"] for r in rows}
    rows += _history_rows(settings, known)
    known |= {r["id"] for r in rows}
    rows += _benchmark_rows(settings, known)

    labels = evaluation.load_label_entries(settings.eval_dir / "labels.yaml")
    for row in rows:
        entry = labels.get(row["id"], {})
        score = entry.get("score")
        row["my_score"] = int(score) if isinstance(score, (int, float)) else None
        row["my_note"] = str(entry.get("note") or "")
    rows.sort(key=lambda r: r["total"] if r["total"] is not None else -1, reverse=True)
    rows.sort(key=lambda r: r["run_date"] or "", reverse=True)  # estável: mantém a nota dentro do dia
    return rows


# --- benchmark ------------------------------------------------------------------------


def _results_dir(settings: Settings) -> Path:
    return settings.eval_dir / "results"


def benchmark_runs(settings: Settings) -> list[dict[str, Any]]:
    out = []
    for path in sorted(_results_dir(settings).glob("eval_*.json"), reverse=True):
        runs, metas, meta = evaluation.load_results(path)
        out.append({"file": path.name, "date": meta.get("date"), "models": [r.model for r in runs],
                    "jobs": len(metas)})
    return out


def _resolve_run(settings: Settings, run: str | None) -> Path:
    if run is None:
        latest = evaluation.latest_results(_results_dir(settings))
        if latest is None:
            raise DashboardError(404, "Nenhum resultado de benchmark. Rode: python -m vagas_bot eval-models")
        return latest
    if not _RUN_FILE_RE.match(run):
        raise DashboardError(404, f"Resultado inválido: {run}")
    path = _results_dir(settings) / run
    if not path.is_file():
        raise DashboardError(404, f"Resultado não encontrado: {run}")
    return path


def benchmark_payload(settings: Settings, run: str | None) -> dict[str, Any]:
    runs, metas, meta = evaluation.load_results(_resolve_run(settings, run))
    labels = evaluation.load_labels(settings.eval_dir / "labels.yaml")
    by_id = {m.id: m for m in metas}
    summaries = [evaluation.summarize(r, by_id, labels) for r in runs]
    ref = summaries[0] if summaries else None

    summary_rows = []
    for s in summaries:
        row = {k: v for k, v in asdict(s).items() if k != "mean_totals"}
        row |= {
            "invalid_rate": s.invalid_rate,
            "fail_rate": s.fail_rate,
            "reliable": is_reliable(s),
            "agreement_with_ref": None if ref is None or s is ref else evaluation.agreement(ref, s),
        }
        summary_rows.append(row)

    jobs = []
    for m in metas:
        models = {}
        for r, s in zip(runs, summaries, strict=True):
            trials = sorted((t for t in r.trials if t.job_id == m.id), key=lambda t: t.run)
            models[r.model] = {
                "totals": [t.total for t in trials],
                "pj_status": [t.output.pj_status.value if t.output else None for t in trials],
                "mean": s.mean_totals.get(m.id),
            }
        jobs.append(asdict(m) | {"my_score": labels.get(m.id), "models": models})

    return {
        "meta": meta,
        "summaries": summary_rows,
        "reading": [_MARKDOWN_RE.sub("", line.removeprefix("- ")) for line in reading(summaries, len(labels))],
        "jobs": jobs,
    }


# --- notas ----------------------------------------------------------------------------


def find_job(settings: Settings, job_id: str) -> Job | None:
    """Archive (latest) → eval snapshots → history (rebuilt, low fidelity)."""
    for job in archived_jobs(load_archive(settings.jobs_archive_path)):
        if job.id == job_id:
            return job
    for job in evaluation.load_eval_jobs(settings.eval_dir / "jobs"):
        if job.id == job_id:
            return job
    for record in reversed(load_history(settings.history_path)):
        if record.get("id") == job_id:
            return job_from_history(record)
    return None


def save_label(settings: Settings, job_id: str, body: Any) -> dict[str, Any]:
    """PUT /api/labels/{id}: {"score": 0-100 | null, "note": "..."}."""
    if not isinstance(body, dict) or "score" not in body:
        raise DashboardError(400, 'Corpo inválido: envie {"score": 0-100 ou null, "note": "..."}')
    score, note = body["score"], body.get("note") or ""
    if score is not None and (isinstance(score, bool) or not isinstance(score, int) or not 0 <= score <= 100):
        raise DashboardError(400, "A nota deve ser um inteiro de 0 a 100 (ou null para apagar).")
    if not isinstance(note, str):
        raise DashboardError(400, "O comentário deve ser texto.")
    labels_path = settings.eval_dir / "labels.yaml"
    if score is None:
        evaluation.remove_label(labels_path, job_id)
        return {"id": job_id, "my_score": None, "my_note": ""}
    job = find_job(settings, job_id)
    if job is None:
        raise DashboardError(404, f"Vaga não encontrada: {job_id}")
    evaluation.save_eval_jobs([job], settings.eval_dir / "jobs")
    evaluation.set_label(labels_path, job.id, job.title, job.company, score, note.strip())
    return {"id": job.id, "my_score": score, "my_note": note.strip()}
