"""LLM scoring stage: sequential (one GPU, one model), with per-job fallback to embeddings."""

import time
from dataclasses import dataclass, field

from vagas_bot.filters import has_clt_signals
from vagas_bot.log import get_logger
from vagas_bot.models import Job, LLMScoreOutput, PJStatus, Prefs, ScoreResult
from vagas_bot.scoring.llm_base import LLMInvalidOutput, LLMScorer, LLMUnavailable
from vagas_bot.scoring.ranker import weighted_total

log = get_logger("llm")


@dataclass
class LLMStageInfo:
    model: str
    scored: int = 0
    failed: int = 0
    available: bool = True
    latencies: list[float] = field(default_factory=list)

    @property
    def total_s(self) -> float:
        return sum(self.latencies)

    @property
    def avg_s(self) -> float:
        return self.total_s / len(self.latencies) if self.latencies else 0.0


def to_score_result(output: LLMScoreOutput, model: str, latency_s: float) -> ScoreResult:
    return ScoreResult(
        **output.model_dump(), total=weighted_total(output), model=model, latency_s=round(latency_s, 2)
    )


def merge_pj_status(job: Job, llm_status: PJStatus) -> PJStatus:
    """The LLM has the final word only where the regex was uncertain.

    Guard: an LLM "clt" (which discards the job) is accepted only with CLT evidence in the text.
    Live test 2026-11-09: qwen3.5:9b answered "clt" for remote jobs that never mention a contract.
    """
    if job.pj_status is not PJStatus.UNCERTAIN:
        return job.pj_status
    if llm_status is PJStatus.CLT and not has_clt_signals(job):
        log.info("  LLM disse CLT sem evidência no texto em '%s': mantida como incerta.", job.title)
        return PJStatus.UNCERTAIN
    return llm_status


def llm_stage(
    jobs: list[Job], scorer: LLMScorer, cv_md: str, prefs: Prefs, max_calls: int
) -> tuple[list[Job], LLMStageInfo]:
    """Score jobs in order. Jobs that fail keep score=None (the ranker uses the estimate)."""
    info = LLMStageInfo(model=scorer.name)
    if not jobs:
        return jobs, info
    try:
        scorer.healthcheck()
    except LLMUnavailable as exc:
        log.error("LLM indisponível: %s. Seguindo com estimativa por embeddings.", exc)
        info.available = False
        return jobs, info

    result: list[Job] = []
    for index, job in enumerate(jobs):
        if index >= max_calls:
            log.warning("Limite max_calls_per_run=%d atingido: %d vagas ficam com estimativa.",
                        max_calls, len(jobs) - index)
            result.extend(jobs[index:])
            break
        t0 = time.perf_counter()
        try:
            output = scorer.score(job, cv_md, prefs)
        except LLMInvalidOutput as exc:
            info.failed += 1
            log.warning("LLM falhou em '%s' (%s): usando estimativa.", job.title, exc)
            result.append(job)
            continue
        except LLMUnavailable as exc:
            info.available = False
            log.error("LLM caiu no meio da etapa (%s): %d vagas ficam com estimativa.", exc, len(jobs) - index)
            result.extend(jobs[index:])
            break
        latency = time.perf_counter() - t0
        info.scored += 1
        info.latencies.append(latency)
        score = to_score_result(output, scorer.name, latency)
        result.append(
            job.model_copy(update={"score": score, "pj_status": merge_pj_status(job, output.pj_status)})
        )
        log.info("  LLM %d/%d: %3d%% em %.1fs · %s", index + 1, len(jobs), score.total, latency, job.title)

    log.info(
        "LLM (%s): %d avaliadas, %d falhas, %.1fs no total, %.1fs/vaga.",
        scorer.name, info.scored, info.failed, info.total_s, info.avg_s,
    )
    return result, info
