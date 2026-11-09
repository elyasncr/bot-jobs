import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from helpers import FakeEmbedder, FakeScorer, make_job
from typer.testing import CliRunner

from vagas_bot import doctor, pipeline
from vagas_bot.__main__ import app
from vagas_bot.config import SearchConfig, load_settings
from vagas_bot.embeddings.base import EmbedderUnavailable
from vagas_bot.models import Job
from vagas_bot.notify.email import EmailError
from vagas_bot.ollama_utils import OllamaUnavailable

runner = CliRunner()


class FakeSource:
    name = "fake"

    def __init__(self, jobs: list[Job]) -> None:
        self.jobs = jobs
        self.fetches = 0

    def fetch(self, cfg: SearchConfig) -> list[Job]:
        self.fetches += 1
        return self.jobs


def _job(n: int) -> Job:
    return make_job(title=f"AI Engineer {n}", company=f"Empresa {n}")


@pytest.fixture
def sent_emails(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    for name, value in [("GMAIL_USER", "bot@gmail.com"), ("GMAIL_APP_PASSWORD", "app-pass"), ("EMAIL_TO", "eu@gmail.com")]:
        monkeypatch.setenv(name, value)
    sent: list[Any] = []
    monkeypatch.setattr(pipeline, "send_email", lambda msg, user, password: sent.append(msg))
    return sent


@pytest.fixture
def fake_sources(monkeypatch: pytest.MonkeyPatch, sent_emails: list[Any]) -> FakeSource:
    monkeypatch.setenv("RAPIDAPI_KEY", "test-key")
    source = FakeSource([_job(1), _job(2), _job(3)])
    monkeypatch.setattr(pipeline, "build_sources", lambda settings: [source])
    monkeypatch.setattr(pipeline, "get_embedder", lambda settings: FakeEmbedder())
    monkeypatch.setattr(pipeline, "get_scorer", lambda settings: FakeScorer())
    return source


def test_run_dry_run_writes_preview(project_dir: Path, fake_sources: FakeSource) -> None:
    result = runner.invoke(app, ["run", "--dry-run", "--config", str(project_dir / "config.yaml")])
    assert result.exit_code == 0, result.output
    preview = (project_dir / "preview.html").read_text(encoding="utf-8")
    assert "AI Engineer 1" in preview and "AI Engineer 3" in preview
    log_text = next((project_dir / "logs").glob("run_*.log")).read_text(encoding="utf-8")
    assert "AI Engineer 2" in log_text


def test_run_limit(project_dir: Path, fake_sources: FakeSource) -> None:
    result = runner.invoke(app, ["run", "--dry-run", "--limit", "1", "--config", str(project_dir / "config.yaml")])
    assert result.exit_code == 0, result.output
    preview = (project_dir / "preview.html").read_text(encoding="utf-8")
    assert "AI Engineer 1" in preview and "AI Engineer 2" not in preview


def test_run_without_dry_run_requires_gmail_env(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RAPIDAPI_KEY", "k")
    result = runner.invoke(app, ["run", "--config", str(project_dir / "config.yaml")])
    assert result.exit_code == 1


def test_test_email_command(project_dir: Path, sent_emails: list[Any]) -> None:
    result = runner.invoke(app, ["test-email", "--config", str(project_dir / "config.yaml")])
    assert result.exit_code == 0, result.output
    assert sent_emails[0]["Subject"].startswith("[TESTE] [Vagas PJ] 3 novas vagas")


def test_run_requires_rapidapi_key(project_dir: Path) -> None:
    result = runner.invoke(app, ["run", "--dry-run", "--config", str(project_dir / "config.yaml")])
    assert result.exit_code == 1
    assert not (project_dir / "preview.html").exists()


def test_two_runs_do_not_repeat_jobs(project_dir: Path, fake_sources: FakeSource) -> None:
    args = ["run", "--config", str(project_dir / "config.yaml")]
    first = runner.invoke(app, args)
    assert first.exit_code == 0, first.output
    seen = json.loads((project_dir / "data" / "seen.json").read_text(encoding="utf-8"))
    assert {"id-AI Engineer 1-Empresa 1", "id-AI Engineer 3-Empresa 3"} <= set(seen)

    fake_sources.jobs = [_job(1), _job(2), _job(4)]  # 1 e 2 já vistas, 4 é nova
    preview_args = ["run", "--dry-run", "--config", str(project_dir / "config.yaml")]
    second = runner.invoke(app, preview_args)
    assert second.exit_code == 0, second.output
    preview = (project_dir / "preview.html").read_text(encoding="utf-8")
    assert "AI Engineer 4" in preview
    assert "AI Engineer 1" not in preview and "AI Engineer 2" not in preview


def test_embedder_is_released_after_stage(
    project_dir: Path, fake_sources: FakeSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    embedder = FakeEmbedder()
    monkeypatch.setattr(pipeline, "get_embedder", lambda settings: embedder)
    result = runner.invoke(app, ["run", "--dry-run", "--config", str(project_dir / "config.yaml")])
    assert result.exit_code == 0, result.output
    assert embedder.healthchecks == 1 and embedder.released == 1


def test_embedder_down_aborts_without_state(
    project_dir: Path, fake_sources: FakeSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    class DownEmbedder(FakeEmbedder):
        def healthcheck(self) -> None:
            raise EmbedderUnavailable("Ollama não responde. Rode: ollama serve")

    monkeypatch.setattr(pipeline, "get_embedder", lambda settings: DownEmbedder())
    result = runner.invoke(app, ["run", "--config", str(project_dir / "config.yaml")])
    assert result.exit_code == 1
    assert not (project_dir / "data" / "seen.json").exists()


def test_full_run_writes_history_and_query_stats(
    project_dir: Path, fake_sources: FakeSource, sent_emails: list[Any]
) -> None:
    result = runner.invoke(app, ["run", "--config", str(project_dir / "config.yaml")])
    assert result.exit_code == 0, result.output
    assert len(sent_emails) == 1
    assert sent_emails[0]["Subject"].startswith("[Vagas PJ] 3 novas vagas")
    assert sent_emails[0]["To"] == "eu@gmail.com"
    history = [json.loads(line) for line in (project_dir / "data" / "history.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(history) == 3 and {h["total"] for h in history} == {78}
    assert all("Fulano" not in json.dumps(h) for h in history)  # nunca dados do CV


def test_llm_down_still_ranks_by_estimate(
    project_dir: Path, fake_sources: FakeSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline, "get_scorer", lambda settings: FakeScorer(down=True))
    result = runner.invoke(app, ["run", "--dry-run", "--config", str(project_dir / "config.yaml")])
    assert result.exit_code == 0, result.output
    preview = (project_dir / "preview.html").read_text(encoding="utf-8")
    assert "estimativa" in preview and "AI Engineer 1" in preview


def test_no_llm_never_calls_scorer(
    project_dir: Path, fake_sources: FakeSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(settings: object) -> None:
        raise AssertionError("scorer não deveria ser criado com --no-llm")

    monkeypatch.setattr(pipeline, "get_scorer", boom)
    result = runner.invoke(app, ["run", "--no-llm", "--config", str(project_dir / "config.yaml")])
    assert result.exit_code == 0, result.output
    assert not (project_dir / "data" / "history.jsonl").exists()


def test_second_run_same_day_is_skipped(
    project_dir: Path, fake_sources: FakeSource, sent_emails: list[Any]
) -> None:
    args = ["run", "--config", str(project_dir / "config.yaml")]
    assert runner.invoke(app, args).exit_code == 0
    assert (project_dir / "data" / ".last_run").read_text(encoding="utf-8") == date.today().isoformat()
    fake_sources.jobs = [_job(9)]
    second = runner.invoke(app, args)
    assert second.exit_code == 0
    assert fake_sources.fetches == 1 and len(sent_emails) == 1  # nem coletou, nem enviou

    forced = runner.invoke(app, [*args, "--force"])
    assert forced.exit_code == 0
    assert fake_sources.fetches == 2 and len(sent_emails) == 2


def test_dry_run_ignores_and_does_not_write_lock(project_dir: Path, fake_sources: FakeSource) -> None:
    (project_dir / "data" / ".last_run").write_text(date.today().isoformat(), encoding="utf-8")
    result = runner.invoke(app, ["run", "--dry-run", "--config", str(project_dir / "config.yaml")])
    assert result.exit_code == 0 and fake_sources.fetches == 1


def test_lock_from_yesterday_does_not_block(project_dir: Path, fake_sources: FakeSource) -> None:
    (project_dir / "data" / ".last_run").write_text((date.today() - timedelta(days=1)).isoformat(), encoding="utf-8")
    assert runner.invoke(app, ["run", "--config", str(project_dir / "config.yaml")]).exit_code == 0
    assert fake_sources.fetches == 1


def test_dry_run_does_not_write_state(project_dir: Path, fake_sources: FakeSource) -> None:
    result = runner.invoke(app, ["run", "--dry-run", "--config", str(project_dir / "config.yaml")])
    assert result.exit_code == 0, result.output
    assert not (project_dir / "data" / "seen.json").exists()


def test_failed_notification_does_not_write_state(
    project_dir: Path, fake_sources: FakeSource, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail(msg: Any, user: str, password: str) -> None:
        raise EmailError("Falha no envio SMTP: timeout")

    monkeypatch.setattr(pipeline, "send_email", fail)
    result = runner.invoke(app, ["run", "--config", str(project_dir / "config.yaml")])
    assert result.exit_code == 0, result.output
    assert not (project_dir / "data" / "seen.json").exists()
    assert not (project_dir / "data" / ".last_run").exists()  # falhou → pode rodar de novo hoje


def test_run_fails_clearly_without_cv(project_dir: Path, fake_sources: FakeSource) -> None:
    (project_dir / "data" / "cv.md").unlink()
    result = runner.invoke(app, ["run", "--dry-run", "--config", str(project_dir / "config.yaml")])
    assert result.exit_code == 1


def test_doctor_reports_ollama_down(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def down(host: str, timeout_s: float = 5.0) -> set[str]:
        raise OllamaUnavailable(f"Ollama não responde em {host}. Rode: ollama serve")

    monkeypatch.setattr(doctor, "list_local_models", down)
    result = runner.invoke(app, ["doctor", "--no-smtp", "--config", str(project_dir / "config.yaml")])
    assert result.exit_code == 1
    assert "Ollama" in result.output

    checks = doctor.run_checks(load_settings(project_dir / "config.yaml"), smtp=False)
    ollama_check = next(c for c in checks if c.name == "Ollama")
    assert ollama_check.status is doctor.Status.FAIL
    assert "ollama serve" in ollama_check.detail
    assert not any(c.name.startswith("Modelo") for c in checks)


def test_doctor_reports_missing_model(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "list_local_models", lambda host, timeout_s=5.0: {"bge-m3:latest"})
    checks = doctor.run_checks(load_settings(project_dir / "config.yaml"), smtp=False)
    by_name = {c.name: c for c in checks}
    assert by_name["Ollama"].status is doctor.Status.OK
    assert by_name["Modelo embeddings"].status is doctor.Status.OK
    assert by_name["Modelo LLM"].status is doctor.Status.FAIL
    assert "ollama pull qwen3.5:9b" in by_name["Modelo LLM"].detail
