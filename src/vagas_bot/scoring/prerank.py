"""Embedding pre-rank: cosine similarity CV × job, used to pick the top_n jobs for the LLM.

Provider-agnostic: only the Embedder protocol is used here.
"""

import numpy as np

from vagas_bot.embeddings.base import Embedder, l2_normalize
from vagas_bot.models import Job
from vagas_bot.text import normalize_text

JOB_TEXT_MAX_CHARS = 2000

# Section title fragments (normalized) → CV block index.
_BLOCK_KEYWORDS: list[tuple[int, tuple[str, ...]]] = [
    (0, ("resumo", "summary", "sobre", "about", "perfil", "competencia", "skill", "habilidade")),
    (1, ("experiencia", "experience", "historico profissional")),
    (2, ("formacao", "education", "portfolio", "projeto", "project", "certifica", "curso")),
]


def job_to_text(job: Job, max_chars: int = JOB_TEXT_MAX_CHARS) -> str:
    """Single job → text function, reused by training (Phase 9) and history."""
    text = f"{job.title}\n{job.company}\n{job.description}".strip()
    return text[:max_chars]


def _split_sections(cv_md: str) -> list[tuple[str, str]]:
    """[(title, body)]; text before the first '## ' gets the title ''."""
    sections: list[tuple[str, str]] = []
    title, lines = "", []
    for line in cv_md.splitlines():
        if line.startswith("## "):
            sections.append((title, "\n".join(lines).strip()))
            title, lines = line[3:].strip(), []
        else:
            lines.append(line)
    sections.append((title, "\n".join(lines).strip()))
    return [(t, b) for t, b in sections if b or t]


def _block_index(title: str) -> int:
    if not title:
        return 0  # cabeçalho: cargo-alvo, senioridade, modalidade
    norm = normalize_text(title)
    for index, keywords in _BLOCK_KEYWORDS:
        if any(k in norm for k in keywords):
            return index
    return 2


def cv_blocks(cv_md: str) -> list[str]:
    """3 blocks: header + summary + skills; experience; education + certifications + portfolio."""
    blocks: list[list[str]] = [[], [], []]
    for title, body in _split_sections(cv_md):
        blocks[_block_index(title)].append(f"{title}\n{body}".strip())
    return [joined for parts in blocks if (joined := "\n\n".join(parts).strip())]


def cv_vector(embedder: Embedder, cv_md: str) -> np.ndarray:
    """Normalized mean of the block embeddings (cv_representation = blocks_mean)."""
    vectors = embedder.embed_passages(cv_blocks(cv_md))
    return l2_normalize(vectors.mean(axis=0))


def prerank(jobs: list[Job], embedder: Embedder, cv_md: str) -> list[Job]:
    """Return all jobs with embedding_score set, sorted by it (desc)."""
    if not jobs:
        return []
    cv = cv_vector(embedder, cv_md)
    job_vectors = embedder.embed_queries([job_to_text(j) for j in jobs])
    scores = job_vectors @ cv
    scored = [j.model_copy(update={"embedding_score": float(s)}) for j, s in zip(jobs, scores, strict=True)]
    return sorted(scored, key=lambda j: j.embedding_score or 0.0, reverse=True)
