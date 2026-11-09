from pathlib import Path

import pytest
from pydantic import ValidationError

from vagas_bot.config import (
    ConfigError,
    load_app_config,
    load_settings,
    missing_env,
    required_env,
)

REPO_CONFIG = Path(__file__).resolve().parent.parent / "config.yaml"


def test_repo_config_is_valid() -> None:
    cfg = load_app_config(REPO_CONFIG)
    assert cfg.llm.provider == "ollama"
    assert cfg.llm.ollama.num_ctx == 16384
    assert cfg.embeddings.ollama.model == "bge-m3"
    assert cfg.search.publishers == []
    assert cfg.search.remote_only is True
    assert cfg.filters.modalities == ["remote"]


def test_unknown_key_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("search:\n  queries: ['x']\n  typo_key: 1\n", encoding="utf-8")
    with pytest.raises(ValidationError):
        load_app_config(path)


def test_missing_config_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError):
        load_app_config(tmp_path / "nope.yaml")


def test_env_file_blank_values_are_none(project_dir: Path) -> None:
    (project_dir / ".env").write_text("RAPIDAPI_KEY=\nGMAIL_USER=eu@gmail.com\n", encoding="utf-8")
    settings = load_settings(project_dir / "config.yaml")
    assert settings.secrets.rapidapi_key is None
    assert settings.secrets.gmail_user == "eu@gmail.com"


def test_ollama_host_env_overrides_config(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings(project_dir / "config.yaml")
    assert settings.ollama_host == "http://localhost:11434"
    monkeypatch.setenv("OLLAMA_HOST", "http://gpu-box:11434")
    settings = load_settings(project_dir / "config.yaml")
    assert settings.ollama_host == "http://gpu-box:11434"


def test_paths_are_relative_to_config(project_dir: Path) -> None:
    settings = load_settings(project_dir / "config.yaml")
    assert settings.cv_path == project_dir.resolve() / "data" / "cv.md"
    assert settings.logs_dir == project_dir.resolve() / "logs"


def test_anthropic_key_only_required_for_anthropic_provider() -> None:
    cfg = load_app_config(REPO_CONFIG)
    assert "ANTHROPIC_API_KEY" not in required_env(cfg, collect=True, send_email=True, use_llm=True)
    cfg.llm.provider = "anthropic"
    assert "ANTHROPIC_API_KEY" in required_env(cfg, collect=False, send_email=False, use_llm=True)
    assert "ANTHROPIC_API_KEY" not in required_env(cfg, collect=False, send_email=False, use_llm=False)


def test_missing_env_reports_names(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GMAIL_USER", "eu@gmail.com")
    settings = load_settings(project_dir / "config.yaml")
    names = required_env(settings.config, collect=True, send_email=True, use_llm=True)
    assert missing_env(settings, names) == ["RAPIDAPI_KEY", "GMAIL_APP_PASSWORD", "EMAIL_TO"]
