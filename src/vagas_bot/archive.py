"""data/jobs.jsonl: every new job of every run (after dedupe), with how far it went.

Raw material for the dashboard and for eval snapshots. One line per job per run:
the full Job (description included, CV never) + run_date, stage and filter_reason.
"""

import json
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any

from vagas_bot.config import FiltersConfig
from vagas_bot.filters import filter_reason
from vagas_bot.models import Job


class Stage(str, Enum):
    FILTERED = "filtered"  # caiu num filtro rígido (título, modalidade, CLT)
    EVALUATED = "evaluated"  # passou dos filtros, mas não foi para o email
    EMAILED = "emailed"


def archive_records(
    after_dedupe: list[Job],
    processed: list[Job],
    emailed_ids: set[str],
    filters: FiltersConfig,
    run_date: date,
) -> list[dict[str, Any]]:
    """`processed` = jobs after embeddings/LLM (they carry scores); the rest were filtered."""
    latest = {job.id: job for job in processed}
    records = []
    for original in after_dedupe:
        job = latest.get(original.id, original)
        if job.id in emailed_ids:
            stage, reason = Stage.EMAILED, None
        elif job.id in latest:
            stage, reason = Stage.EVALUATED, None
        else:
            stage, reason = Stage.FILTERED, filter_reason(job, filters) or "limit"  # cortada por --limit
        records.append(
            {"run_date": run_date.isoformat(), "stage": stage.value, "filter_reason": reason}
            | job.model_dump(mode="json")
        )
    return records


def append_archive(path: Path, records: list[dict[str, Any]]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")


def load_archive(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def archived_jobs(records: list[dict[str, Any]], stages: set[str] | None = None) -> list[Job]:
    """Jobs from archive records (most recent run wins for the same id)."""
    chosen: dict[str, dict[str, Any]] = {}
    for record in records:
        if stages is None or record.get("stage") in stages:
            chosen[record["id"]] = record
    return [Job.model_validate(r) for r in chosen.values()]
