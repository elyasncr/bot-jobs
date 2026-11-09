"""Email rendering and sending. Phase 1: minimal HTML preview only (full email in Phase 6)."""

from typing import TYPE_CHECKING

from jinja2 import Environment, PackageLoader, select_autoescape

from vagas_bot.scoring.ranker import RankedJob

if TYPE_CHECKING:
    from vagas_bot.pipeline import RunStats

_env = Environment(
    loader=PackageLoader("vagas_bot.notify", "templates"),
    autoescape=select_autoescape(["html", "j2"]),
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_html(ranked: list[RankedJob], stats: "RunStats") -> str:
    return _env.get_template("email.html.j2").render(ranked=ranked, stats=stats)
