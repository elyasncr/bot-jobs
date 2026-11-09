"""Per-query yield: which queries bring jobs that nobody else brings, and which pay off.

Each job is attributed to the first query that found it (by fingerprint). Appended to
data/query_stats.jsonl so query choices can be decided with a week of data.
"""

import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path

from vagas_bot.log import get_logger
from vagas_bot.models import Job
from vagas_bot.scoring.ranker import RankedJob

log = get_logger("query_stats")


@dataclass(frozen=True)
class QueryStat:
    query: str
    fetched: int  # vagas devolvidas pela API
    first_found: int  # vagas que esta query trouxe primeiro (as outras repetiram)
    new: int  # das primeiras, quantas não estavam em seen.json
    passed_filters: int
    emailed: int
    llm_high: int  # nota do LLM >= min_score_to_email
    more_pages: bool  # havia mais páginas além de pages_per_query (vagas cortadas)


def build_query_stats(
    *,
    fetched_by_query: dict[str, int],
    origin_by_fingerprint: dict[str, str],
    full_page_queries: set[str],
    after_dedupe: list[Job],
    after_filters: list[Job],
    ranked: list[RankedJob],
    min_score: int,
) -> list[QueryStat]:
    def count(jobs: list[Job]) -> Counter[str]:
        return Counter(origin_by_fingerprint.get(j.fingerprint, "?") for j in jobs)

    first_found = Counter(origin_by_fingerprint.values())
    new, passed = count(after_dedupe), count(after_filters)
    emailed = count([r.job for r in ranked])
    high = count([r.job for r in ranked if not r.is_estimate and r.total >= min_score])
    return [
        QueryStat(
            query=q,
            fetched=n,
            first_found=first_found[q],
            new=new[q],
            passed_filters=passed[q],
            emailed=emailed[q],
            llm_high=high[q],
            more_pages=q in full_page_queries,
        )
        for q, n in fetched_by_query.items()
    ]


def log_query_stats(stats: list[QueryStat]) -> None:
    log.info("Rendimento por query (veio / 1ª a achar / novas / filtros / email / LLM alta):")
    for s in stats:
        log.info(
            "  %-55s %2d / %2d / %2d / %2d / %2d / %2d%s",
            s.query,
            s.fetched,
            s.first_found,
            s.new,
            s.passed_filters,
            s.emailed,
            s.llm_high,
            "  ⚠ havia mais páginas" if s.more_pages else "",
        )


def append_query_stats(path: Path, stats: list[QueryStat], today: date) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        for s in stats:
            fh.write(json.dumps({"date": today.isoformat(), **asdict(s)}, ensure_ascii=False) + "\n")
