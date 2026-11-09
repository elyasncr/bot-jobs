"""Embedder protocol and factory. prerank.py only knows this interface, never the provider."""

from typing import Protocol

import numpy as np

from vagas_bot.config import ConfigError, Settings


class EmbedderUnavailable(Exception):
    """The embedding backend is down or the model is missing (message in Portuguese)."""


class Embedder(Protocol):
    name: str  # "ollama/bge-m3", "st/models/bge-m3-elyas-v1"

    def healthcheck(self) -> None: ...

    def embed_queries(self, texts: list[str]) -> np.ndarray: ...  # vagas

    def embed_passages(self, texts: list[str]) -> np.ndarray: ...  # blocos do CV

    def release(self) -> None: ...  # libera VRAM antes da etapa de LLM


def l2_normalize(vectors: np.ndarray) -> np.ndarray:
    """Row-wise L2 normalization so cosine similarity is a dot product."""
    vectors = np.asarray(vectors, dtype=np.float32)
    norms = np.linalg.norm(vectors, axis=-1, keepdims=True)
    return vectors / np.where(norms == 0, 1.0, norms)


def get_embedder(settings: Settings) -> Embedder:
    cfg = settings.config.embeddings
    if cfg.provider == "ollama":
        from vagas_bot.embeddings.ollama import OllamaEmbedder  # noqa: PLC0415

        return OllamaEmbedder(
            host=settings.ollama_host,
            model=cfg.ollama.model,
            timeout_s=settings.config.llm.ollama.request_timeout_s,
        )
    if cfg.provider == "sentence-transformers":
        raise ConfigError(
            "Provider de embeddings 'sentence-transformers' ainda não implementado (Fase 9). "
            "Use embeddings.provider: ollama."
        )
    raise ConfigError(f"Provider de embeddings desconhecido: {cfg.provider}")
