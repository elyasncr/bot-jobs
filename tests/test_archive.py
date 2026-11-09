from datetime import date
from pathlib import Path

from helpers import make_job

from vagas_bot.archive import append_archive, archive_records, archived_jobs, load_archive
from vagas_bot.config import FiltersConfig
from vagas_bot.filters import filter_reason

CFG = FiltersConfig(modalities=["remote"], exclude_title_keywords=["junior"])


def test_filter_reason() -> None:
    assert filter_reason(make_job(), CFG) is None
    assert filter_reason(make_job(title="AI Engineer Junior"), CFG) == "title"
    assert filter_reason(make_job(is_remote=False, location="São Paulo", description="Presencial. PJ."), CFG) == "modality"
    assert filter_reason(make_job(description="Regime CLT."), CFG) == "clt"


def test_archive_records_stages() -> None:
    kept, evaluated, dropped = make_job(title="AI A"), make_job(title="AI B"), make_job(title="AI Junior")
    scored = kept.model_copy(update={"embedding_score": 0.8})
    records = archive_records([kept, evaluated, dropped], [scored, evaluated], {kept.id}, CFG, date(2026, 11, 9))

    by_title = {r["title"]: r for r in records}
    assert by_title["AI A"]["stage"] == "emailed" and by_title["AI A"]["embedding_score"] == 0.8
    assert by_title["AI B"]["stage"] == "evaluated"
    assert by_title["AI Junior"]["stage"] == "filtered" and by_title["AI Junior"]["filter_reason"] == "title"
    assert all(r["run_date"] == "2026-11-09" and r["description"] for r in records)


def test_archive_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "jobs.jsonl"
    job = make_job()
    append_archive(path, archive_records([job], [job], set(), CFG, date(2026, 11, 9)))
    append_archive(path, archive_records([job], [], set(), FiltersConfig(modalities=["hybrid"]), date(2026, 11, 10)))
    records = load_archive(path)
    assert len(records) == 2
    assert [j.id for j in archived_jobs(records)] == [job.id]
    assert archived_jobs(records, {"emailed"}) == []
