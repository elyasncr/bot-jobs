"""Training pairs (CV, job, score 0-1) from history.jsonl (silver) + labels.yaml (gold).

Split by job with a fixed seed: the same job never appears in train and validation.
Gold goes 100% to validation, unless there are 150+ gold labels (then 50% may train).
Silver: 90% train, 10% validation.
"""

import json
import random
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from vagas_bot.models import Job
from vagas_bot.scoring.prerank import job_to_text

MIN_SILVER = 300
MIN_GOLD = 40
GOLD_TRAIN_THRESHOLD = 150
SILVER_VAL_RATIO = 0.10
DEFAULT_SEED = 42


class InsufficientData(Exception):
    """Below the minimum number of pairs to train (overridable with --force)."""


@dataclass(frozen=True)
class Pair:
    job_id: str
    job_text: str
    score: float  # 0–1
    gold: bool


@dataclass
class DatasetSplit:
    train: list[Pair] = field(default_factory=list)
    val_silver: list[Pair] = field(default_factory=list)
    val_gold: list[Pair] = field(default_factory=list)
    n_silver: int = 0
    n_gold: int = 0

    @property
    def validation(self) -> list[Pair]:
        return self.val_gold + self.val_silver

    def train_ids(self) -> set[str]:
        return {p.job_id for p in self.train}

    def val_ids(self) -> set[str]:
        return {p.job_id for p in self.validation}

    def stats(self) -> dict[str, int]:
        return {
            "silver": self.n_silver,
            "gold": self.n_gold,
            "train_pairs": len(self.train),
            "train_gold_pairs": sum(p.gold for p in self.train),
            "val_silver": len(self.val_silver),
            "val_gold": len(self.val_gold),
        }


def load_history(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def silver_pairs(history: Iterable[dict[str, Any]]) -> list[Pair]:
    """One pair per job (the most recent LLM score wins)."""
    latest: dict[str, Pair] = {}
    for record in history:
        if record.get("job_text") and record.get("total") is not None:
            latest[record["id"]] = Pair(record["id"], record["job_text"], record["total"] / 100, gold=False)
    return list(latest.values())


def gold_pairs(labels: dict[str, int], jobs: Iterable[Job], history: Iterable[dict[str, Any]]) -> list[Pair]:
    """Job text from the eval snapshot (same job_to_text as inference), else from history."""
    texts = {r["id"]: r["job_text"] for r in history if r.get("job_text")}
    texts |= {job.id: job_to_text(job) for job in jobs}
    return [Pair(jid, texts[jid], score / 100, gold=True) for jid, score in labels.items() if jid in texts]


def split_pairs(
    silver: list[Pair], gold: list[Pair], seed: int = DEFAULT_SEED, gold_weight: int = 3
) -> DatasetSplit:
    rng = random.Random(seed)
    gold_ids = sorted({p.job_id for p in gold})
    rng.shuffle(gold_ids)
    gold_train_ids = set(gold_ids[: len(gold_ids) // 2]) if len(gold_ids) >= GOLD_TRAIN_THRESHOLD else set()
    gold_val_ids = set(gold_ids) - gold_train_ids

    # Silver de uma vaga gold segue o lado da gold; o resto é sorteado 90/10.
    free_ids = sorted({p.job_id for p in silver} - set(gold_ids))
    rng.shuffle(free_ids)
    n_val = round(len(free_ids) * SILVER_VAL_RATIO)
    silver_val_ids = set(free_ids[:n_val]) | gold_val_ids

    split = DatasetSplit(n_silver=len(silver), n_gold=len(gold))
    for pair in silver:
        (split.val_silver if pair.job_id in silver_val_ids else split.train).append(pair)
    for pair in gold:
        if pair.job_id in gold_train_ids:
            split.train.extend([pair] * gold_weight)  # peso maior por duplicação controlada
        else:
            split.val_gold.append(pair)
    return split


def check_minimums(split: DatasetSplit, force: bool) -> list[str]:
    """Problems with the data volume. Raises unless force=True (then they are warnings)."""
    problems = []
    if split.n_silver < MIN_SILVER:
        problems.append(f"{split.n_silver} pares silver (mínimo {MIN_SILVER}; o histórico cresce a cada execução)")
    if split.n_gold < MIN_GOLD:
        problems.append(f"{split.n_gold} notas gold (mínimo {MIN_GOLD}; use o comando label)")
    if not split.train:
        raise InsufficientData("Nenhum par de treino (history.jsonl vazio?). Nem --force resolve.")
    if problems and not force:
        raise InsufficientData("Dados insuficientes: " + "; ".join(problems) + ". Use --force para treinar mesmo assim.")
    return problems
