"""Dedupe, hard filters (title, modality) and the PJ regex classifier.

Every filter is a pure function list[Job] -> list[Job]. Text matching always runs on
normalized text (lowercase, no accents), so 'Estágio' matches 'estagio'.
"""

import re
from collections.abc import Iterable
from enum import Enum

from vagas_bot.config import FiltersConfig
from vagas_bot.log import get_logger
from vagas_bot.models import Job, PJStatus
from vagas_bot.text import normalize_text

log = get_logger("filters")

PJ_POSITIVE = [
    r"\bpj\b",
    r"pessoa juridica",
    r"\bcnpj\b",
    r"contrato pj",
    r"modelo pj",
    r"contractor",
    r"\bb2b\b",
    r"freelanc",
]
PJ_NEGATIVE = [r"\bclt\b", r"carteira assinada", r"regime clt"]
_PJ_POSITIVE_RE = re.compile("|".join(PJ_POSITIVE))
_PJ_NEGATIVE_RE = re.compile("|".join(PJ_NEGATIVE))
# Weaker CLT evidence, used only to accept an LLM "clt" verdict (never to discard by itself).
_CLT_SIGNALS_RE = re.compile(
    "|".join(PJ_NEGATIVE)
    + r"|\bfgts\b|vale[- ]refeicao|vale[- ]alimentacao|\b13o\b|13o salario|decimo terceiro"
    + r"|ferias remuneradas|\befetivo\b|\befetivacao\b"
)

_REMOTE_RE = re.compile(
    r"\bremot[oa]s?\b|\bremote\b|home[ -]?office|\banywhere\b|qualquer lugar|work from home"
)
# Only unambiguous phrases count in the description ("trabalho remoto 2x/semana" is hybrid).
_STRONG_REMOTE_BODY_RE = re.compile(
    r"100% ?remot|totalmente remot|integralmente remot|fully remote|full[- ]remote|100% remote"
    r"|remote[- ]first|(?:modelo|modalidade|regime)(?: de trabalho)?:? ?remot|home office 100%"
)
_HYBRID_RE = re.compile(r"\bhibrid[oa]\b|\bhybrid\b")
_ONSITE_RE = re.compile(r"\bpresencial\b|\bon[- ]?site\b|\bin[- ]office\b")


class Modality(str, Enum):
    REMOTE = "remote"
    HYBRID = "hybrid"
    ONSITE = "onsite"
    UNKNOWN = "unknown"


# --- dedupe ---------------------------------------------------------------------------


def _preference(job: Job) -> tuple[bool, int]:
    """Higher is better: LinkedIn first, then the longest description."""
    return ((job.publisher or "").casefold() == "linkedin", len(job.description))


def dedupe(jobs: list[Job], seen: Iterable[str]) -> list[Job]:
    """Drop jobs already seen (by id or fingerprint) and collapse duplicates within the batch."""
    seen_keys = set(seen)
    fresh = [j for j in jobs if j.id not in seen_keys and j.fingerprint not in seen_keys]

    best: dict[str, Job] = {}
    order: list[str] = []
    for job in fresh:
        key = job.fingerprint
        current = best.get(key)
        if current is None:
            order.append(key)
            best[key] = job
        elif _preference(job) > _preference(current):
            best[key] = job

    return [best[key] for key in order]


# --- title ----------------------------------------------------------------------------


def _keyword_re(keywords: list[str]) -> re.Pattern[str] | None:
    words = [re.escape(normalize_text(k)) for k in keywords if k.strip()]
    return re.compile(r"\b(?:" + "|".join(words) + r")\b") if words else None


def filter_title(jobs: list[Job], exclude_keywords: list[str]) -> list[Job]:
    pattern = _keyword_re(exclude_keywords)
    if pattern is None:
        return jobs
    return [j for j in jobs if not pattern.search(normalize_text(j.title))]


# --- modality -------------------------------------------------------------------------


