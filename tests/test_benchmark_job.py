import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from vagas_bot.config import Settings, load_settings
from vagas_bot.dashboard.benchmark_job import BenchmarkJob
from vagas_bot.dashboard.data import DashboardError
from vagas_bot.eval_runner import AddResult, EvalRunnerError

Progress = Callable[[str, int, int], None]


@pytest.fixture
def settings(project_dir: Path) -> Settings:
    return load_settings(project_dir / "config.yaml")


def _add(_: Settings) -> AddResult:
    return AddResult(added=3, total=18, new_labels=3)


def test_runs_to_done_with_progress(settings: Settings) -> None:
    calls: list[list[str]] = []

    def fake_run(s: Settings, models: list[str], on_progress: Progress) -> Path:
        for model in models:
            on_progress(model, 1, 2)
            on_progress(model, 2, 2)
        calls.append(models)
        return Path("data/eval/results/eval_20261113_100000.json")

    job = BenchmarkJob(settings, add=_add, run=fake_run)
    assert job.status()["state"] == "idle"
    first = job.start(["a:1b", "b:2b"])
    assert first["state"] == "running" and first["model_count"] == 2 and first["started_at"]
    job.wait(5)

    status = job.status()
    assert status["state"] == "done" and status["result_file"] == "eval_20261113_100000.json"
    assert status["added"] == 3 and status["finished_at"] and status["error"] is None
    assert (status["current_model"], status["model_index"], status["done"], status["total"]) == ("b:2b", 2, 2, 2)
    assert calls == [["a:1b", "b:2b"]]


def test_second_start_conflicts_until_done(settings: Settings) -> None:
    release = threading.Event()

    def slow_run(s: Settings, models: list[str], on_progress: Progress) -> Path:
        release.wait(5)
        return Path("eval_20261113_100000.json")

    job = BenchmarkJob(settings, add=_add, run=slow_run)
    job.start(["a:1b"])
    with pytest.raises(DashboardError) as err:
        job.start(["a:1b"])
    assert err.value.status == 409
    release.set()
    job.wait(5)
    assert job.status()["state"] == "done"
    assert job.start(["a:1b"])["state"] == "running"  # depois de terminar, pode rodar de novo
    job.wait(5)


def test_failure_becomes_error_state(settings: Settings) -> None:
    def failing_run(s: Settings, models: list[str], on_progress: Progress) -> Path:
        raise EvalRunnerError("Nenhuma vaga em data/eval/jobs/.")

    job = BenchmarkJob(settings, add=_add, run=failing_run)
    job.start(["a:1b"])
    job.wait(5)
    status = job.status()
    assert status["state"] == "error" and status["error"] == "Nenhuma vaga em data/eval/jobs/."
    assert status["finished_at"]
