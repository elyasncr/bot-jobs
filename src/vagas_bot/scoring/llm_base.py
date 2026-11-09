"""LLMScorer protocol and factory. The rest of the code never knows the provider."""

from typing import Protocol

from vagas_bot.config import ConfigError, Settings
from vagas_bot.models import Job, LLMScoreOutput, Prefs


class LLMUnavailable(Exception):
    """Server down or model missing: skip the LLM stage and fall back to embeddings."""


class LLMInvalidOutput(Exception):
    """The model answered, but not a valid LLMScoreOutput (after the retry)."""


class LLMScorer(Protocol):
    name: str  # "ollama/qwen3.5:9b"

    def healthcheck(self) -> None: ...  # levanta LLMUnavailable com mensagem clara

    def score(self, job: Job, cv_md: str, prefs: Prefs) -> LLMScoreOutput: ...


def get_scorer(settings: Settings) -> LLMScorer:
    cfg = settings.config.llm
    if cfg.provider == "ollama":
        from vagas_bot.scoring.llm_ollama import OllamaScorer  # noqa: PLC0415

        return OllamaScorer(cfg.ollama, host=settings.ollama_host)
    if cfg.provider == "anthropic":
        raise ConfigError("Provider LLM 'anthropic' ainda não implementado (Fase 10). Use llm.provider: ollama.")
    raise ConfigError(f"Provider LLM desconhecido: {cfg.provider}")
