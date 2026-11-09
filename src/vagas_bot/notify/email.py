"""Email: subject, HTML (Jinja2, inline CSS, mobile-first) + text/plain, sent via Gmail SMTP SSL."""

import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage
from email.utils import formatdate, make_msgid
from typing import TYPE_CHECKING, Any

from jinja2 import Environment, PackageLoader

from vagas_bot.filters import Modality, detect_modality
from vagas_bot.models import PJStatus
from vagas_bot.scoring.ranker import RankedJob

if TYPE_CHECKING:
    from vagas_bot.pipeline import RunStats

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465
GMAIL_CLIP_BYTES = 102_000  # o Gmail corta ("mensagem cortada") emails HTML acima de ~102 KB

_env = Environment(
    loader=PackageLoader("vagas_bot.notify", "templates"),
    autoescape=lambda name: name is not None and ".html" in name,  # o .txt não é escapado
    trim_blocks=True,
    lstrip_blocks=True,
)


class EmailError(Exception):
    """Sending failed (message in Portuguese, never contains secrets)."""


@dataclass(frozen=True)
class Band:
    label: str
    min_total: int
    color: str


BANDS = [
    Band("Alta aderência", 80, "#1a7f37"),
    Band("Boa", 65, "#0969da"),
    Band("Possível", 50, "#9a6700"),
]
FALLBACK_BAND = Band("Abaixo de 50%", 0, "#6e7781")

CONTRACT_LABELS = {
    PJStatus.PJ: "PJ",
    PJStatus.BOTH: "CLT ou PJ",
    PJStatus.UNCERTAIN: "Não informado",
    PJStatus.CLT: "CLT",
}
MODALITY_LABELS = {
    Modality.REMOTE: "Remoto",
    Modality.HYBRID: "Híbrido",
    Modality.ONSITE: "Presencial",
    Modality.UNKNOWN: "Modalidade não informada",
}


def band_for(total: int) -> Band:
    return next((b for b in BANDS if total >= b.min_total), FALLBACK_BAND)


def card(item: RankedJob) -> dict[str, Any]:
    """Template-ready view of one job."""
    job, score = item.job, item.job.score
    place = ", ".join(p for p in [job.location, MODALITY_LABELS[detect_modality(job)]] if p)
    return {
        "title": job.title,
        "url": job.url,
        "company": job.company or "Empresa não informada",
        "place": place,
        "total": item.total,
        "color": band_for(item.total).color,
        "contract": CONTRACT_LABELS[job.pj_status],
        "publisher": job.publisher,
        "posted": job.posted_at.strftime("%d/%m") if job.posted_at else None,
        "summary": score.summary if score else None,
        "strengths": score.strengths[:3] if score else [],
        "gaps": score.gaps[:3] if score else [],
        "is_estimate": item.is_estimate,
        "low_fidelity": job.low_fidelity,
    }


def group_by_band(ranked: list[RankedJob]) -> list[dict[str, Any]]:
    groups = []
    for band in [*BANDS, FALLBACK_BAND]:
        upper = next((b.min_total for b in reversed(BANDS) if b.min_total > band.min_total), 101)
        cards = [card(r) for r in ranked if band.min_total <= r.total < upper]
        if cards:
            groups.append({"label": band.label, "color": band.color, "range": _range(band, upper), "cards": cards})
    return groups


def _range(band: Band, upper: int) -> str:
    return f"≥ {band.min_total}%" if upper > 100 else f"{band.min_total}–{upper - 1}%"


def _duration(seconds: float) -> str:
    minutes, secs = divmod(round(seconds), 60)
    return f"{minutes}min {secs:02d}s" if minutes else f"{secs}s"


def _context(ranked: list[RankedJob], stats: "RunStats") -> dict[str, Any]:
    return {
        "date": stats.started_at.strftime("%d/%m/%Y"),
        "stats": stats,
        "groups": group_by_band(ranked),
        "count": len(ranked),
        "model": stats.llm_model or "só embeddings (sem LLM)",
        "duration": _duration(stats.elapsed_s),
        "avg": f"{stats.llm_avg_s:.1f}s/vaga" if stats.llm_avg_s else "—",
    }


def build_subject(ranked: list[RankedJob], when: datetime) -> str:
    n = len(ranked)
    noun = "nova vaga" if n == 1 else "novas vagas"
    top = f" (top {max(r.total for r in ranked)}%)" if ranked else ""
    return f"[Vagas PJ] {n} {noun} — {when:%d/%m}{top}"


def render_html(ranked: list[RankedJob], stats: "RunStats") -> str:
    return _env.get_template("email.html.j2").render(**_context(ranked, stats))


def render_text(ranked: list[RankedJob], stats: "RunStats") -> str:
    return _env.get_template("email.txt.j2").render(**_context(ranked, stats))


def build_message(
    ranked: list[RankedJob], stats: "RunStats", sender: str, to: str, subject_prefix: str = ""
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject_prefix + build_subject(ranked, stats.started_at)
    msg["From"] = sender
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain="vagas-pj-bot")
    msg.set_content(render_text(ranked, stats))
    msg.add_alternative(render_html(ranked, stats), subtype="html")
    return msg


def html_size(msg: EmailMessage) -> int:
    html = msg.get_body(preferencelist=("html",))
    return len(html.get_content().encode("utf-8")) if html else 0


def send_email(msg: EmailMessage, user: str, app_password: str, timeout_s: float = 30.0) -> None:
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=timeout_s) as smtp:
            smtp.login(user, app_password)
            smtp.send_message(msg)
    except smtplib.SMTPAuthenticationError as exc:
        raise EmailError("Gmail recusou o login (confira GMAIL_USER e a senha de app).") from exc
    except (OSError, smtplib.SMTPException) as exc:
        raise EmailError(f"Falha no envio SMTP: {type(exc).__name__}: {exc}") from exc
