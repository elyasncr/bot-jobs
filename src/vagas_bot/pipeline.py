"""Pipeline orchestration. Each stage is a function list[Job] -> list[Job].

collect → dedupe → filters → embeddings pre-rank → LLM (top_n) → rank → notify → persist
"""

import time
from dataclasses import dataclass, field
from datetime import date, datetime

from vagas_bot.config import ConfigError, Settings, missing_env, required_env
from vagas_bot.cv import load_cv, section_titles
from vagas_bot.embeddings.base import Embedder, get_embedder
from vagas_bot.filters import apply_filters, dedupe, final_contract_filter
from vagas_bot.log import get_logger
from vagas_bot.models import Job
from vagas_bot.notify.email import render_html
from vagas_bot.query_stats import append_query_stats, build_query_stats, log_query_stats
from vagas_bot.scoring.llm_base import LLMScorer, get_scorer
from vagas_bot.scoring.llm_stage import llm_stage
from vagas_bot.scoring.prerank import job_to_text, prerank
from vagas_bot.scoring.prompts import prefs_from_config
from vagas_bot.scoring.ranker import RankedJob, rank
from vagas_bot.sources.base import Source
from vagas_bot.sources.jsearch import JSearchSource
from vagas_bot.storage import (
    append_history,
    history_record,
    load_seen,
    mark_seen,
    prune_seen,
    save_seen,
)

log = get_logger("pipeline")


@dataclass(frozen=True)
class RunOptions:
    dry_run: bool = False
    no_llm: bool = False
    limit: int | None = None


@dataclass
class RunStats:
    started_at: datetime = field(default_factory=datetime.now)
    collected: int = 0
    after_dedupe: int = 0
    after_filters: int = 0
    sent_to_llm: int = 0
    llm_scored: int = 0
    emailed: int = 0
    jsearch_requests: int = 0
    llm_model: str | None = None
    llm_avg_s: float = 0.0
    elapsed_s: float = 0.0


def validate_env(settings: Settings, opts: RunOptions) -> None:
    names = required_env(
        settings.config,
        collect=True,
        send_email=False,  # Fase 6: passa a ser `not opts.dry_run`
        use_llm=not opts.no_llm,
    )
    missing = missing_env(settings, names)
    if missing:
        raise ConfigError(
            "Variáveis de ambiente ausentes: " + ", ".join(missing) + " (veja .env.example)"
        )


def build_sources(settings: Settings) -> list[Source]:
    api_key = settings.secrets.rapidapi_key
    assert api_key is not None  # garantido por validate_env
    return [JSearchSource(api_key.get_secret_value())]


def collect(sources: list[Source], settings: Settings, stats: RunStats) -> list[Job]:
    jobs: list[Job] = []
    for source in sources:
        jobs.extend(source.fetch(settings.config.search))
        if isinstance(source, JSearchSource):
            stats.jsearch_requests += source.requests_made
    return jobs


def log_ranked(ranked: list[RankedJob]) -> None:
    for item in ranked:
        job = item.job
        cosine = f" cos={job.embedding_score:.3f}" if job.embedding_score is not None else ""
        log.info(
            "  %3d%%%s%s [%s] %s · %s · contrato=%s",
            item.total,
            " (estimativa)" if item.is_estimate else "",
            cosine,
            job.publisher or "?",
            job.title,
            job.company or "?",
            job.pj_status.value,
        )


def embedding_stage(jobs: list[Job], embedder: Embedder, cv_md: str) -> list[Job]:
    """Whole embedding stage before the LLM; always frees VRAM at the end."""
    if not jobs:
        return jobs
    embedder.healthcheck()
    t0 = time.perf_counter()
    try:
        ranked = prerank(jobs, embedder, cv_md)
    finally:
        embedder.release()
    log.info("Embeddings (%s): %d vagas em %.1fs.", embedder.name, len(ranked), time.perf_counter() - t0)
    return ranked


def scoring_stage(
    jobs: list[Job], settings: Settings, cv_md: str, stats: RunStats, scorer: LLMScorer | None
) -> list[Job]:
    """Send the embedding top_n to the LLM; the rest is discarded by the pre-rank."""
    cfg = settings.config
    top = jobs[: cfg.embeddings.top_n]
    if len(jobs) > len(top):
        log.info("Pré-rank: %d vagas abaixo do top_n=%d descartadas.", len(jobs) - len(top), cfg.embeddings.top_n)
    stats.sent_to_llm = len(top)
    scored, info = llm_stage(
        top,
        scorer or get_scorer(settings),
        cv_md,
        prefs_from_config(cfg.filters),
        cfg.llm.max_calls_per_run,
    )
    stats.llm_model = info.model
    stats.llm_scored = info.scored
    stats.llm_avg_s = info.avg_s
    return scored


