"""JSearch (RapidAPI) source — aggregates Google for Jobs, including LinkedIn.

Checked against the live API on 2026-11-09:
- The search endpoint is `/search-v2` (`/search` now returns 404).
- Jobs come under `data.jobs`; pagination uses `data.cursor` (no `page` param).
- `job_employment_type` is localized ("Tempo integral e Prestador de serviços");
  `job_employment_types` is the enum list but may omit CONTRACTOR, so both are combined.
- `job_posted_at_datetime_utc` is often null; `job_posted_at` holds relative text ("há 4 dias").
- `work_from_home=true` is honoured (10/10 remote in a live test); `remote_jobs_only` is not
  recognized and returned 0 jobs.
"""

import re
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)
from tenacity.wait import WaitBaseT

from vagas_bot.config import SearchConfig
from vagas_bot.log import get_logger
from vagas_bot.models import Job
from vagas_bot.text import make_fingerprint, normalize_text

log = get_logger("jsearch")

HOST = "jsearch.p.rapidapi.com"
SEARCH_URL = f"https://{HOST}/search-v2"
FREE_PLAN_MONTHLY_QUOTA = 200
BUSINESS_DAYS_PER_MONTH = 22
LOW_FIDELITY_MIN_CHARS = 200
RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# Localized employment-type fragments (normalized, no accents) → JSearch enum.
_LOCALIZED_TYPES = {
    "prestador de servico": "CONTRACTOR",
    "contractor": "CONTRACTOR",
    "tempo integral": "FULLTIME",
    "full-time": "FULLTIME",
    "meio periodo": "PARTTIME",
    "part-time": "PARTTIME",
    "temporario": "TEMPORARY",
    "estagio": "INTERN",
}

_RELATIVE_UNITS = {
    "minuto": "minutes",
    "minute": "minutes",
    "hora": "hours",
    "hour": "hours",
    "dia": "days",
    "day": "days",
    "semana": "weeks",
    "week": "weeks",
    "mes": "months",
    "month": "months",
}
_RELATIVE_RE = re.compile(r"(\d+)\+?\s*(minuto|minute|hora|hour|dia|day|semana|week|mes|month)")


class RetryableHTTPError(Exception):
    """429/5xx from JSearch — worth retrying with backoff."""


def query_variants(query: str) -> list[str]:
    """Only the plain query. The SPEC's extra '{query} PJ' variant returned 0 jobs in every live
    test (2026-11-09) while costing half of the 200 req/month quota; PJ is detected by the regex."""
    return [query]


def estimate_monthly_requests(cfg: SearchConfig) -> int:
    per_run = len(cfg.queries) * len(query_variants("x")) * cfg.pages_per_query
    return per_run * BUSINESS_DAYS_PER_MONTH


def parse_posted_at(raw: dict[str, Any], now: datetime | None = None) -> datetime | None:
    iso = raw.get("job_posted_at_datetime_utc")
    if iso:
        try:
            return datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            pass
    ts = raw.get("job_posted_at_timestamp")
    if isinstance(ts, int | float):
        return datetime.fromtimestamp(ts, tz=UTC)
    return parse_relative(raw.get("job_posted_at"), now)


def parse_relative(text: str | None, now: datetime | None = None) -> datetime | None:
    """Parse 'há 4 dias', '12 hours ago', 'hoje', 'ontem'. Months approximated as 30 days."""
    if not text:
        return None
    now = now or datetime.now(UTC)
    norm = normalize_text(text)
    if norm in {"hoje", "today", "agora", "just now"}:
        return now
    if norm in {"ontem", "yesterday"}:
        return now - timedelta(days=1)
    match = _RELATIVE_RE.search(norm)
    if not match:
        return None
    amount, unit = int(match.group(1)), _RELATIVE_UNITS[match.group(2)]
    if unit == "months":
        return now - timedelta(days=30 * amount)
    return now - timedelta(**{unit: amount})


def employment_types(raw: dict[str, Any]) -> list[str]:
    types = {str(t).upper() for t in raw.get("job_employment_types") or []}
    localized = normalize_text(raw.get("job_employment_type") or "")
    types |= {enum for fragment, enum in _LOCALIZED_TYPES.items() if fragment in localized}
    return sorted(types)


def _location(raw: dict[str, Any]) -> str | None:
    if raw.get("job_location"):
        return raw["job_location"]
    parts = [raw.get(k) for k in ("job_city", "job_state", "job_country")]
    return ", ".join(p for p in parts if p) or None


def _to_job(raw: dict[str, Any], now: datetime | None = None) -> Job | None:
    """Single mapping point from a JSearch job object to Job. Returns None if unusable."""
    job_id, title = raw.get("job_id"), (raw.get("job_title") or "").strip()
    url = raw.get("job_apply_link") or raw.get("job_google_link")
    if not job_id or not title or not url:
        return None
    company = (raw.get("employer_name") or "").strip()
    description = (raw.get("job_description") or "").strip()
    types = employment_types(raw)
    return Job(
        id=str(job_id),
        fingerprint=make_fingerprint(title, company),
        source="jsearch",
        publisher=raw.get("job_publisher"),
        title=title,
        company=company,
        location=_location(raw),
        is_remote=raw.get("job_is_remote"),
        employment_type=",".join(types) or None,
        description=description,
        url=url,
        posted_at=parse_posted_at(raw, now),
        low_fidelity=len(description) < LOW_FIDELITY_MIN_CHARS,
    )


