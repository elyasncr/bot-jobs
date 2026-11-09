from typing import Any

import numpy as np

from vagas_bot.embeddings.base import l2_normalize
from vagas_bot.models import Job, LLMScoreOutput, PJStatus, Prefs
from vagas_bot.scoring.llm_base import LLMInvalidOutput, LLMUnavailable
from vagas_bot.text import make_fingerprint


def llm_output(**overrides: Any) -> LLMScoreOutput:
    base: dict[str, Any] = {
        "technical": 80,
        "seniority": 70,
        "domain": 60,
        "modality_contract": 100,
        "language": 90,
        "pj_status": PJStatus.PJ,
        "strengths": ["LLMs"],
        "gaps": [],
        "summary": "Boa aderência.",
    }
    return LLMScoreOutput.model_validate(base | overrides)


class FakeScorer:
    """Scores by title: 'invalid' → LLMInvalidOutput, 'crash' → LLMUnavailable, else llm_output()."""

    name = "fake/llm"

    def __init__(self, down: bool = False, output: LLMScoreOutput | None = None) -> None:
        self.down = down
        self.output = output or llm_output()
        self.scored: list[str] = []

    def healthcheck(self) -> None:
        if self.down:
            raise LLMUnavailable("Ollama não responde. Rode: ollama serve")

    def score(self, job: Job, cv_md: str, prefs: Prefs) -> LLMScoreOutput:
        if "invalid" in job.title:
            raise LLMInvalidOutput("JSON inválido")
        if "crash" in job.title:
            raise LLMUnavailable("caiu")
        self.scored.append(job.title)
        return self.output

KEYWORD_AXES = ("llm", "rag", "padeiro")


class FakeEmbedder:
    """Deterministic embedder: one axis per keyword in KEYWORD_AXES, plus a bias axis."""

    name = "fake/keywords"

    def __init__(self) -> None:
        self.released = 0
        self.healthchecks = 0
        self.query_calls: list[list[str]] = []

    def healthcheck(self) -> None:
        self.healthchecks += 1

    def _vec(self, text: str) -> list[float]:
        low = text.lower()
        return [float(low.count(k)) for k in KEYWORD_AXES] + [0.1]

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        self.query_calls.append(texts)
        return l2_normalize(np.array([self._vec(t) for t in texts]))

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return l2_normalize(np.array([self._vec(t) for t in texts]))

    def release(self) -> None:
        self.released += 1


def make_job(**overrides: Any) -> Job:
    """A remote PJ AI job that passes every filter unless overridden."""
    title = overrides.pop("title", "AI Engineer")
    company = overrides.pop("company", "Empresa")
    base: dict[str, Any] = {
        "id": f"id-{title}-{company}",
        "fingerprint": make_fingerprint(title, company),
        "source": "fake",
        "publisher": "LinkedIn",
        "title": title,
        "company": company,
        "location": "Rio de Janeiro, RJ",
        "is_remote": True,
        "employment_type": "FULLTIME",
        "description": "Vaga de IA. Contratação PJ.",
        "url": "https://example.com/job",
        "posted_at": None,
    }
    return Job.model_validate(base | overrides)