def send_notification(ranked: list[RankedJob], stats: RunStats) -> bool:
    """Fase 6: envio real por SMTP. Até lá, só registra no log e considera sucesso."""
    log.warning("Envio de email ainda não implementado (Fase 6): %d vagas seriam enviadas.", len(ranked))
    return True


def persist_state(settings: Settings, seen: dict[str, str], evaluated: list[Job]) -> None:
    today = date.today()
    pruned = prune_seen(seen, today, settings.config.state.prune_after_days)
    save_seen(settings.seen_path, mark_seen(pruned, evaluated, today))
    log.info("Estado gravado: %d vagas marcadas como vistas.", len(evaluated))


def record_history(settings: Settings, jobs: list[Job], embedder_name: str) -> None:
    today = date.today()
    records = [history_record(j, job_to_text(j), embedder_name, today) for j in jobs if j.score]
    append_history(settings.history_path, records)
    if records:
        log.info("Histórico: %d vagas anexadas a %s.", len(records), settings.history_path.name)


def report_queries(
    sources: list[Source], settings: Settings, opts: RunOptions,
    after_dedupe: list[Job], after_filters: list[Job], ranked: list[RankedJob],
) -> None:
    for source in sources:
        if not isinstance(source, JSearchSource):
            continue
        stats = build_query_stats(
            fetched_by_query=source.fetched_by_query,
            origin_by_fingerprint=source.origin_by_fingerprint,
            full_page_queries=source.full_page_queries,
            after_dedupe=after_dedupe,
            after_filters=after_filters,
            ranked=ranked,
            min_score=settings.config.scoring.min_score_to_email,
        )
        log_query_stats(stats)
        if not opts.dry_run:
            append_query_stats(settings.query_stats_path, stats, date.today())


def run_pipeline(
    settings: Settings,
    opts: RunOptions,
    sources: list[Source] | None = None,
    embedder: Embedder | None = None,
    scorer: LLMScorer | None = None,
) -> RunStats:
    t0 = time.perf_counter()
    stats = RunStats()
    cfg = settings.config
    validate_env(settings, opts)

    cv_md = load_cv(settings.cv_path)
    log.info("CV carregado: %d caracteres, %d seções.", len(cv_md), len(section_titles(cv_md)))
    seen = load_seen(settings.seen_path)

    sources = sources if sources is not None else build_sources(settings)
    jobs = collect(sources, settings, stats)
    stats.collected = len(jobs)

    jobs = dedupe(jobs, seen)
    stats.after_dedupe = len(jobs)
    evaluated = after_dedupe = jobs  # tudo que passou do dedupe é avaliado hoje e vira "visto"

    jobs = apply_filters(jobs, cfg.filters)
    if opts.limit is not None:
        jobs = jobs[: opts.limit]
    stats.after_filters = len(jobs)
    after_filters = jobs

    embedder = embedder or get_embedder(settings)
    jobs = embedding_stage(jobs, embedder, cv_md)
    if opts.no_llm:
        log.info("--no-llm: ranking só pela estimativa dos embeddings.")
    else:
        jobs = scoring_stage(jobs, settings, cv_md, stats, scorer)
        if not opts.dry_run:
            record_history(settings, jobs, embedder.name)

    jobs = final_contract_filter(jobs, cfg.filters.include_uncertain_contract)
    ranked = rank(jobs, cfg.scoring.min_score_to_email, cfg.email.max_jobs)
    stats.emailed = len(ranked)
    log_ranked(ranked)
    report_queries(sources, settings, opts, after_dedupe, after_filters, ranked)

    stats.elapsed_s = time.perf_counter() - t0
    log.info(
        "Contagem: coletadas=%d → após dedupe=%d → após filtros=%d → LLM=%d (ok %d) → email=%d "
        "(requisições JSearch: %d, tempo total %.0fs)",
        stats.collected,
        stats.after_dedupe,
        stats.after_filters,
        stats.sent_to_llm,
        stats.llm_scored,
        stats.emailed,
        stats.jsearch_requests,
        stats.elapsed_s,
    )

    if opts.dry_run:
        settings.preview_path.write_text(render_html(ranked, stats), encoding="utf-8")
        log.info("Dry-run: email não enviado, estado não gravado. Preview em %s", settings.preview_path)
        return stats

    if not ranked and not cfg.email.send_when_empty:
        log.info("Nenhuma vaga nova e send_when_empty=false: email não enviado.")
        persist_state(settings, seen, evaluated)
    elif send_notification(ranked, stats):
        persist_state(settings, seen, evaluated)
    else:
        log.error("Falha no envio do email: estado NÃO gravado (as vagas voltam na próxima execução).")
    return stats
