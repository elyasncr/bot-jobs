from datetime import date
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import pytest

from vagas_bot import pipeline
from vagas_bot.config import LinkedInAlertsConfig, SearchConfig, load_settings, required_env
from vagas_bot.filters import Modality, detect_modality
from vagas_bot.sources import linkedin_alerts as la
from vagas_bot.sources.linkedin_alerts import (
    LinkedInAlertsSource,
    imap_since,
    jobs_from_message,
    parse_alert_text,
)

FIXTURE = (Path(__file__).parent / "fixtures" / "linkedin_alert.txt").read_text(encoding="utf-8")
SEARCH = SearchConfig(queries=["x"])


def _message(text: str = FIXTURE, html_only: bool = False) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = "LinkedIn <jobalerts-noreply@linkedin.com>"
    msg["Subject"] = "Engenheiro de IA na empresa Alfa"
    msg["Date"] = "Mon, 09 Nov 2026 08:00:00 -0300"
    if html_only:
        msg.set_content("<p>vagas</p>", subtype="html")
    else:
        msg.set_content(text)
        msg.add_alternative("<p>html</p>", subtype="html")
    return msg


def test_parse_alert_blocks_skip_noise() -> None:
    jobs = parse_alert_text(FIXTURE)
    assert [(j.view_id, j.title, j.company, j.location) for j in jobs] == [
        ("1000000001", "Engenheiro de Inteligência Artificial Sênior", "Empresa Alfa", "Rio de Janeiro, RJ"),
        ("1000000002", "Machine Learning Engineer", "Empresa Beta", "Brasil (Remoto)"),
        ("1000000003", "Cientista de Dados Sr. - Banco de Talentos", "Empresa Gama", "São Paulo, SP"),
        ("1000000004", "LLM Engineer - Trabalho Remoto", "Empresa Delta", "Curitiba, PR"),
    ]


def test_parse_english_and_short_block() -> None:
    text = "Data Scientist\nACME\nView job: https://www.linkedin.com/comm/jobs/view/42/?x=1\n"
    jobs = parse_alert_text(text)
    assert [(j.view_id, j.title, j.company, j.location) for j in jobs] == [("42", "Data Scientist", "ACME", None)]
    assert parse_alert_text("Só um título\nView job: https://www.linkedin.com/jobs/view/7/") == []


def test_jobs_from_message_low_fidelity_clean_url_and_remote() -> None:
    jobs = jobs_from_message(_message())
    first, second, _, fourth = jobs
    assert first.id == "linkedin:1000000001" and first.source == "linkedin_alerts"
    assert first.url == "https://www.linkedin.com/jobs/view/1000000001/"  # sem trackingId
    assert first.low_fidelity and first.description == "" and first.publisher == "LinkedIn"
    assert first.posted_at is not None and first.posted_at.date() == date(2026, 11, 9)
    assert first.is_remote is None and second.is_remote is True and fourth.is_remote is True
    assert detect_modality(first) is Modality.UNKNOWN and detect_modality(second) is Modality.REMOTE


def test_assume_remote_sender() -> None:
    jobs = jobs_from_message(_message(), assume_remote=True)
    assert all(j.is_remote for j in jobs)


def test_html_only_message_is_skipped() -> None:
    assert jobs_from_message(_message(html_only=True)) == []


def test_imap_since_format() -> None:
    assert imap_since(3, today=date(2026, 11, 9)) == "06-Nov-2026"


class FakeIMAP:
    """imaplib.IMAP4_SSL stand-in: one alert per sender, records calls."""

    instances: list["FakeIMAP"] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.by_sender = {"jobalerts-noreply@linkedin.com": [b"1"], "jobs-noreply@linkedin.com": [b"2"]}
        FakeIMAP.instances.append(self)

    def __enter__(self) -> "FakeIMAP":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def login(self, user: str, password: str) -> None:
        self.calls.append(("login", user))

    def select(self, mailbox: str, readonly: bool = False) -> tuple[str, list[bytes]]:
        self.calls.append(("select", mailbox, readonly))
        return "OK", [b"2"]

    def search(self, charset: None, criteria: str) -> tuple[str, list[bytes]]:
        self.calls.append(("search", criteria))
        sender = criteria.split('"')[1]
        return "OK", [b" ".join(self.by_sender.get(sender, []))]

    def fetch(self, msg_id: bytes, parts: str) -> tuple[str, list[Any]]:
        self.calls.append(("fetch", msg_id, parts))
        return "OK", [(b"1 (BODY[] {n}", _message().as_bytes()), b")"]


@pytest.fixture
def fake_imap(monkeypatch: pytest.MonkeyPatch) -> type[FakeIMAP]:
    FakeIMAP.instances = []
    monkeypatch.setattr(la.imaplib, "IMAP4_SSL", FakeIMAP)
    return FakeIMAP


def test_source_reads_readonly_and_dedupes_across_emails(fake_imap: type[FakeIMAP]) -> None:
    source = LinkedInAlertsSource(LinkedInAlertsConfig(enabled=True), "eu@gmail.com", "senha")
    jobs = source.fetch(SEARCH)
    assert len(jobs) == 4  # mesmas 4 vagas nos 2 emails
    assert source.emails_read == 2
    assert source.fetched_by_query == {"linkedin:jobalerts-noreply": 4, "linkedin:jobs-noreply": 4}
    calls = fake_imap.instances[0].calls
    assert ("select", '"INBOX"', True) in calls  # só leitura
    assert all(c[2] == "(BODY.PEEK[])" for c in calls if c[0] == "fetch")  # PEEK: não marca como lido
    assert all("senha" not in str(c) for c in calls)


def test_source_failure_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("sem rede")

    monkeypatch.setattr(la.imaplib, "IMAP4_SSL", boom)
    source = LinkedInAlertsSource(LinkedInAlertsConfig(enabled=True), "eu@gmail.com", "senha")
    assert source.fetch(SEARCH) == []


def test_required_env_includes_gmail_when_enabled(project_dir: Path) -> None:
    cfg = load_settings(project_dir / "config.yaml").config
    cfg.linkedin_alerts.enabled = True
    names = required_env(cfg, collect=True, send_email=True, use_llm=True)
    assert names.count("GMAIL_USER") == 1 and "GMAIL_APP_PASSWORD" in names
    assert "GMAIL_USER" in required_env(cfg, collect=True, send_email=False, use_llm=False)


def test_build_sources_adds_linkedin_when_enabled(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in [("RAPIDAPI_KEY", "k"), ("GMAIL_USER", "eu@gmail.com"), ("GMAIL_APP_PASSWORD", "p")]:
        monkeypatch.setenv(name, value)
    settings = load_settings(project_dir / "config.yaml")
    settings.config.linkedin_alerts.enabled = False
    assert [s.name for s in pipeline.build_sources(settings)] == ["jsearch"]
    settings.config.linkedin_alerts.enabled = True
    assert [s.name for s in pipeline.build_sources(settings)] == ["jsearch", "linkedin_alerts"]
