import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_VARS = [
    "RAPIDAPI_KEY",
    "GMAIL_USER",
    "GMAIL_APP_PASSWORD",
    "EMAIL_TO",
    "OLLAMA_HOST",
    "ANTHROPIC_API_KEY",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never depend on the developer's real environment or secrets."""
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def project_dir(tmp_path: Path) -> Path:
    """A throwaway project root with the real config.yaml and a small CV."""
    shutil.copy(REPO_ROOT / "config.yaml", tmp_path / "config.yaml")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "cv.md").write_text(
        "# Fulano\n\n## Resumo\nEngenheiro de IA.\n\n## Experiência\n- Algo\n",
        encoding="utf-8",
    )
    return tmp_path
