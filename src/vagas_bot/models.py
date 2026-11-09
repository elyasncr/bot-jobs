"""Core data models: Job, PJStatus, LLM score output and final score."""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class PJStatus(str, Enum):
    PJ = "pj"  # explicitamente PJ / contractor
    BOTH = "both"  # aceita CLT ou PJ
    CLT = "clt"  # explicitamente só CLT → descartar
    UNCERTAIN = "uncertain"


class LLMScoreOutput(BaseModel):
    """What the LLM returns. The weighted total is computed in code, never by the LLM."""

    technical: int = Field(ge=0, le=100)
    seniority: int = Field(ge=0, le=100)
    domain: int = Field(ge=0, le=100)
    modality_contract: int = Field(ge=0, le=100)
    language: int = Field(ge=0, le=100)
    pj_status: PJStatus
    strengths: list[str] = Field(max_length=3)
    gaps: list[str] = Field(max_length=3)
    summary: str


class Prefs(BaseModel):
    """Candidate preferences sent to the LLM (derived from config.filters)."""

    modalities: list[str]
    hybrid_allowed_cities: list[str]
    contract: str = "PJ"


class ScoreResult(LLMScoreOutput):
    total: int = Field(ge=0, le=100)  # 0–100, calculado no código; é o "%" exibido
    model: str  # ex.: "ollama/qwen3.5:9b"
    latency_s: float


class Job(BaseModel):
    id: str  # id da fonte
    fingerprint: str  # sha1(normalize(title) + normalize(company))
    source: str  # "jsearch", "linkedin_alerts"
    publisher: str | None
    title: str
    company: str
    location: str | None
    is_remote: bool | None
    employment_type: str | None
    description: str
    url: str
    posted_at: datetime | None
    low_fidelity: bool = False  # sem descrição completa
    pj_status: PJStatus = PJStatus.UNCERTAIN
    embedding_score: float | None = None
    score: ScoreResult | None = None
