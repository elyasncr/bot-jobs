"""State in data/seen.json: {"<id or fingerprint>": "YYYY-MM-DD"} with atomic writes."""

import json
import os
import tempfile
from collections.abc import Iterable
from datetime import date, timedelta
from pathlib import Path

from vagas_bot.models import Job


class StorageError(Exception):
    """State file is unreadable."""


def load_seen(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise StorageError(
            f"{path} está corrompido ({exc}). Corrija ou apague o arquivo (vagas antigas voltarão)."
        ) from exc
    if not isinstance(data, dict):
        raise StorageError(f"{path} deveria conter um objeto JSON.")
    return {str(k): str(v) for k, v in data.items()}


def prune_seen(seen: dict[str, str], today: date, days: int) -> dict[str, str]:
    cutoff = (today - timedelta(days=days)).isoformat()
    return {key: day for key, day in seen.items() if day >= cutoff}


def mark_seen(seen: dict[str, str], jobs: Iterable[Job], today: date) -> dict[str, str]:
    updated = dict(seen)
    stamp = today.isoformat()
    for job in jobs:
        updated[job.id] = stamp
        updated[job.fingerprint] = stamp
    return updated


def atomic_write_text(path: Path, text: str) -> None:
    """Write to a temp file in the same folder, then rename over the target."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as tmp:
            tmp.write(text)
            tmp.flush()
            os.fsync(tmp.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def save_seen(path: Path, seen: dict[str, str]) -> None:
    atomic_write_text(path, json.dumps(dict(sorted(seen.items())), indent=0, ensure_ascii=False))


def history_record(job: Job, job_text: str, embedder: str, today: date) -> dict[str, object]:
    """One line of history.jsonl. Never includes CV data."""
    assert job.score is not None
    s = job.score
    return {
        "date": today.isoformat(),
        "id": job.id,
        "title": job.title,
        "company": job.company,
        "job_text": job_text,
        "embedding_score": job.embedding_score,
        "embedder": embedder,
        "technical": s.technical,
        "seniority": s.seniority,
        "domain": s.domain,
        "modality_contract": s.modality_contract,
        "language": s.language,
        "total": s.total,
        "pj_status": job.pj_status.value,
        "llm_model": s.model,
    }


def append_history(path: Path, records: list[dict[str, object]]) -> None:
    if not records:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
