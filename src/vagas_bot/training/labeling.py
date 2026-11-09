"""`label` command helpers: which history jobs to ask about, and how to show them."""

import random
from typing import Any

from vagas_bot.models import Job
from vagas_bot.text import make_fingerprint

DOUBT_RANGE = (40, 75)  # notas do LLM onde há mais dúvida: perguntar primeiro
PREVIEW_CHARS = 600


def pick_candidates(history: list[dict[str, Any]], labeled: set[str], n: int, seed: int) -> list[dict[str, Any]]:
    """Unlabeled history jobs (latest record per id); LLM total within 40–75 first, shuffled."""
    latest: dict[str, dict[str, Any]] = {}
    for record in history:
        if record.get("id") and record["id"] not in labeled:
            latest[record["id"]] = record
    records = sorted(latest.values(), key=lambda r: r["id"])
    random.Random(seed).shuffle(records)
    low, high = DOUBT_RANGE
    doubtful = [r for r in records if low <= (r.get("total") or 0) <= high]
    others = [r for r in records if r not in doubtful]
    return (doubtful + others)[:n]


def job_from_history(record: dict[str, Any]) -> Job:
    """A Job rebuilt from a history line (job_text = title\\ncompany\\ndescription)."""
    title, company = record.get("title", ""), record.get("company", "")
    text: str = record.get("job_text", "")
    lines = text.split("\n", 2)
    description = lines[2] if len(lines) == 3 else text
    return Job(
        id=record["id"], fingerprint=make_fingerprint(title, company), source="history", publisher=None,
        title=title, company=company, location=None, is_remote=None, employment_type=None,
        description=description, url="", posted_at=None, low_fidelity=True,
    )


def describe(record: dict[str, Any], job: Job) -> str:
    summary = " ".join(job.description.split())[:PREVIEW_CHARS]
    lines = [
        f"{job.title} · {job.company}",
        f"Local: {job.location or '—'} · publisher: {job.publisher or '—'} · nota do LLM: {record.get('total', '—')}%",
    ]
    if job.url:
        lines.append(f"Link: {job.url}")
    lines += ["", summary + ("…" if len(job.description) > PREVIEW_CHARS else "")]
    return "\n".join(lines)
