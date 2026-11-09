from pathlib import Path
from typing import Any

import numpy as np
import pytest
from helpers import FakeEmbedder, make_job
from typer.testing import CliRunner

from vagas_bot.__main__ import app
from vagas_bot.config import load_settings
from vagas_bot.evaluation import ensure_label_entries, load_labels, save_eval_jobs
from vagas_bot.training import eval_embeddings as ee
from vagas_bot.training.dataset import (
    MIN_GOLD,
    MIN_SILVER,
    InsufficientData,
    Pair,
    check_minimums,
    gold_pairs,
    silver_pairs,
    split_pairs,
)
from vagas_bot.training.labeling import job_from_history, pick_candidates

runner = CliRunner()


def _history(n: int, total: int = 60) -> list[dict[str, Any]]:
    return [{"id": f"j{i}", "title": f"AI {i}", "company": "X", "job_text": f"AI {i}\nX\ndesc {i}",
             "total": total} for i in range(n)]


def test_silver_pairs_latest_record_wins() -> None:
    history = [*_history(2), {"id": "j0", "job_text": "novo", "total": 90}, {"id": "jx", "job_text": "", "total": 50}]
    pairs = {p.job_id: p for p in silver_pairs(history)}
    assert set(pairs) == {"j0", "j1"}  # sem job_text não entra
    assert pairs["j0"].score == pytest.approx(0.9) and pairs["j0"].job_text == "novo"


def test_gold_pairs_prefer_snapshot_text() -> None:
    job = make_job(title="ML Eng", company="ACME", description="Descrição completa")
    history = [{"id": job.id, "job_text": "texto antigo", "total": 50}, {"id": "h1", "job_text": "só histórico"}]
    pairs = {p.job_id: p for p in gold_pairs({job.id: 80, "h1": 30, "sem-texto": 10}, [job], history)}
    assert pairs[job.id].job_text.startswith("ML Eng\nACME\nDescrição") and pairs[job.id].gold
    assert pairs["h1"].score == pytest.approx(0.3)
    assert "sem-texto" not in pairs


def test_split_has_no_leakage_and_gold_goes_to_validation() -> None:
    silver = [Pair(f"s{i}", "t", 0.5, False) for i in range(100)] + [Pair("g1", "t", 0.4, False)]
    gold = [Pair(f"g{i}", "t", 0.8, True) for i in range(10)]
    split = split_pairs(silver, gold, seed=1)
    assert split.train_ids().isdisjoint(split.val_ids())
    assert len(split.val_gold) == 10 and not any(p.gold for p in split.train)
    assert any(p.job_id == "g1" for p in split.val_silver)  # silver de vaga gold segue a gold
    assert 8 <= len(split.val_silver) <= 12  # ~10% do silver livre (+1 da g1)
    assert split_pairs(silver, gold, seed=1).val_ids() == split.val_ids()  # determinístico


def test_split_with_many_gold_trains_on_half_with_weight() -> None:
    gold = [Pair(f"g{i}", "t", 0.8, True) for i in range(150)]
    split = split_pairs([], gold, gold_weight=3)
    assert len(split.val_gold) == 75 and len(split.train) == 75 * 3
    assert split.train_ids().isdisjoint(split.val_ids())


def test_check_minimums() -> None:
    small = split_pairs(silver_pairs(_history(20)), [])
    with pytest.raises(InsufficientData, match=str(MIN_SILVER)):
        check_minimums(small, force=False)
    warnings = check_minimums(small, force=True)
    assert len(warnings) == 2 and str(MIN_GOLD) in warnings[1]
    with pytest.raises(InsufficientData, match="Nenhum par"):
        check_minimums(split_pairs([], []), force=True)


# --- label ---


def test_pick_candidates_prioritizes_doubt_and_skips_labeled() -> None:
    history = [{"id": "a", "total": 90}, {"id": "b", "total": 50}, {"id": "c", "total": 60}, {"id": "d", "total": 20}]
    picked = [r["id"] for r in pick_candidates(history, {"c"}, n=3, seed=0)]
    assert picked[0] == "b" and "c" not in picked and len(picked) == 3


def test_job_from_history_splits_text() -> None:
    job = job_from_history({"id": "x", "title": "AI", "company": "ACME", "job_text": "AI\nACME\nDescrição\nlonga"})
    assert job.description == "Descrição\nlonga" and job.low_fidelity


