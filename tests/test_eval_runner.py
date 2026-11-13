from datetime import date
from pathlib import Path

import pytest
from helpers import ScriptedScorer, llm_output, make_job
from typer.testing import CliRunner

from vagas_bot import eval_runner, evaluation
from vagas_bot.__main__ import app
from vagas_bot.archive import append_archive, archive_records
from vagas_bot.config import FiltersConfig, Settings, load_settings
from vagas_bot.eval_runner import AddResult, EvalRunnerError
from vagas_bot.models import Job
from vagas_bot.scoring.llm_stage import to_score_result

CFG = FiltersConfig(modalities=["remote"], exclude_title_keywords=["junior"])
runner = CliRunner()


@pytest.fixture
def settings(project_dir: Path) -> Settings:
    return load_settings(project_dir / "config.yaml")


def _scored(job: Job, technical: int = 80) -> Job:
    return job.model_copy(update={"score": to_score_result(llm_output(technical=technical), "ollama/x", 2.0)})


def _archive(settings: Settings, after_dedupe: list[Job], processed: list[Job], emailed: set[str]) -> None:
    records = archive_records(after_dedupe, processed, emailed, CFG, date(2026, 11, 12))
    append_archive(settings.jobs_archive_path, records)


def _fake_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(evaluation, "ollama_scorer_for", lambda s, m: ScriptedScorer(f"ollama/{m}", [70] * 10))
    monkeypatch.setattr(evaluation, "loaded_vram_gb", lambda host, model: 5.5)
    monkeypatch.setattr(evaluation, "gpu_memory_used_gb", lambda: None)
    monkeypatch.setattr(evaluation, "unload_model", lambda host, model: None)


def test_add_archive_jobs_adds_only_new_evaluated(settings: Settings) -> None:
    old, new, junior = make_job(title="AI Old"), make_job(title="AI New"), make_job(title="AI Junior")
    _archive(settings, [old, new, junior], [_scored(old), _scored(new)], {old.id})  # junior: filtrada
    evaluation.save_eval_jobs([old], settings.eval_dir / "jobs")

    assert eval_runner.pending_archive_jobs(settings) == 1
    assert eval_runner.add_archive_jobs(settings) == AddResult(added=1, total=2, new_labels=2)
    assert eval_runner.pending_archive_jobs(settings) == 0
    assert {j.title for j in evaluation.load_eval_jobs(settings.eval_dir / "jobs")} == {"AI Old", "AI New"}


def test_add_archive_jobs_respects_n(settings: Settings) -> None:
    jobs = [make_job(title=f"AI {i}") for i in range(3)]
    _archive(settings, jobs, [_scored(j, 20 * i) for i, j in enumerate(jobs)], set())
    assert eval_runner.add_archive_jobs(settings, n=2).added == 2
    assert eval_runner.pending_archive_jobs(settings) == 1


def test_add_archive_jobs_without_archive(settings: Settings) -> None:
    assert eval_runner.pending_archive_jobs(settings) == 0
    assert eval_runner.add_archive_jobs(settings) == AddResult(added=0, total=0, new_labels=0)


def test_run_benchmark_saves_results_and_report(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_ollama(monkeypatch)
    evaluation.save_eval_jobs([make_job(title=f"AI {i}") for i in range(2)], settings.eval_dir / "jobs")
    seen: list[tuple[str, int, int]] = []

    path = eval_runner.run_benchmark(settings, ["m1:7b"], runs=1,
                                     on_progress=lambda m, d, t: seen.append((m, d, t)))

    assert path.is_file() and path.parent == settings.eval_dir / "results"
    assert evaluation.load_results(path)[2]["models"] == ["m1:7b"]
    assert "ollama/m1:7b" in (settings.root / "eval_report.md").read_text(encoding="utf-8")
    assert seen[-1] == ("m1:7b", 2, 2)


def test_run_benchmark_without_jobs(settings: Settings) -> None:
    with pytest.raises(EvalRunnerError, match="eval-snapshot"):
        eval_runner.run_benchmark(settings, ["m1:7b"])


def test_run_benchmark_without_cv(settings: Settings) -> None:
    evaluation.save_eval_jobs([make_job()], settings.eval_dir / "jobs")
    settings.cv_path.unlink()
    with pytest.raises(EvalRunnerError, match="cv.md"):
        eval_runner.run_benchmark(settings, ["m1:7b"])


def test_cli_eval_snapshot_from_archive(settings: Settings) -> None:
    job = make_job(title="AI A")
    _archive(settings, [job], [_scored(job)], set())
    result = runner.invoke(app, ["eval-snapshot", "--from-archive", "--config", str(settings.root / "config.yaml")])
    assert result.exit_code == 0, result.output
    assert "1 vagas novas salvas; 1 no total" in result.output
