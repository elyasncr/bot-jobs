import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
from helpers import FakeEmbedder, make_job

from vagas_bot.config import ConfigError, load_settings
from vagas_bot.embeddings import ollama as ollama_embed
from vagas_bot.embeddings.base import EmbedderUnavailable, get_embedder, l2_normalize
from vagas_bot.embeddings.ollama import OllamaEmbedder
from vagas_bot.embeddings.st import STEmbedder, resolve_model_path
from vagas_bot.scoring.prerank import cv_blocks, cv_to_text_compact, cv_vector, job_to_text, prerank

REAL_CV = Path(__file__).resolve().parent.parent / "data" / "cv.md"
CV = """# Fulano
**Cargo-alvo:** AI Engineer

## Resumo profissional
Engenheiro de IA com LLM e RAG.

## Competências
- LLM, RAG

## Experiência profissional
### Empresa X
- RAG em produção

## Formação
- MBA em IA

## Portfólio
- Projeto LLM
"""


# --- factory --------------------------------------------------------------------------


def test_factory_picks_ollama(project_dir: Path) -> None:
    embedder = get_embedder(load_settings(project_dir / "config.yaml"))
    assert isinstance(embedder, OllamaEmbedder)
    assert embedder.name == "ollama/bge-m3"
    assert embedder.host == "http://localhost:11434"


def test_factory_picks_st_and_resolves_local_model(project_dir: Path) -> None:
    settings = load_settings(project_dir / "config.yaml")
    settings.config.embeddings.provider = "sentence-transformers"
    embedder = get_embedder(settings)
    assert isinstance(embedder, STEmbedder)
    assert embedder.name == "st/BAAI/bge-m3" and embedder.model_path == "BAAI/bge-m3"  # nome do HF

    (project_dir / "models" / "meu-modelo").mkdir(parents=True)
    assert resolve_model_path("models/meu-modelo", project_dir) == str(project_dir / "models" / "meu-modelo")


def test_factory_unknown_provider(project_dir: Path) -> None:
    settings = load_settings(project_dir / "config.yaml")
    object.__setattr__(settings.config.embeddings, "provider", "outro")
    with pytest.raises(ConfigError, match="desconhecido"):
        get_embedder(settings)


def test_st_and_torch_not_imported_by_default() -> None:
    """Building the st embedder must not import torch: only healthcheck/encode do."""
    code = (
        "import sys, vagas_bot.pipeline, vagas_bot.embeddings.base, vagas_bot.scoring.prerank;"
        "from vagas_bot.embeddings.st import STEmbedder;"
        "from vagas_bot.config import SentenceTransformersConfig;"
        "from pathlib import Path; STEmbedder(SentenceTransformersConfig(), Path('.'));"
        "print('torch' in sys.modules, 'sentence_transformers' in sys.modules)"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False False"


class _FakeSTModel:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def encode(self, texts: list[str], **kwargs: Any) -> np.ndarray:
        self.calls.append(texts)
        assert kwargs["normalize_embeddings"] is True
        return np.array([[float(len(t)), 1.0] for t in texts])


def test_st_embedder_applies_prefixes_and_releases() -> None:
    from vagas_bot.config import SentenceTransformersConfig

    embedder = STEmbedder(SentenceTransformersConfig(query_prefix="query: ", passage_prefix="passage: "), Path("."))
    fake = _FakeSTModel()
    embedder._model = fake
    vectors = embedder.embed_queries(["vaga"])
    embedder.embed_passages(["cv"])
    assert fake.calls == [["query: vaga"], ["passage: cv"]]
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0)
    embedder.release()
    assert embedder._model is None


def test_cv_compact_has_head_and_roles() -> None:
    text = cv_to_text_compact(CV)
    assert "Cargo-alvo" in text and "Engenheiro de IA" in text and "LLM, RAG" in text
    assert "Cargos:\nEmpresa X" in text
    assert "RAG em produção" not in text and "MBA" not in text  # sem bullets de experiência e sem formação


def test_cv_vector_compact_is_single_normalized_embedding() -> None:
    embedder = FakeEmbedder()
    vec = cv_vector(embedder, CV, "compact")
    assert vec.shape == (4,) and np.isclose(np.linalg.norm(vec), 1.0)


# --- CV / job text --------------------------------------------------------------------


def test_cv_blocks_groups_sections() -> None:
    blocks = cv_blocks(CV)
    assert len(blocks) == 3
    assert "Cargo-alvo" in blocks[0] and "Resumo profissional" in blocks[0] and "Competências" in blocks[0]
    assert "Experiência profissional" in blocks[1] and "Empresa X" in blocks[1]
    assert "Formação" in blocks[2] and "Portfólio" in blocks[2]


