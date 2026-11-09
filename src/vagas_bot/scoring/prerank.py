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


def cv_to_text_compact(cv_md: str) -> str:
    """Header + summary + skills + job titles (the '### ' lines of the experience sections).

    The CV format used in fine-tuning (Phase 9); fine-tuned models must use it at inference.
    """
    sections = _split_sections(cv_md)
    head = [f"{t}\n{b}".strip() for t, b in sections if _block_index(t) == 0]
    roles = [
        line[4:].strip()
        for t, b in sections
        if _block_index(t) == 1
        for line in b.splitlines()
        if line.startswith("### ")
    ]
    parts = head + (["Cargos:\n" + "\n".join(roles)] if roles else [])
    return "\n\n".join(p for p in parts if p).strip()


def cv_vector(embedder: Embedder, cv_md: str, representation: str = "blocks_mean") -> np.ndarray:
    """blocks_mean: normalized mean of the 3 block embeddings; compact: one embedding."""
    if representation == "compact":
        return l2_normalize(embedder.embed_passages([cv_to_text_compact(cv_md)])[0])
    vectors = embedder.embed_passages(cv_blocks(cv_md))
    return l2_normalize(vectors.mean(axis=0))


def prerank(jobs: list[Job], embedder: Embedder, cv_md: str, representation: str = "blocks_mean") -> list[Job]:
    """Return all jobs with embedding_score set, sorted by it (desc)."""
    if not jobs:
        return []
    cv = cv_vector(embedder, cv_md, representation)
    job_vectors = embedder.embed_queries([job_to_text(j) for j in jobs])
    scores = job_vectors @ cv
    scored = [j.model_copy(update={"embedding_score": float(s)}) for j, s in zip(jobs, scores, strict=True)]
    return sorted(scored, key=lambda j: j.embedding_score or 0.0, reverse=True)