def test_cli_label_saves_gold_and_snapshot(project_dir: Path) -> None:
    import json

    lines = [json.dumps(r) for r in _history(3)]
    (project_dir / "data" / "history.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    config = str(project_dir / "config.yaml")
    # 1ª vaga: nota 70 + comentário; 2ª: pula; 3ª: inválida
    result = runner.invoke(app, ["label", "--config", config], input="70\nboa stack\n\n150\n")
    assert result.exit_code == 0, result.output
    labels = load_labels(project_dir / "data" / "eval" / "labels.yaml")
    assert list(labels.values()) == [70]
    assert len(list((project_dir / "data" / "eval" / "jobs").glob("*.json"))) == 1


# --- eval-embeddings ---


def test_recall_at() -> None:
    assert ee.recall_at(["a", "b", "c"], {"a", "c"}, 2) == 0.5
    assert ee.recall_at(["a"], set(), 1) is None


def test_evaluate_embedder_metrics() -> None:
    gold = [Pair("g-llm", "LLM LLM rag", 0.9, True), Pair("g-rag", "rag", 0.6, True),
            Pair("g-pad", "padeiro", 0.1, True)]
    silver = [Pair("s1", "LLM", 0.8, False), Pair("s2", "padeiro padeiro", 0.2, False), Pair("s3", "rag LLM", 0.7, False)]
    split = split_pairs([], [])
    split.val_gold, split.val_silver = gold, silver
    embedder = FakeEmbedder()
    spec = ee.EmbedderSpec("fake/x", "blocks_mean")
    result = ee.evaluate_embedder(embedder, spec, "## Resumo\nLLM e rag", split, ["LLM", "padeiro"], top_n=2)
    assert result.error is None and embedder.released == 1
    assert result.spearman_gold == pytest.approx(1.0) and result.n_gold == 3
    assert result.recall_top_n == 1.0 and result.n_good == 1 and result.pool == 6
    assert result.eval_job_cosines is not None and len(result.eval_job_cosines) == 2


def test_recommendation_rule() -> None:
    base = ee.EmbedderResult("st/base", "blocks_mean", spearman_gold=0.40, recall_top_n=0.8)
    better = ee.EmbedderResult("st/ft", "compact", spearman_gold=0.50, recall_top_n=0.8)
    worse_recall = ee.EmbedderResult("st/ft", "compact", spearman_gold=0.60, recall_top_n=0.5)
    small_gain = ee.EmbedderResult("st/ft", "compact", spearman_gold=0.43, recall_top_n=0.9)
    assert ee.recommendation(base, better).startswith("**Trocar**")
    assert ee.recommendation(base, worse_recall).startswith("**Manter")
    assert ee.recommendation(base, small_gain).startswith("**Manter")


def test_resolve_spec_uses_compact_for_finetuned(project_dir: Path) -> None:
    settings = load_settings(project_dir / "config.yaml")
    folder = project_dir / "models" / "ft"
    folder.mkdir(parents=True)
    (folder / "training_meta.json").write_text('{"cv_representation": "compact"}', encoding="utf-8")
    assert ee.resolve_spec("st/models/ft", settings).representation == "compact"
    assert ee.resolve_spec("ollama/bge-m3", settings).representation == "blocks_mean"
    with pytest.raises(ValueError, match="inválido"):
        ee.resolve_spec("bge-m3", settings)


def test_cli_eval_embeddings_report(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import json

    settings = load_settings(project_dir / "config.yaml")
    history = _history(30)
    for i, record in enumerate(history):
        record["total"] = 30 + i * 2
        record["job_text"] = "LLM " * (i % 5) + "padeiro " * (5 - i % 5)
    settings.history_path.write_text("\n".join(json.dumps(r) for r in history) + "\n", encoding="utf-8")
    jobs = [make_job(title=f"AI {i}", description="LLM " * i + "padeiro") for i in range(3)]
    save_eval_jobs(jobs, settings.eval_dir / "jobs")
    ensure_label_entries(settings.eval_dir / "labels.yaml", jobs)
    monkeypatch.setattr(ee, "build_embedder", lambda spec, s: FakeEmbedder())

    result = runner.invoke(app, ["eval-embeddings", "ollama/bge-m3", "st/BAAI/bge-m3", "--config",
                                 str(project_dir / "config.yaml")])
    assert result.exit_code == 0, result.output
    report = (project_dir / "finetune_report.md").read_text(encoding="utf-8")
    assert "| ollama/bge-m3 |" in report and "| st/BAAI/bge-m3 |" in report
    assert "1.000" in report  # mesmo embedder fake → concordância total
    assert np.isfinite(len(report))


def test_cli_finetune_refuses_without_data(project_dir: Path) -> None:
    result = runner.invoke(app, ["finetune-embeddings", "--config", str(project_dir / "config.yaml")])
    assert result.exit_code == 1
    assert "Nenhum par" in result.output
