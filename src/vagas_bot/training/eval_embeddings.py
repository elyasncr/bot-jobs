"""eval-embeddings: compare embedders on the same validation data → finetune_report.md.

Metrics (SPEC 9.7): Spearman cosine × my gold score (main), Spearman cosine × LLM score
(silver validation), recall@top_n of the jobs I scored >= 70, plus agreement between
embedders on data/eval/jobs (acceptance: st/BAAI/bge-m3 ≈ ollama/bge-m3, Spearman > 0.95).
"""

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from vagas_bot.config import Settings
from vagas_bot.embeddings.base import Embedder, l2_normalize
from vagas_bot.evaluation import spearman
from vagas_bot.log import get_logger
from vagas_bot.scoring.prerank import cv_vector
from vagas_bot.training.dataset import DatasetSplit, Pair

log = get_logger("eval.embeddings")

GOOD_SCORE = 0.70  # "vaga boa": nota gold >= 70
SWITCH_MIN_GAIN = 0.05
TRAINING_META = "training_meta.json"


@dataclass
class EmbedderSpec:
    spec: str  # "ollama/bge-m3", "st/BAAI/bge-m3", "st/models/bge-m3-elyas-v1"
    representation: str  # blocks_mean | compact


@dataclass
class EmbedderResult:
    spec: str
    representation: str
    error: str | None = None
    spearman_gold: float | None = None
    n_gold: int = 0
    spearman_silver: float | None = None
    n_silver: int = 0
    recall_top_n: float | None = None
    recall_30: float | None = None
    n_good: int = 0
    pool: int = 0
    agreement: float | None = None  # Spearman vs. 1º embedder nas vagas de data/eval/jobs
    eval_job_cosines: list[float] | None = None


def resolve_spec(spec: str, settings: Settings) -> EmbedderSpec:
    """Fine-tuned models (folder with training_meta.json) use 'compact'; others the config."""
    if not spec.startswith(("ollama/", "st/")):
        raise ValueError(f"Embedder '{spec}' inválido: use ollama/<modelo> ou st/<modelo ou pasta>.")
    representation = settings.config.embeddings.cv_representation
    if spec.startswith("st/"):
        path = Path(spec[3:])
        folder = path if path.is_absolute() else settings.root / path
        if (folder / TRAINING_META).is_file():
            representation = json.loads((folder / TRAINING_META).read_text(encoding="utf-8")).get(
                "cv_representation", "compact"
            )
    return EmbedderSpec(spec, representation)


def build_embedder(spec: str, settings: Settings) -> Embedder:
    if spec.startswith("ollama/"):
        from vagas_bot.embeddings.ollama import OllamaEmbedder  # noqa: PLC0415

        return OllamaEmbedder(host=settings.ollama_host, model=spec[len("ollama/"):],
                              timeout_s=settings.config.llm.ollama.request_timeout_s)
    from vagas_bot.embeddings.st import STEmbedder  # noqa: PLC0415

    cfg = settings.config.embeddings.sentence_transformers.model_copy(update={"model": spec[len("st/"):]})
    return STEmbedder(cfg, root=settings.root)


def cosines(embedder: Embedder, cv_md: str, representation: str, texts: list[str]) -> np.ndarray:
    if not texts:
        return np.zeros(0, dtype=np.float32)
    cv = cv_vector(embedder, cv_md, representation)
    return l2_normalize(embedder.embed_queries(texts)) @ cv


def recall_at(ranked_ids: list[str], good: set[str], k: int) -> float | None:
    if not good:
        return None
    return len(set(ranked_ids[:k]) & good) / len(good)


def evaluate_embedder(
    embedder: Embedder,
    spec: EmbedderSpec,
    cv_md: str,
    split: DatasetSplit,
    eval_job_texts: list[str],
    top_n: int,
) -> EmbedderResult:
    result = EmbedderResult(spec.spec, spec.representation)
    try:
        embedder.healthcheck()
        pool = _unique(split.validation)
        pool_cos = cosines(embedder, cv_md, spec.representation, [p.job_text for p in pool])
        result.eval_job_cosines = cosines(embedder, cv_md, spec.representation, eval_job_texts).tolist()
    except Exception as exc:  # noqa: BLE001 — qualquer falha do provider vira linha de erro no relatório
        log.error("%s: %s", spec.spec, exc)
        result.error = str(exc)
        return result
    finally:
        embedder.release()

    cos_by_id = {p.job_id: float(c) for p, c in zip(pool, pool_cos, strict=True)}
    gold, silver = split.val_gold, split.val_silver
    result.n_gold, result.n_silver = len(gold), len(silver)
    result.spearman_gold = spearman([cos_by_id[p.job_id] for p in gold], [p.score for p in gold])
    result.spearman_silver = spearman([cos_by_id[p.job_id] for p in silver], [p.score for p in silver])

    ranked = sorted(cos_by_id, key=lambda jid: cos_by_id[jid], reverse=True)
    good = {p.job_id for p in gold if p.score >= GOOD_SCORE}
    result.pool, result.n_good = len(ranked), len(good)
    result.recall_top_n = recall_at(ranked, good, top_n)
    result.recall_30 = recall_at(ranked, good, max(1, math.ceil(0.3 * len(ranked))))
    return result


