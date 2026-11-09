"""Shared helpers to talk to the local Ollama server (health and model availability)."""

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
