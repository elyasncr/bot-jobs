"""Shared helpers to talk to the local Ollama server (health and model availability)."""

import time

import ollama


class OllamaUnavailable(Exception):
    """Ollama server is down or unreachable."""


def normalize_model_name(name: str) -> str:
    """Ollama implies ':latest' when no tag is given."""
    return name if ":" in name else f"{name}:latest"


def list_local_models(host: str, timeout_s: float = 5.0) -> set[str]:
    client = ollama.Client(host=host, timeout=timeout_s)
    try:
        response = client.list()
    except ConnectionError as exc:
        raise OllamaUnavailable(f"Ollama não responde em {host}. Rode: ollama serve") from exc
    return {normalize_model_name(m.model) for m in response.models if m.model}


def is_model_available(name: str, available: set[str]) -> bool:
    return normalize_model_name(name) in available


def pull_hint(name: str) -> str:
    return f"Modelo {name} não encontrado. Rode: ollama pull {name}"


def loaded_vram_gb(host: str, model: str, timeout_s: float = 5.0) -> float | None:
    """VRAM used by a loaded model (ollama ps), or None if it is not loaded."""
    client = ollama.Client(host=host, timeout=timeout_s)
    try:
        running = client.ps().models
    except (ConnectionError, ollama.ResponseError):
        return None
    wanted = normalize_model_name(model)
    for item in running:
        if normalize_model_name(item.model or "") == wanted and item.size_vram is not None:
            return round(item.size_vram / 1024**3, 1)
    return None


def unload_model(host: str, model: str, timeout_s: float = 30.0) -> None:
    """Free the model's VRAM now (keep_alive=0) and wait until Ollama lists it as gone."""
    client = ollama.Client(host=host, timeout=timeout_s)
    wanted = normalize_model_name(model)
    try:
        client.generate(model=model, prompt="", keep_alive=0)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if all(normalize_model_name(m.model or "") != wanted for m in client.ps().models):
                return
            time.sleep(0.5)
    except (ConnectionError, ollama.ResponseError):
        pass