def _unique(pairs: list[Pair]) -> list[Pair]:
    seen: dict[str, Pair] = {}
    for pair in pairs:
        seen.setdefault(pair.job_id, pair)
    return list(seen.values())


def add_agreement(results: list[EmbedderResult]) -> None:
    ref = next((r for r in results if r.eval_job_cosines), None)
    for r in results:
        if ref is not None and r is not ref and r.eval_job_cosines:
            r.agreement = spearman(ref.eval_job_cosines, r.eval_job_cosines)


def recommendation(base: EmbedderResult, candidate: EmbedderResult) -> str:
    """Switch only if gold Spearman improves >= 0.05 AND recall@top_n does not get worse."""
    if candidate.error or base.error:
        return "Sem recomendação: um dos modelos falhou."
    if base.spearman_gold is None or candidate.spearman_gold is None:
        return "Sem recomendação: faltam notas gold na validação (use o comando label)."
    gain = candidate.spearman_gold - base.spearman_gold
    recall_ok = (candidate.recall_top_n or 0) >= (base.recall_top_n or 0)
    verdict = "**Trocar**" if gain >= SWITCH_MIN_GAIN and recall_ok else "**Manter o atual**"
    return (f"{verdict}: Spearman gold {base.spearman_gold:.2f} → {candidate.spearman_gold:.2f} "
            f"(ganho {gain:+.2f}, mínimo {SWITCH_MIN_GAIN}); recall@top_n "
            f"{_f(base.recall_top_n)} → {_f(candidate.recall_top_n)}.")


def _f(value: float | None, pattern: str = "{:.2f}") -> str:
    return pattern.format(value) if value is not None else "—"


def render_report(
    results: list[EmbedderResult], split: DatasetSplit, top_n: int, n_eval_jobs: int,
    training_meta: dict | None = None,
) -> str:
    stats = split.stats()
    ref = results[0].spec if results else "—"
    lines = [
        "# Embeddings: base × fine-tunado (eval-embeddings)",
        "",
        f"- Validação: {stats['val_gold']} pares gold, {stats['val_silver']} silver "
        f"(treino: {stats['train_pairs']} pares). top_n = {top_n}.",
        f"- Concordância medida em {n_eval_jobs} vagas de `data/eval/jobs/` (Spearman dos cossenos vs. {ref}).",
    ]
    if training_meta:
        p = training_meta.get("params", {})
        lines.append(
            f"- Treino: base {training_meta.get('base')}, {p.get('epochs')} épocas, lr {p.get('learning_rate')}, "
            f"batch {p.get('batch_size')}, {training_meta.get('duration_s')}s."
        )
    lines += [
        "",
        "| Embedder | CV | Spearman gold (n) | Spearman LLM (n) | Recall@top_n | Recall@30% | Concordância |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        if r.error:
            lines.append(f"| {r.spec} | {r.representation} | erro: {r.error[:80]} | | | | |")
            continue
        lines.append(
            f"| {r.spec} | {r.representation} | {_f(r.spearman_gold)} ({r.n_gold}) "
            f"| {_f(r.spearman_silver)} ({r.n_silver}) | {_f(r.recall_top_n)} | {_f(r.recall_30)} "
            f"| {'—' if r is results[0] else _f(r.agreement, '{:.3f}')} |"
        )
    lines += ["", "## Recomendação", ""]
    if len(results) >= 2:
        lines += [f"- {r.spec} vs. {results[0].spec}: {recommendation(results[0], r)}" for r in results[1:]]
    lines += [
        "- A troca é decisão sua: o `config.yaml` nunca é alterado automaticamente.",
        "",
        "## Cuidados",
        "",
        f"- *Recall@top_n* conta, entre as vagas que você avaliou com nota ≥ {int(GOOD_SCORE * 100)}, quantas "
        "ficariam no top_n do pré-rank. É a métrica que mais importa: o pré-rank não pode deixar vaga boa para trás. "
        "Quando o conjunto de validação é menor que o top_n, ela vale 1 por construção; veja o Recall@30%.",
        "- Treinar só com silver ensina o embedding a imitar o LLM, inclusive os erros dele; por isso as notas "
        "gold decidem.",
        "- Como o CV é quase sempre o mesmo, o modelo aprende uma \"direção de vaga boa para mim\". "
        "Retreine se o `cv.md` mudar muito.",
        "- Modelos fine-tunados usam `embeddings.cv_representation: compact` (o formato do treino).",
    ]
    problems = training_meta.get("warnings") if training_meta else None
    if problems:
        lines += ["", "## Avisos do treino", "", *[f"- {p}" for p in problems]]
    return "\n".join(lines) + "\n"
