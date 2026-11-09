"""LinkedIn job alert emails via IMAP (Gmail, same app password). Read-only.

Parses the text/plain part: each job is a block "title / company / location / ...
Visualizar vaga: https://www.linkedin.com/comm/jobs/view/<id>/?trackingId=...".
No description (low_fidelity=True) and the job page is NEVER fetched (SPEC 7.3).
"""

import imaplib
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email import message_from_bytes, policy
from email.message import EmailMessage
from email.utils import parsedate_to_datetime

from vagas_bot.config import LinkedInAlertsConfig, SearchConfig
from vagas_bot.log import get_logger
from vagas_bot.models import Job
from vagas_bot.text import make_fingerprint, normalize_text

log = get_logger("sources.linkedin")

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
_VIEW_RE = re.compile(r"^(?:visualizar vaga|ver vaga|view job)\s*:\s*\S*?/jobs/view/(\d+)", re.IGNORECASE)
_SEPARATOR_RE = re.compile(r"^-{10,}\s*$")
# Linhas que não são título/empresa/local (normalizadas: minúsculas, sem acento).
_NOISE_RE = re.compile(
    r"^https?://|conex(ao|oes)\b|connections?\b|ex-funcionari|ex-alun|instituicao de ensino|alumni"
    r"|esta empresa esta contratando|avaliando candidaturas|reviewing applicants"
    r"|this company is (actively )?hiring|candidate-se|candidatura simplificada|easy apply|apply with"
    r"|recrutando agora|actively recruiting|seja (um|uma) d[oa]s primeir|be an early applicant|promovida|promoted"
    r"|alerta de vaga|job alert|recomendacoes com base|amplie sua pesquisa|^vagas de |^ver todas|^veja todas"
    r"|r\$|/mes\b|/ano\b|/yr\b|/hr\b"
)
_REMOTE_RE = re.compile(r"\bremot[oa]\b|\bremote\b")


@dataclass(frozen=True)
class AlertJob:
    view_id: str
    title: str
    company: str
    location: str | None


def parse_alert_text(text: str) -> list[AlertJob]:
    """Jobs of one alert email (text/plain). Unknown blocks are skipped, never guessed."""
    jobs: list[AlertJob] = []
    block: list[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if _SEPARATOR_RE.match(line):
            block = []
            continue
        match = _VIEW_RE.match(line)
        if not match:
            if line:
                block.append(line)
            continue
        fields = [b for b in block if not _NOISE_RE.search(normalize_text(b))]
        block = []
        if len(fields) < 2:
            continue
        if len(fields) >= 3:
            title, company, location = fields[-3], fields[-2], fields[-1]
        else:
            title, company, location = fields[0], fields[1], None
        jobs.append(AlertJob(match.group(1), title, company, location))
    return jobs


def to_job(alert: AlertJob, received: datetime | None, assume_remote: bool = False) -> Job:
    where = normalize_text(f"{alert.title} {alert.location or ''}")
    return Job(
        id=f"linkedin:{alert.view_id}",
        fingerprint=make_fingerprint(alert.title, alert.company),
        source="linkedin_alerts",
        publisher="LinkedIn",
        title=alert.title,
        company=alert.company,
        location=alert.location,
        is_remote=True if assume_remote or _REMOTE_RE.search(where) else None,
        employment_type=None,
        description="",
        url=f"https://www.linkedin.com/jobs/view/{alert.view_id}/",  # sem trackingId
        posted_at=received,
        low_fidelity=True,
    )


def jobs_from_message(msg: EmailMessage, assume_remote: bool = False) -> list[Job]:
    body = msg.get_body(("plain",))
    if body is None:
        log.warning("Alerta do LinkedIn sem parte text/plain (assunto: %s): ignorado.", msg["Subject"])
        return []
    try:
        received = parsedate_to_datetime(msg["Date"]) if msg["Date"] else None
    except (TypeError, ValueError):
        received = None
    return [to_job(a, received, assume_remote) for a in parse_alert_text(body.get_content())]


def imap_since(days: int, today: date | None = None) -> str:
    return ((today or date.today()) - timedelta(days=days)).strftime("%d-%b-%Y")


class LinkedInAlertsSource:
    name = "linkedin_alerts"

    def __init__(self, cfg: LinkedInAlertsConfig, user: str, app_password: str) -> None:
        self.cfg = cfg
        self._user = user
        self._password = app_password
        self.emails_read = 0
        # Mesmos contadores da JSearch, para o rendimento entrar em query_stats.jsonl.
        self.fetched_by_query: dict[str, int] = {}
        self.origin_by_fingerprint: dict[str, str] = {}
        self.full_page_queries: set[str] = set()

    def fetch(self, cfg: SearchConfig) -> list[Job]:  # noqa: ARG002 — mesma interface das outras fontes
        try:
            messages = self._read_messages()
        except (imaplib.IMAP4.error, OSError) as exc:
            log.warning("LinkedIn (IMAP): falhou (%s). Seguindo sem esta fonte.", exc)
            return []
        jobs: dict[str, Job] = {}
        for sender, msg in messages:
            found = jobs_from_message(msg, assume_remote=sender in self.cfg.assume_remote_senders)
            label = f"linkedin:{sender.split('@')[0]}"
            self.fetched_by_query[label] = self.fetched_by_query.get(label, 0) + len(found)
            for job in found:
                jobs.setdefault(job.id, job)  # a mesma vaga vem em vários alertas
                self.origin_by_fingerprint.setdefault(job.fingerprint, label)
        log.info("LinkedIn (IMAP): %d emails de alerta, %d vagas únicas (desde %s).",
                 self.emails_read, len(jobs), imap_since(self.cfg.since_days))
        return list(jobs.values())

    def _read_messages(self) -> list[tuple[str, EmailMessage]]:
        since = imap_since(self.cfg.since_days)
        out: list[tuple[str, EmailMessage]] = []
        with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, timeout=60) as imap:
            imap.login(self._user, self._password)
            status, _ = imap.select(_quote(self.cfg.mailbox), readonly=True)  # só leitura: nada vira "lido"
            if status != "OK":
                raise imaplib.IMAP4.error(f"pasta '{self.cfg.mailbox}' não encontrada")
            for sender in self.cfg.senders:
                _, data = imap.search(None, f'(FROM "{sender}" SINCE {since})')
                for msg_id in (data[0] or b"").split():
                    _, parts = imap.fetch(msg_id, "(BODY.PEEK[])")
                    raw = next((p[1] for p in parts if isinstance(p, tuple)), None)
                    if raw:
                        out.append((sender, message_from_bytes(raw, policy=policy.default)))  # type: ignore[arg-type]
                        self.emails_read += 1
        return out


def _quote(mailbox: str) -> str:
    return mailbox if mailbox.startswith('"') else f'"{mailbox}"'
