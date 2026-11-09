from helpers import make_job

from vagas_bot.models import LLMScoreOutput, PJStatus, ScoreResult
from vagas_bot.scoring.ranker import estimate_totals, rank, weighted_total


def _llm(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "technical": 80,
        "seniority": 70,
        "domain": 60,
        "modality_contract": 100,
        "language": 90,
        "pj_status": PJStatus.PJ,
        "strengths": [],
        "gaps": [],
        "summary": "ok",
    }
    return base | overrides


def _score(total: int) -> ScoreResult:
    return ScoreResult.model_validate(_llm() | {"total": total, "model": "fake", "latency_s": 1.0})


def test_weighted_total() -> None:
    out = LLMScoreOutput.model_validate(_llm())
    # 0.45*80 + 0.20*70 + 0.15*60 + 0.10*100 + 0.10*90 = 36 + 14 + 9 + 10 + 9 = 78
    assert weighted_total(out) == 78


def test_weighted_total_rounds() -> None:
    out = LLMScoreOutput.model_validate(_llm(technical=81, seniority=0, domain=0, modality_contract=0, language=0))
    assert weighted_total(out) == round(0.45 * 81)  # 36.45 → 36


def test_estimate_min_max() -> None:
    jobs = [
        make_job(title="A", embedding_score=0.50),
        make_job(title="B", embedding_score=0.70),
        make_job(title="C", embedding_score=0.60),
        make_job(title="D", embedding_score=None),
    ]
    est = estimate_totals(jobs)
    assert est == {jobs[0].id: 0, jobs[1].id: 100, jobs[2].id: 50}


def test_estimate_flat_batch() -> None:
    jobs = [make_job(title="A", embedding_score=0.6)]
    assert estimate_totals(jobs) == {jobs[0].id: 50}


def test_rank_fallback_filters_sorts_and_caps() -> None:
    jobs = [make_job(title=t, embedding_score=s) for t, s in [("A", 0.5), ("B", 0.9), ("C", 0.8), ("D", 0.7)]]
    ranked = rank(jobs, min_score=50, max_jobs=2)
    assert [(r.job.title, r.total, r.is_estimate) for r in ranked] == [("B", 100, True), ("C", 75, True)]


def test_rank_prefers_llm_score() -> None:
    jobs = [
        make_job(title="LLM", embedding_score=0.1, score=_score(90)),
        make_job(title="Emb", embedding_score=0.9),
        make_job(title="Low", embedding_score=0.5),
    ]
    ranked = rank(jobs, min_score=50, max_jobs=10)
    # LLM usa o total do LLM (90), não a estimativa (seria 0); Emb=100 e Low=50 vêm do min-max
    assert [(r.job.title, r.total, r.is_estimate) for r in ranked] == [
        ("Emb", 100, True),
        ("LLM", 90, False),
        ("Low", 50, True),
    ]


def test_rank_skips_jobs_without_any_score() -> None:
    assert rank([make_job(title="X")], min_score=0, max_jobs=10) == []