def detect_modality(job: Job) -> Modality:
    """Remote flag, remote words in title/location or an unambiguous remote phrase in the
    description win; then explicit hybrid/onsite anywhere."""
    head = normalize_text(f"{job.title} {job.location or ''}")
    body = normalize_text(job.description)
    if job.is_remote or _REMOTE_RE.search(head) or _STRONG_REMOTE_BODY_RE.search(body):
        return Modality.REMOTE
    if _HYBRID_RE.search(head) or _HYBRID_RE.search(body):
        return Modality.HYBRID
    if _ONSITE_RE.search(head) or _ONSITE_RE.search(body):
        return Modality.ONSITE
    return Modality.UNKNOWN


def _in_allowed_city(job: Job, cities: list[str]) -> bool:
    location = normalize_text(job.location or "")
    return any(normalize_text(city) in location for city in cities if city.strip())


def keep_by_modality(job: Job, cfg: FiltersConfig) -> bool:
    """Remote: kept if 'remote' is allowed. Otherwise only in hybrid_allowed_cities.

    Unknown modality in an allowed city is kept (many ads don't say; the LLM judges later).
    Explicit on-site requires 'onsite' in modalities.
    """
    modality = detect_modality(job)
    if modality is Modality.REMOTE:
        return "remote" in cfg.modalities
    if not _in_allowed_city(job, cfg.hybrid_allowed_cities):
        return False
    if modality is Modality.ONSITE:
        return "onsite" in cfg.modalities
    return "hybrid" in cfg.modalities or "onsite" in cfg.modalities


def filter_modality(jobs: list[Job], cfg: FiltersConfig) -> list[Job]:
    kept = []
    for job in jobs:
        if keep_by_modality(job, cfg):
            kept.append(job)
        else:
            log.debug("Modalidade descartou: %s · %s (%s)", job.title, job.location, detect_modality(job).value)
    return kept


# --- PJ classifier --------------------------------------------------------------------


def classify_pj(job: Job) -> PJStatus:
    text = normalize_text(f"{job.title} {job.description}")
    types = {t.strip().upper() for t in (job.employment_type or "").split(",")}
    positive = bool(_PJ_POSITIVE_RE.search(text)) or "CONTRACTOR" in types
    negative = bool(_PJ_NEGATIVE_RE.search(text))
    if positive and negative:
        return PJStatus.BOTH
    if positive:
        return PJStatus.PJ
    if negative:
        return PJStatus.CLT
    return PJStatus.UNCERTAIN


def has_clt_signals(job: Job) -> bool:
    return bool(_CLT_SIGNALS_RE.search(normalize_text(f"{job.title} {job.description}")))


def apply_pj_classifier(jobs: list[Job]) -> list[Job]:
    """Tag pj_status and drop CLT-only jobs. UNCERTAIN goes on; the LLM has the final word."""
    tagged = [j.model_copy(update={"pj_status": classify_pj(j)}) for j in jobs]
    return [j for j in tagged if j.pj_status is not PJStatus.CLT]


def final_contract_filter(jobs: list[Job], include_uncertain: bool) -> list[Job]:
    """After scoring: drop CLT (e.g. revealed by the LLM) and, if configured, still-uncertain jobs."""
    return [
        j
        for j in jobs
        if j.pj_status is not PJStatus.CLT
        and (include_uncertain or j.pj_status is not PJStatus.UNCERTAIN)
    ]


# --- all hard filters -----------------------------------------------------------------


def apply_filters(jobs: list[Job], cfg: FiltersConfig) -> list[Job]:
    steps = [
        ("título", lambda js: filter_title(js, cfg.exclude_title_keywords)),
        ("modalidade", lambda js: filter_modality(js, cfg)),
        ("regex PJ (CLT descartadas)", apply_pj_classifier),
    ]
    for label, step in steps:
        before = len(jobs)
        jobs = step(jobs)
        log.info("Filtro %s: %d → %d", label, before, len(jobs))
    return jobs