def filter_publishers(jobs: list[Job], publishers: list[str]) -> list[Job]:
    if not publishers:
        return jobs
    allowed = {p.casefold() for p in publishers}
    return [j for j in jobs if (j.publisher or "").casefold() in allowed]


class JSearchSource:
    name = "jsearch"

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.Client | None = None,
        max_attempts: int = 4,
        wait: WaitBaseT | None = None,
        timeout_s: float = 60.0,  # queries com OR passaram de 30s num teste real
    ) -> None:
        self._api_key = api_key
        self._client = client or httpx.Client(timeout=timeout_s)
        self._max_attempts = max_attempts
        self._wait = wait or wait_exponential(multiplier=1, min=2, max=30)
        self.requests_made = 0
        self.quota_remaining: int | None = None
        # Medição por query: quantas vagas cada uma trouxe e qual achou cada vaga primeiro.
        self.fetched_by_query: dict[str, int] = {}
        self.full_page_queries: set[str] = set()
        self.origin_by_fingerprint: dict[str, str] = {}

    def fetch(self, cfg: SearchConfig) -> list[Job]:
        self._warn_quota(cfg)
        jobs: list[Job] = []
        for query in cfg.queries:
            for variant in query_variants(query):
                try:
                    found = self._search(variant, cfg)
                except (httpx.HTTPError, RetryableHTTPError, ValueError) as exc:
                    log.warning("JSearch: query '%s' falhou (%s). Seguindo.", variant, exc)
                    continue
                log.info("JSearch: '%s' → %d vagas", variant, len(found))
                self.fetched_by_query[variant] = len(found)
                for job in found:
                    self.origin_by_fingerprint.setdefault(job.fingerprint, variant)
                jobs.extend(found)

        kept = filter_publishers(jobs, cfg.publishers)
        log.info(
            "JSearch: %d vagas coletadas, %d após filtro de publisher %s. Requisições: %d%s",
            len(jobs),
            len(kept),
            cfg.publishers or "(todos)",
            self.requests_made,
            f" (cota restante no mês: {self.quota_remaining})" if self.quota_remaining is not None else "",
        )
        return kept

    def _search(self, query: str, cfg: SearchConfig) -> list[Job]:
        jobs: list[Job] = []
        cursor: str | None = None
        for _ in range(cfg.pages_per_query):
            params: dict[str, str] = {
                "query": query,
                "country": cfg.country,
                "date_posted": cfg.date_posted,
            }
            if cfg.remote_only:
                params["work_from_home"] = "true"
            if cursor:
                params["cursor"] = cursor
            data = self._get(params).get("data") or {}
            jobs.extend(job for raw in data.get("jobs") or [] if (job := _to_job(raw)))
            cursor = data.get("cursor")
            if not cursor:
                break
        else:
            if cursor:  # parou por pages_per_query, mas havia mais páginas
                self.full_page_queries.add(query)
        return jobs

    def _get(self, params: dict[str, str]) -> dict[str, Any]:
        retrying = Retrying(
            retry=retry_if_exception_type((RetryableHTTPError, httpx.TimeoutException)),
            stop=stop_after_attempt(self._max_attempts),
            wait=self._wait,
            before_sleep=_log_retry,
            reraise=True,
        )
        return retrying(self._get_once, params)

    def _get_once(self, params: dict[str, str]) -> dict[str, Any]:
        self.requests_made += 1
        response = self._client.get(
            SEARCH_URL,
            params=params,
            headers={"X-RapidAPI-Key": self._api_key, "X-RapidAPI-Host": HOST},
        )
        self._track_quota(response)
        if response.status_code in RETRYABLE_STATUS:
            raise RetryableHTTPError(f"HTTP {response.status_code}")
        response.raise_for_status()
        return response.json()

    def _track_quota(self, response: httpx.Response) -> None:
        remaining = response.headers.get("x-ratelimit-requests-remaining")
        if remaining is not None and remaining.isdigit():
            self.quota_remaining = int(remaining)

    @staticmethod
    def _warn_quota(cfg: SearchConfig) -> None:
        monthly = estimate_monthly_requests(cfg)
        if monthly > FREE_PLAN_MONTHLY_QUOTA:
            log.warning(
                "JSearch: esta configuração gasta ~%d requisições/mês em dias úteis "
                "(%d queries × %d variantes × %d páginas × %d dias), acima da cota gratuita de %d.",
                monthly,
                len(cfg.queries),
                len(query_variants("x")),
                cfg.pages_per_query,
                BUSINESS_DAYS_PER_MONTH,
                FREE_PLAN_MONTHLY_QUOTA,
            )


def _log_retry(state: Any) -> None:
    log.warning(
        "JSearch: %s, tentativa %d — aguardando %.0fs",
        state.outcome.exception() if state.outcome else "erro",
        state.attempt_number,
        state.next_action.sleep if state.next_action else 0,
    )
