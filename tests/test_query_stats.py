import json
from datetime import date
from pathlib import Path

from helpers import make_job

from vagas_bot.models import ScoreResult
from vagas_bot.query_stats import append_query_stats, build_query_stats
from vagas_bot.scoring.ranker import RankedJob


def test_attribution_to_first_query(tmp_path: Path) -> None:
    a, b, c = make_job(title="A"), make_job(title="B"), make_job(title="C")
    origin = {a.fingerprint: "q1", b.fingerprint: "q1", c.fingerprint: "q2"}
    score = ScoreResult.model_validate(
        {"technical": 90, "seniority": 90, "domain": 90, "modality_contract": 90, "language": 90,
         "pj_status": "pj", "strengths": [], "gaps": [], "summary": "", "total": 90, "model": "m", "latency_s": 1}
    )
    stats = build_query_stats(
        fetched_by_query={"q1": 2, "q2": 3},  # q2 também trouxe A e B, mas q1 achou primeiro
        origin_by_fingerprint=origin,
        full_page_queries={"q2"},
        after_dedupe=[a, b, c],
        after_filters=[a, c],
        ranked=[RankedJob(a.model_copy(update={"score": score}), 90, False), RankedJob(c, 60, True)],
        min_score=50,
    )
    by_q = {s.query: s for s in stats}
    assert (by_q["q1"].fetched, by_q["q1"].first_found, by_q["q1"].new, by_q["q1"].passed_filters) == (2, 2, 2, 1)
    assert (by_q["q1"].emailed, by_q["q1"].llm_high) == (1, 1)
    assert (by_q["q2"].fetched, by_q["q2"].first_found, by_q["q2"].emailed, by_q["q2"].llm_high) == (3, 1, 1, 0)
    assert by_q["q2"].more_pages and not by_q["q1"].more_pages

    path = tmp_path / "data" / "query_stats.jsonl"
    append_query_stats(path, stats, date(2026, 11, 9))
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [line["query"] for line in lines] == ["q1", "q2"]
    assert lines[0]["date"] == "2026-11-09"
