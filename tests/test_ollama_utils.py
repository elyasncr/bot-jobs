from types import SimpleNamespace

import pytest

from vagas_bot import ollama_utils
from vagas_bot.ollama_utils import (
    OllamaUnavailable,
    is_model_available,
    list_local_models,
    normalize_model_name,
)


def test_normalize_adds_latest_tag() -> None:
    assert normalize_model_name("bge-m3") == "bge-m3:latest"
    assert normalize_model_name("qwen3.5:9b") == "qwen3.5:9b"


def test_is_model_available() -> None:
    available = {"bge-m3:latest", "qwen3.5:9b"}
    assert is_model_available("bge-m3", available)
    assert is_model_available("qwen3.5:9b", available)
    assert not is_model_available("gpt-oss:20b", available)


class _FakeClient:
    def __init__(self, models: list[str] | None = None, down: bool = False, **_: object) -> None:
        self._models = models or []
        self._down = down

    def list(self) -> SimpleNamespace:
        if self._down:
            raise ConnectionError("Failed to connect to Ollama.")
        return SimpleNamespace(models=[SimpleNamespace(model=m) for m in self._models])


def test_list_local_models(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ollama_utils.ollama, "Client", lambda **kw: _FakeClient(["bge-m3", "qwen3:14b"]))
    assert list_local_models("http://x") == {"bge-m3:latest", "qwen3:14b"}


def test_list_local_models_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ollama_utils.ollama, "Client", lambda **kw: _FakeClient(down=True))
    with pytest.raises(OllamaUnavailable, match="ollama serve"):
        list_local_models("http://x")
