"""Final ranking: weighted LLM total, or an embedding-based estimate as fallback."""

from dataclasses import dataclass

from vagas_bot.models import Job, LLMScoreOutput

WEIGHTS = {
    "technical": 0.45,
    "seniority": 0.20,
    "domain": 0.15,
    "modality_contract": 0.10,
    "language": 0.10,
}
FLAT_RANGE_ESTIMATE = 50  # quando todas as similaridades do lote são iguais (ou só há uma vaga)


@dataclass(frozen=True)
class RankedJob:
    job: Job
    total: int  # 0–100, o "%" exibido
    is_estimate: bool  # True = veio do embedding, não do LLM


def weighted_total(score: LLMScoreOutput) -> int:
    return round(sum(getattr(score, field) * weight for field, weight in WEIGHTS.items()))


def estimate_totals(jobs: list[Job]) -> dict[str, int]:
    """Min-max rescale of embedding_score within the batch to 0–100."""
    scores = {j.id: j.embedding_score for j in jobs if j.embedding_score is not None}
    if not scores:
        return {}
    low, high = min(scores.values()), max(scores.values())
    if high - low < 1e-9:
        return dict.fromkeys(scores, FLAT_RANGE_ESTIMATE)
    return {job_id: round(100 * (s - low) / (high - low)) for job_id, s in scores.items()}


def rank(jobs: list[Job], min_score: int, max_jobs: int) -> list[RankedJob]:
    """LLM total when available, else the batch estimate; drop < min_score, sort, cap."""
    estimates = estimate_totals(jobs)
    ranked: list[RankedJob] = []
    for job in jobs:
        if job.score is not None:
            ranked.append(RankedJob(job, job.score.total, is_estimate=False))
        elif job.id in estimates:
            ranked.append(RankedJob(job, estimates[job.id], is_estimate=True))
    kept = [r for r in ranked if r.total >= min_score]
    kept.sort(key=lambda r: (r.total, r.job.embedding_score or 0.0), reverse=True)
    return kept[:max_jobs]
