"""Loading of the CV (data/cv.md), the single source of the candidate profile."""

from pathlib import Path


class CVError(Exception):
    """CV missing or empty."""


def load_cv(path: Path) -> str:
    if not path.is_file():
        raise CVError(f"Currículo não encontrado em {path}. Crie o arquivo data/cv.md.")
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise CVError(f"Currículo vazio: {path}")
    return text


def section_titles(cv_md: str) -> list[str]:
    """Titles of the '## ' sections, used for sanity checks (never log the CV content)."""
    return [line[3:].strip() for line in cv_md.splitlines() if line.startswith("## ")]
