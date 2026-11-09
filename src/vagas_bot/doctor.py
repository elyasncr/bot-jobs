"""Environment diagnostics: env vars, CV, Ollama, models, SMTP, optional torch/GPU."""

import importlib.util
import smtplib
import sys
from dataclasses import dataclass
from enum import Enum

from vagas_bot.config import Settings
from vagas_bot.cv import CVError, load_cv, section_titles
from vagas_bot.ollama_utils import (
    OllamaUnavailable,
    is_model_available,
    list_local_models,
    pull_hint,
)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


class Status(str, Enum):
    OK = "ok"
    WARN = "aviso"
    FAIL = "falha"
    SKIP = "pulado"


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    detail: str


def check_python() -> Check:
    version = ".".join(map(str, sys.version_info[:3]))
    ok = sys.version_info[:2] == (3, 12)
    return Check("Python", Status.OK if ok else Status.WARN, version)


def check_cv(settings: Settings) -> Check:
    try:
        cv_md = load_cv(settings.cv_path)
    except CVError as exc:
        return Check("Currículo", Status.FAIL, str(exc))
    titles = section_titles(cv_md)
    return Check("Currículo", Status.OK, f"{len(cv_md)} caracteres, {len(titles)} seções '##'")


def check_env(settings: Settings) -> list[Check]:
    cfg = settings.config
    required = {
        "RAPIDAPI_KEY": "JSearch",
        "GMAIL_USER": "email",
        "GMAIL_APP_PASSWORD": "email",
        "EMAIL_TO": "email",
    }
    if cfg.llm.provider == "anthropic":
        required["ANTHROPIC_API_KEY"] = "LLM anthropic"
    checks: list[Check] = []
    for name, purpose in required.items():
        present = getattr(settings.secrets, name.lower()) is not None
        status = Status.OK if present else Status.FAIL
        checks.append(Check(f"env {name}", status, f"{'definida' if present else 'ausente'} ({purpose})"))
    if settings.secrets.ollama_host:
        checks.append(Check("env OLLAMA_HOST", Status.OK, f"sobrescreve host: {settings.ollama_host}"))
    return checks


def check_ollama(settings: Settings) -> list[Check]:
    cfg = settings.config
    host = settings.ollama_host
    try:
        available = list_local_models(host)
    except OllamaUnavailable as exc:
        return [Check("Ollama", Status.FAIL, str(exc))]

    checks = [Check("Ollama", Status.OK, f"no ar em {host} ({len(available)} modelos locais)")]
    wanted: list[tuple[str, str]] = []
    if cfg.llm.provider == "ollama":
        wanted.append(("Modelo LLM", cfg.llm.ollama.model))
    if cfg.embeddings.provider == "ollama":
        wanted.append(("Modelo embeddings", cfg.embeddings.ollama.model))
    for label, model in wanted:
        if is_model_available(model, available):
            checks.append(Check(label, Status.OK, model))
        else:
            checks.append(Check(label, Status.FAIL, pull_hint(model)))
    return checks


def check_smtp(settings: Settings) -> Check:
    secrets = settings.secrets
    if not (secrets.gmail_user and secrets.gmail_app_password):
        return Check("SMTP Gmail", Status.SKIP, "GMAIL_USER/GMAIL_APP_PASSWORD ausentes")
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=15) as smtp:
            smtp.login(secrets.gmail_user, secrets.gmail_app_password.get_secret_value())
    except smtplib.SMTPAuthenticationError:
        return Check("SMTP Gmail", Status.FAIL, "login recusado (confira a senha de app)")
    except (OSError, smtplib.SMTPException) as exc:
        return Check("SMTP Gmail", Status.FAIL, f"erro de conexão: {type(exc).__name__}")
    return Check("SMTP Gmail", Status.OK, f"login ok em {SMTP_HOST}:{SMTP_PORT}")


def check_torch() -> Check:
    if importlib.util.find_spec("torch") is None:
        return Check("PyTorch (extra st)", Status.SKIP, "extra 'st' não instalado")
    import torch  # noqa: PLC0415 — optional dependency

    if not torch.cuda.is_available():
        return Check("PyTorch (extra st)", Status.WARN, f"torch {torch.__version__} sem CUDA")
    gpu = torch.cuda.get_device_name(0)
    return Check("PyTorch (extra st)", Status.OK, f"torch {torch.__version__}, GPU: {gpu}")


def run_checks(settings: Settings, *, smtp: bool = True) -> list[Check]:
    checks = [check_python(), check_cv(settings), *check_env(settings), *check_ollama(settings)]
    checks.append(check_smtp(settings) if smtp else Check("SMTP Gmail", Status.SKIP, "--no-smtp"))
    checks.append(check_torch())
    return checks
