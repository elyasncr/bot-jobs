"""Optional embeddings provider: sentence-transformers (extra "st").

torch / sentence_transformers are imported only inside this module's methods, so the
project works without the extra installed. Accepts a Hugging Face name or a local folder
(e.g. a fine-tuned model in models/).
"""

import gc
from pathlib import Path
from typing import Any

import numpy as np

from vagas_bot.config import SentenceTransformersConfig
from vagas_bot.embeddings.base import EmbedderUnavailable, l2_normalize
from vagas_bot.log import get_logger

log = get_logger("embeddings.st")


def resolve_model_path(model: str, root: Path) -> str:
    """'models/x' relative to the project root when that folder exists; else the HF name."""
    local = Path(model) if Path(model).is_absolute() else root / model
    return str(local) if local.is_dir() else model


class STEmbedder:
    def __init__(self, cfg: SentenceTransformersConfig, root: Path) -> None:
        self.cfg = cfg
        self.model_path = resolve_model_path(cfg.model, root)
        self.name = f"st/{cfg.model}"
        self._model: Any = None

    def healthcheck(self) -> None:
        try:
            import sentence_transformers  # noqa: F401, PLC0415
            import torch  # noqa: PLC0415
        except ImportError as exc:
            raise EmbedderUnavailable(
                "Provider 'sentence-transformers' precisa do extra 'st'. Rode: uv sync --extra st"
            ) from exc
        if self.cfg.device == "cuda" and not torch.cuda.is_available():
            raise EmbedderUnavailable(
                f"torch {torch.__version__} sem CUDA. Instale a variante CUDA (veja pyproject.toml) "
                "ou use embeddings.sentence_transformers.device: cpu."
            )
        self._load()

    def _load(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # noqa: PLC0415

            log.info("Carregando %s em %s...", self.model_path, self.cfg.device)
            try:
                self._model = SentenceTransformer(self.model_path, device=self.cfg.device)
            except (OSError, ValueError) as exc:
                raise EmbedderUnavailable(f"Não foi possível carregar {self.model_path}: {exc}") from exc
        return self._model

    def _encode(self, texts: list[str], prefix: str) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        vectors = self._load().encode(
            [prefix + t for t in texts],
            batch_size=self.cfg.batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        return l2_normalize(vectors)

    def embed_queries(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts, self.cfg.query_prefix)

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return self._encode(texts, self.cfg.passage_prefix)

    def release(self) -> None:
        if self._model is None:
            return
        self._model = None
        gc.collect()
        try:
            import torch  # noqa: PLC0415

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except ImportError:
            pass
