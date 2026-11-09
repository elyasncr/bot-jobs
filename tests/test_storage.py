from datetime import date
from pathlib import Path

import pytest
from helpers import make_job

from vagas_bot.storage import (
    StorageError,
    append_history,
    history_record,
    load_seen,
    mark_seen,
    prune_seen,
    save_seen,
)


def test_load_missing_returns_empty(tmp_path: Path) -> None:
    assert load_seen(tmp_path / "seen.json") == {}


def test_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "data" / "seen.json"
    save_seen(path, {"b": "2026-11-09", "a": "2026-11-08"})
    assert load_seen(path) == {"a": "2026-11-08", "b": "2026-11-09"}
    assert list(path.parent.glob("*.tmp")) == []


def test_corrupt_file_raises_clear_error(tmp_path: Path) -> None:
    path = tmp_path / "seen.json"
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(StorageError, match="corrompido"):
        load_seen(path)


def test_prune_keeps_recent_entries() -> None:
    seen = {"old": "2026-08-01", "edge": "2026-09-10", "new": "2026-11-08"}
    assert prune_seen(seen, date(2026, 11, 9), days=60) == {"edge": "2026-09-10", "new": "2026-11-08"}


def test_history_record_and_append(tmp_path: Path) -> None:
    from helpers import llm_output

    from vagas_bot.scoring.llm_stage import to_score_result

    job = make_job(id="j1", embedding_score=0.61).model_copy(
        update={"score": to_score_result(llm_output(), "ollama/qwen3.5:9b", 3.2)}
    )
    record = history_record(job, "AI Engineer\nEmpresa\n...", "ollama/bge-m3", date(2026, 11, 9))
    assert record["total"] == 78 and record["llm_model"] == "ollama/qwen3.5:9b"
    assert record["embedder"] == "ollama/bge-m3" and record["embedding_score"] == 0.61
    assert set(record) == {
        "date", "id", "title", "company", "job_text", "embedding_score", "embedder", "technical",
        "seniority", "domain", "modality_contract", "language", "total", "pj_status", "llm_model",
    }
    path = tmp_path / "history.jsonl"
    append_history(path, [record])
    append_history(path, [record])
    assert len(path.read_text(encoding="utf-8").splitlines()) == 2


def test_mark_seen_adds_id_and_fingerprint() -> None:
    job = make_job(id="job-1")
    updated = mark_seen({"x": "2026-11-01"}, [job], date(2026, 11, 9))
    assert updated == {"x": "2026-11-01", "job-1": "2026-11-09", job.fingerprint: "2026-11-09"}
