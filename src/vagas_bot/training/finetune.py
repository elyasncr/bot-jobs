"""Fine-tuning of the embedding model (Phase 9): SentenceTransformerTrainer + CoSENTLoss.

Pairs are (CV compact text, job_to_text(job), score 0-1). Imports of torch / datasets /
sentence_transformers stay inside the functions (extra "st").
"""

import json
import shutil
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from vagas_bot.log import get_logger
from vagas_bot.training.dataset import DatasetSplit, Pair

log = get_logger("finetune")


@dataclass
class FinetuneParams:
    base: str = "BAAI/bge-m3"
    epochs: int = 2
    learning_rate: float = 2e-5
    batch_size: int = 8
    warmup_ratio: float = 0.1
    max_seq_length: int = 512
    bf16: bool = True
    gradient_checkpointing: bool = False
    gold_weight: int = 3
    seed: int = 42


def _dataset(cv_text: str, pairs: list[Pair]) -> Any:
    from datasets import Dataset  # noqa: PLC0415

    return Dataset.from_dict({
        "sentence1": [cv_text] * len(pairs),
        "sentence2": [p.job_text for p in pairs],
        "score": [p.score for p in pairs],
    })


def finetune(
    params: FinetuneParams, split: DatasetSplit, cv_text: str, out: Path, warnings: list[str] | None = None
) -> dict[str, Any]:
    """Train, save the model in `out` with training_meta.json; returns the meta."""
    import torch  # noqa: PLC0415
    from sentence_transformers import (  # noqa: PLC0415
        SentenceTransformer,
        SentenceTransformerTrainer,
        SentenceTransformerTrainingArguments,
        losses,
    )

    try:  # sentence-transformers >= 6 moveu os evaluators
        from sentence_transformers.sentence_transformer.evaluation import (  # noqa: PLC0415
            EmbeddingSimilarityEvaluator,
        )
    except ImportError:
        from sentence_transformers.evaluation import EmbeddingSimilarityEvaluator  # noqa: PLC0415

    device = "cuda" if torch.cuda.is_available() else "cpu"
    log.info("Fine-tuning de %s em %s: %d pares de treino, %d de validação.",
             params.base, device, len(split.train), len(split.validation))
    model = SentenceTransformer(params.base, device=device)
    model.max_seq_length = params.max_seq_length

    validation = split.validation
    evaluator = None
    if len(validation) >= 3:
        evaluator = EmbeddingSimilarityEvaluator(
            sentences1=[cv_text] * len(validation),
            sentences2=[p.job_text for p in validation],
            scores=[p.score for p in validation],
            name="validacao",
        )
    args = SentenceTransformerTrainingArguments(
        output_dir=str(out / "checkpoints"),
        num_train_epochs=params.epochs,
        per_device_train_batch_size=params.batch_size,
        learning_rate=params.learning_rate,
        warmup_steps=params.warmup_ratio,  # Transformers 5: float < 1 = fração dos passos (substitui warmup_ratio)
        bf16=params.bf16 and device == "cuda",
        gradient_checkpointing=params.gradient_checkpointing,
        seed=params.seed,
        eval_strategy="epoch" if evaluator else "no",
        save_strategy="no",
        logging_steps=10,
        report_to="none",
    )
    trainer = SentenceTransformerTrainer(
        model=model,
        args=args,
        train_dataset=_dataset(cv_text, split.train),
        loss=losses.CoSENTLoss(model),
        evaluator=evaluator,
    )
    started = datetime.now()
    result = trainer.train()
    metrics = dict(result.metrics)
    if evaluator is not None:
        metrics |= evaluator(model)

    out.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(str(out))
    shutil.rmtree(out / "checkpoints", ignore_errors=True)
    meta = {
        "base": params.base,
        "date": started.isoformat(timespec="seconds"),
        "duration_s": round((datetime.now() - started).total_seconds(), 1),
        "cv_representation": "compact",
        "params": asdict(params),
        "data": split.stats(),
        "metrics": {k: float(v) for k, v in metrics.items() if isinstance(v, (int, float))},
        "warnings": warnings or [],
    }
    (out / "training_meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    log.info("Modelo salvo em %s (%.0fs).", out, meta["duration_s"])
    del trainer, model
    if device == "cuda":
        torch.cuda.empty_cache()
    return meta
