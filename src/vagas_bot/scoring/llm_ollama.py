"""Default LLM provider: Ollama `chat` with native structured output (format = JSON schema)."""

import httpx
import ollama
from pydantic import ValidationError

from vagas_bot.config import OllamaLLMConfig
from vagas_bot.log import get_logger
from vagas_bot.models import Job, LLMScoreOutput, Prefs
from vagas_bot.ollama_utils import (
    OllamaUnavailable,
    is_model_available,
    list_local_models,
    pull_hint,
)
from vagas_bot.scoring.llm_base import LLMInvalidOutput, LLMUnavailable
from vagas_bot.scoring.prompts import build_messages, estimate_tokens

log = get_logger("llm.ollama")

CONTEXT_WARN_RATIO = 0.85
MAX_ATTEMPTS = 2  # 1 tentativa + 1 retry em JSON inválido


class OllamaScorer:
    def __init__(self, cfg: OllamaLLMConfig, host: str) -> None:
        self.cfg = cfg
        self.host = host
        self.name = f"ollama/{cfg.model}"
        self._client = ollama.Client(host=host, timeout=cfg.request_timeout_s)
        self._schema = LLMScoreOutput.model_json_schema()
        self.calls = 0  # chamadas ao chat (inclui retries); usado pelo eval-models
        self.invalid_attempts = 0  # respostas que não validaram no schema

    def healthcheck(self) -> None:
        try:
            available = list_local_models(self.host)
        except OllamaUnavailable as exc:
            raise LLMUnavailable(str(exc)) from exc
        if not is_model_available(self.cfg.model, available):
            raise LLMUnavailable(pull_hint(self.cfg.model))

    def score(self, job: Job, cv_md: str, prefs: Prefs) -> LLMScoreOutput:
        messages = build_messages(job, cv_md, prefs)
        self._warn_context(messages, job)
        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            content = self._chat(messages)
            try:
                return LLMScoreOutput.model_validate_json(content)
            except ValidationError as exc:
                last_error = exc
                self.invalid_attempts += 1
                log.warning("JSON inválido do LLM (tentativa %d/%d) para '%s': %s",
                            attempt, MAX_ATTEMPTS, job.title, _short(exc))
        raise LLMInvalidOutput(f"JSON inválido após {MAX_ATTEMPTS} tentativas: {_short(last_error)}")

    def _chat(self, messages: list[dict[str, str]]) -> str:
        self.calls += 1
        try:
            response = self._client.chat(
                model=self.cfg.model,
                messages=messages,
                format=self._schema,
                options={"num_ctx": self.cfg.num_ctx, "temperature": self.cfg.temperature},
                think=self.cfg.think,
                keep_alive=self.cfg.keep_alive,
            )
        except ConnectionError as exc:
            raise LLMUnavailable(f"Ollama caiu durante o scoring: {exc}") from exc
        except httpx.TimeoutException as exc:
            raise LLMInvalidOutput(f"timeout após {self.cfg.request_timeout_s:.0f}s") from exc
        except ollama.ResponseError as exc:
            raise LLMInvalidOutput(f"erro do Ollama: {exc}") from exc
        return response.message.content or ""

    def _warn_context(self, messages: list[dict[str, str]], job: Job) -> None:
        tokens = estimate_tokens(messages)
        if tokens > CONTEXT_WARN_RATIO * self.cfg.num_ctx:
            log.warning(
                "Prompt de '%s' tem ~%d tokens (> %d%% de num_ctx=%d): risco de truncamento.",
                job.title, tokens, int(CONTEXT_WARN_RATIO * 100), self.cfg.num_ctx,
            )


def _short(exc: Exception | None, limit: int = 200) -> str:
    return str(exc).replace("\n", " ")[:limit] if exc else ""