@pytest.mark.parametrize("path", [REAL_CV, REAL_CV.with_name("cv.example.md")], ids=["cv", "example"])
def test_cv_blocks_real_cv(path: Path) -> None:
    if not path.is_file():
        pytest.skip(f"{path.name} não existe (data/cv.md não é versionado)")
    blocks = cv_blocks(path.read_text(encoding="utf-8"))
    assert len(blocks) == 3
    assert "Competências" in blocks[0]
    assert "Experiência profissional" in blocks[1]
    assert "Certificações" in blocks[2] and "Portfólio" in blocks[2]


def test_job_to_text_truncates() -> None:
    job = make_job(title="AI Engineer", company="ACME", description="x" * 5000)
    text = job_to_text(job)
    assert text.startswith("AI Engineer\nACME\nxxx")
    assert len(text) == 2000


def test_l2_normalize() -> None:
    v = l2_normalize(np.array([[3.0, 4.0], [0.0, 0.0]]))
    assert np.allclose(v[0], [0.6, 0.8]) and np.allclose(v[1], [0.0, 0.0])


# --- prerank --------------------------------------------------------------------------


def test_cv_vector_is_normalized() -> None:
    assert np.isclose(np.linalg.norm(cv_vector(FakeEmbedder(), CV)), 1.0)


def test_prerank_orders_by_similarity() -> None:
    jobs = [
        make_job(title="Padeiro", description="padeiro padeiro"),
        make_job(title="AI Engineer", description="LLM e RAG"),
        make_job(title="Data Analyst", description="LLM"),
    ]
    embedder = FakeEmbedder()
    ranked = prerank(jobs, embedder, CV)
    assert [j.title for j in ranked] == ["AI Engineer", "Data Analyst", "Padeiro"]
    assert all(j.embedding_score is not None for j in ranked)
    assert ranked[0].embedding_score > ranked[1].embedding_score > ranked[2].embedding_score  # type: ignore[operator]
    assert len(embedder.query_calls) == 1  # vagas embeddadas em um único lote


def test_prerank_empty() -> None:
    assert prerank([], FakeEmbedder(), CV) == []


# --- Ollama provider (mocked client) ---------------------------------------------------


class _FakeOllamaClient:
    def __init__(self, **_: Any) -> None:
        self.calls: list[dict[str, Any]] = []

    def embed(self, model: str, input: list[str], keep_alive: Any = None) -> SimpleNamespace:  # noqa: A002
        self.calls.append({"model": model, "input": input, "keep_alive": keep_alive})
        return SimpleNamespace(embeddings=[[3.0, 4.0] for _ in input])


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> _FakeOllamaClient:
    client = _FakeOllamaClient()
    monkeypatch.setattr(ollama_embed.ollama, "Client", lambda **kw: client)
    return client


def test_ollama_embedder_batches_and_normalizes(fake_client: _FakeOllamaClient) -> None:
    embedder = OllamaEmbedder("http://x", "bge-m3")
    vectors = embedder.embed_queries([f"t{i}" for i in range(20)])
    assert vectors.shape == (20, 2)
    assert np.allclose(vectors[0], [0.6, 0.8])
    assert [len(c["input"]) for c in fake_client.calls] == [16, 4]
    assert all(c["model"] == "bge-m3" for c in fake_client.calls)


def test_ollama_release_unloads_with_keep_alive_zero(fake_client: _FakeOllamaClient) -> None:
    OllamaEmbedder("http://x", "bge-m3").release()
    assert fake_client.calls == [{"model": "bge-m3", "input": [], "keep_alive": 0}]


def test_ollama_healthcheck_missing_model(monkeypatch: pytest.MonkeyPatch, fake_client: _FakeOllamaClient) -> None:
    monkeypatch.setattr(ollama_embed, "list_local_models", lambda host: {"qwen3.5:9b"})
    with pytest.raises(EmbedderUnavailable, match="ollama pull bge-m3"):
        OllamaEmbedder("http://x", "bge-m3").healthcheck()


def test_ollama_embed_connection_error(monkeypatch: pytest.MonkeyPatch, fake_client: _FakeOllamaClient) -> None:
    def boom(**_: Any) -> None:
        raise ConnectionError("down")

    monkeypatch.setattr(fake_client, "embed", boom)
    with pytest.raises(EmbedderUnavailable):
        OllamaEmbedder("http://x", "bge-m3").embed_queries(["a"])


@pytest.mark.integration
def test_ollama_real_embeddings() -> None:
    embedder = OllamaEmbedder("http://localhost:11434", "bge-m3")
    embedder.healthcheck()
    jobs = [make_job(title="Padeiro", description="Pães artesanais"), make_job(title="AI Engineer", description="LLMs, RAG, LangChain")]
    ranked = prerank(jobs, embedder, REAL_CV.read_text(encoding="utf-8"))
    embedder.release()
    assert ranked[0].title == "AI Engineer"
