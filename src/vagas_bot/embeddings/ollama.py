"""Default embedding provider: Ollama (`ollama.embed`), e.g. bge-m3. No prefixes apply."""

import numpy as np
import ollama

from vagas_bot.embeddings.base import EmbedderUnavailable, l2_normalize
from vagas_bot.log import get_logger
from vagas_bot.ollama_utils import (
    OllamaUnavailable,
    is_model_available,
    list_local_models,
    pull_hint,
)

log = get_logger("embeddings.ollama")

BATCH_SIZE = 16
KEEP_ALIVE_DURING_STAGE = "5m"


class OllamaEmbedder:
    def __init__(self, host: str, model: str, timeout_s: float = 180.0) -> None:
        self.host = host
        self.model = model
        self.name = f"ollama/{model}"
        self._client = ollama.Client(host=host, timeout=timeout_s)

    def healthcheck(self) -> None:
        try:
            available = list_local_models(self.host)
        except OllamaUnavailable as exc:
            raise EmbedderUnavailable(str(exc)) from exc
        if not is_model_available(self.model, available):
            raise EmbedderUnavailable(pull_hint(self.model))

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts)

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return self._embed(texts)

    def release(self) -> None:
        """Unload the model from VRAM (empty request with keep_alive=0)."""
        try:
            self._client.embed(model=self.model, input=[], keep_alive=0)
            log.info("Modelo de embeddings %s descarregado da VRAM.", self.model)
        except (ConnectionError, ollama.ResponseError) as exc:
            log.warning("Não consegui descarregar %s: %s", self.model, exc)

    def _embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        chunks: list[list[list[float]]] = []
        for start in range(0, len(texts), BATCH_SIZE):
            batch = texts[start : start + BATCH_SIZE]
            try:
                response = self._client.embed(
                    model=self.model, input=batch, keep_alive=KEEP_ALIVE_DURING_STAGE
                )
            except ConnectionError as exc:
                raise EmbedderUnavailable(f"Ollama caiu durante os embeddings: {exc}") from exc
            except ollama.ResponseError as exc:
                raise EmbedderUnavailable(f"Erro do Ollama nos embeddings: {exc}") from exc
            chunks.append([list(vector) for vector in response.embeddings])
        return l2_normalize(np.array([v for chunk in chunks for v in chunk], dtype=np.float32))
