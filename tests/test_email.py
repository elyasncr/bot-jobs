import smtplib
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from helpers import make_job

from vagas_bot.notify import email as email_mod
from vagas_bot.notify.email import (
    GMAIL_CLIP_BYTES,
    EmailError,
    band_for,
    build_message,
    build_subject,
    group_by_band,
    html_size,
    render_html,
    render_text,
    send_email,
)
from vagas_bot.notify.sample import sample_ranked
from vagas_bot.pipeline import RunStats
from vagas_bot.scoring.ranker import RankedJob

SNAPSHOTS = Path(__file__).parent / "snapshots"
WHEN = datetime(2026, 11, 9, 8, 0)


def _stats() -> RunStats:
    return RunStats(
        started_at=WHEN, collected=42, after_dedupe=30, after_filters=12, sent_to_llm=12, llm_scored=12,
        jsearch_requests=5, llm_model="ollama/qwen3.5:9b", llm_avg_s=2.8, elapsed_s=95.0,
    )


def _assert_snapshot(name: str, content: str) -> None:
    """First run writes the snapshot; later runs compare. Delete the file to regenerate."""
    path = SNAPSHOTS / name
    if not path.exists():
        SNAPSHOTS.mkdir(exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
        pytest.skip(f"snapshot {name} criado; rode de novo")
    assert content == path.read_text(encoding="utf-8")


@pytest.mark.parametrize("n", [0, 1, 30])
def test_html_snapshot(n: int) -> None:
    _assert_snapshot(f"email_{n}.html", render_html(sample_ranked(n), _stats()))


@pytest.mark.parametrize("n", [0, 1, 30])
def test_text_snapshot(n: int) -> None:
    _assert_snapshot(f"email_{n}.txt", render_text(sample_ranked(n), _stats()))


def test_subject() -> None:
    assert build_subject(sample_ranked(3), WHEN) == "[Vagas PJ] 3 novas vagas — 09/11 (top 88%)"
    assert build_subject(sample_ranked(1), WHEN) == "[Vagas PJ] 1 nova vaga — 09/11 (top 88%)"
    assert build_subject([], WHEN) == "[Vagas PJ] 0 novas vagas — 09/11"


def test_bands() -> None:
    assert band_for(80).label == "Alta aderência"
    assert band_for(79).label == "Boa" and band_for(65).label == "Boa"
    assert band_for(64).label == "Possível" and band_for(50).label == "Possível"


def test_group_by_band_order_and_ranges() -> None:
    groups = group_by_band(sample_ranked(3))
    assert [(g["label"], g["range"], len(g["cards"])) for g in groups] == [
        ("Alta aderência", "≥ 80%", 1),
        ("Boa", "65–79%", 1),
        ("Possível", "50–64%", 1),
    ]


def test_card_badges_and_content() -> None:
    html = render_html(sample_ranked(3), _stats())
    for text in ("88%", "PJ", "CLT ou PJ", "Não informado", "estimativa", "via LinkedIn", "08/11",
                 "LLMs e RAG em produção", "Kubernetes não citado no CV", "https://example.com/vaga/0",
                 "Modelo: ollama/qwen3.5:9b", "1min 35s", "2.8s/vaga", "Chamadas à JSearch: 5",
                 "42 coletadas", "12 após filtros", "12 avaliadas pelo LLM", "3 enviadas"):
        assert text in html, text
    assert "<style" not in html  # CSS só inline (o Gmail remove <style>)


def test_html_escapes_job_content_but_text_does_not() -> None:
    job = make_job(title="R&D <AI> Engineer", embedding_score=0.5)
    ranked = [RankedJob(job, 70, is_estimate=True)]
    assert "R&amp;D &lt;AI&gt; Engineer" in render_html(ranked, _stats())
    assert "R&D <AI> Engineer" in render_text(ranked, _stats())


def test_message_is_multipart_alternative() -> None:
    msg = build_message(sample_ranked(3), _stats(), "bot@gmail.com", "eu@gmail.com", subject_prefix="[TESTE] ")
    assert msg["Subject"].startswith("[TESTE] [Vagas PJ] 3 novas vagas")
    assert msg.get_content_type() == "multipart/alternative"
    assert [p.get_content_type() for p in msg.iter_parts()] == ["text/plain", "text/html"]


def test_thirty_jobs_fit_under_gmail_clip_limit() -> None:
    msg = build_message(sample_ranked(30), _stats(), "a@b.c", "a@b.c")
    assert html_size(msg) < GMAIL_CLIP_BYTES


class _FakeSMTP:
    instances: list["_FakeSMTP"] = []

    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host, self.port, self.sent, self.login_args = host, port, [], None
        _FakeSMTP.instances.append(self)

    def __enter__(self) -> "_FakeSMTP":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def login(self, user: str, password: str) -> None:
        if password == "wrong":
            raise smtplib.SMTPAuthenticationError(535, b"bad")
        self.login_args = (user, password)

    def send_message(self, msg: Any) -> None:
        self.sent.append(msg)


def test_send_email_uses_gmail_ssl(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(email_mod.smtplib, "SMTP_SSL", _FakeSMTP)
    msg = build_message(sample_ranked(1), _stats(), "bot@gmail.com", "eu@gmail.com")
    send_email(msg, "bot@gmail.com", "app-pass")
    smtp = _FakeSMTP.instances[-1]
    assert (smtp.host, smtp.port) == ("smtp.gmail.com", 465)
    assert smtp.login_args == ("bot@gmail.com", "app-pass") and smtp.sent == [msg]


def test_send_email_auth_error_has_no_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(email_mod.smtplib, "SMTP_SSL", _FakeSMTP)
    msg = build_message([], _stats(), "bot@gmail.com", "eu@gmail.com")
    with pytest.raises(EmailError) as info:
        send_email(msg, "bot@gmail.com", "wrong")
    assert "wrong" not in str(info.value)
