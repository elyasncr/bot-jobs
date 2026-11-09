import json
import logging
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from helpers import llm_output, make_job

from vagas_bot.config import OllamaLLMConfig
from vagas_bot.models import LLMScoreOutput, PJStatus, Prefs
from vagas_bot.scoring import llm_ollama
from vagas_bot.scoring.llm_base import LLMInvalidOutput, LLMUnavailable
from vagas_bot.scoring.llm_ollama import OllamaScorer

PREFS = Prefs(modalities=["remote"], hybrid_allowed_cities=["Rio de Janeiro"])
CV = "# Fulano\n\n## Resumo\nEngenheiro de IA."
VALID = llm_output().model_dump_json()


class FakeChatClient:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = responses
        self.calls: list[dict[str, Any]] = []

    def chat(self, **kwargs: Any) -> SimpleNamespace:
        self.calls.append(kwargs)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(message=SimpleNamespace(content=item))


def _scorer(monkeypatch: pytest.MonkeyPatch, responses: list[Any], **cfg: Any) -> tuple[OllamaScorer, FakeChatClient]:
    client = FakeChatClient(responses)
    monkeypatch.setattr(llm_ollama.ollama, "Client", lambda **kw: client)
    return OllamaScorer(OllamaLLMConfig(**cfg), host="http://x"), client


def test_valid_response(monkeypatch: pytest.MonkeyPatch) -> None:
    scorer, client = _scorer(monkeypatch, [VALID])
    out = scorer.score(make_job(), CV, PREFS)
    assert out.technical == 80 and out.pj_status is PJStatus.PJ
    assert len(client.calls) == 1


def test_sends_num_ctx_format_think_keep_alive(monkeypatch: pytest.MonkeyPatch) -> None:
    scorer, client = _scorer(monkeypatch, [VALID], num_ctx=16384, temperature=0, think=False, keep_alive="10m")
    scorer.score(make_job(), CV, PREFS)
    call = client.calls[0]
    assert call["model"] == "qwen3.5:9b"
    assert call["format"] == LLMScoreOutput.model_json_schema()
    assert call["options"] == {"num_ctx": 16384, "temperature": 0}
    assert call["think"] is False
    assert call["keep_alive"] == "10m"
    roles = [m["role"] for m in call["messages"]]
    assert roles == ["system", "user"]
    assert CV in call["messages"][1]["content"]


def test_invalid_then_valid_retries_once(monkeypatch: pytest.MonkeyPatch) -> None:
    scorer, client = _scorer(monkeypatch, ["{not json", VALID])
    assert scorer.score(make_job(), CV, PREFS).technical == 80
    assert len(client.calls) == 2


def test_invalid_twice_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    bad = json.dumps({"technical": 500})
    scorer, client = _scorer(monkeypatch, [bad, "{"])
    with pytest.raises(LLMInvalidOutput):
        scorer.score(make_job(), CV, PREFS)
    assert len(client.calls) == 2


def test_ollama_down_raises_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    scorer, _ = _scorer(monkeypatch, [ConnectionError("Failed to connect to Ollama")])
    with pytest.raises(LLMUnavailable):
        scorer.score(make_job(), CV, PREFS)


def test_timeout_is_invalid_output_for_that_job(monkeypatch: pytest.MonkeyPatch) -> None:
    scorer, _ = _scorer(monkeypatch, [httpx.ReadTimeout("slow")])
    with pytest.raises(LLMInvalidOutput, match="timeout"):
        scorer.score(make_job(), CV, PREFS)


def test_healthcheck_down(monkeypatch: pytest.MonkeyPatch) -> None:
    scorer, _ = _scorer(monkeypatch, [])

    def down(host: str) -> set[str]:
        raise llm_ollama.OllamaUnavailable("Ollama não responde. Rode: ollama serve")

    monkeypatch.setattr(llm_ollama, "list_local_models", down)
    with pytest.raises(LLMUnavailable, match="ollama serve"):
        scorer.healthcheck()


def test_healthcheck_missing_model(monkeypatch: pytest.MonkeyPatch) -> None:
    scorer, _ = _scorer(monkeypatch, [])
    monkeypatch.setattr(llm_ollama, "list_local_models", lambda host: {"bge-m3:latest"})
    with pytest.raises(LLMUnavailable, match="ollama pull qwen3.5:9b"):
        scorer.healthcheck()


def test_context_warning(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    scorer, _ = _scorer(monkeypatch, [VALID], num_ctx=2048)
    logger = logging.getLogger("vagas_bot")
    logger.propagate = True
    try:
        with caplog.at_level(logging.WARNING, logger="vagas_bot"):
            scorer.score(make_job(description="x" * 12000), CV, PREFS)
    finally:
        logger.propagate = False
    assert "risco de truncamento" in caplog.text
