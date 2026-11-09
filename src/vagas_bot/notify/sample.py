"""Deterministic fake jobs for `test-email` and the email snapshot tests."""

from datetime import UTC, datetime

from vagas_bot.models import Job, PJStatus, ScoreResult
from vagas_bot.scoring.ranker import RankedJob
from vagas_bot.text import make_fingerprint

_TEMPLATES = [
    ("Senior AI Engineer (LLMs & RAG)", "Empresa Exemplo A", PJStatus.PJ, 88, False),
    ("Machine Learning Engineer - Remote", "Empresa Exemplo B", PJStatus.BOTH, 72, False),
    ("Data Scientist (GenAI)", "Empresa Exemplo C", PJStatus.UNCERTAIN, 58, True),
]


def _job(index: int, title: str, company: str, pj: PJStatus, total: int, estimate: bool) -> RankedJob:
    score = None if estimate else ScoreResult(
        technical=min(100, total + 5), seniority=total, domain=total, modality_contract=90, language=70,
        pj_status=pj, strengths=["LLMs e RAG em produção", "LangGraph e agentes", "AWS Bedrock"],
        gaps=["Kubernetes não citado no CV", "Inglês fluente desejável"],
        summary="Boa aderência técnica; a senioridade pedida está um pouco acima.",
        total=total, model="ollama/qwen3.5:9b", latency_s=2.8,
    )
    job = Job(
        id=f"sample-{index}", fingerprint=make_fingerprint(f"{title} {index}", company), source="sample",
        publisher="LinkedIn" if index % 2 == 0 else "Glassdoor", title=title, company=company,
        location="Qualquer lugar", is_remote=True, employment_type="CONTRACTOR" if pj is PJStatus.PJ else None,
        description="Descrição de exemplo." * 20, url=f"https://example.com/vaga/{index}",
        posted_at=datetime(2026, 11, 8, 12, tzinfo=UTC), low_fidelity=estimate and index % 2 == 0,
        pj_status=pj, embedding_score=0.6, score=score,
    )
    return RankedJob(job, total, is_estimate=estimate)


def sample_ranked(n: int = 3) -> list[RankedJob]:
    items = []
    for i in range(n):
        title, company, pj, total, estimate = _TEMPLATES[i % len(_TEMPLATES)]
        items.append(_job(i, title if i < len(_TEMPLATES) else f"{title} #{i}", company, pj, total - i // 3, estimate))
    return sorted(items, key=lambda r: r.total, reverse=True)
