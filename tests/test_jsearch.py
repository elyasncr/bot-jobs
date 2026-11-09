import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
from tenacity import wait_none

from vagas_bot.config import SearchConfig
from vagas_bot.sources.jsearch import (
    SEARCH_URL,
    JSearchSource,
    _to_job,
    employment_types,
    estimate_monthly_requests,
    filter_publishers,
    parse_relative,
    query_variants,
)

FIXTURE = Path(__file__).parent / "fixtures" / "jsearch_search_v2.json"
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)


@pytest.fixture
def payload() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def raw_jobs(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return payload["data"]["jobs"]


def _cfg(**overrides: Any) -> SearchConfig:
    base: dict[str, Any] = {"queries": ["AI Engineer"], "publishers": []}
    return SearchConfig.model_validate(base | overrides)


def _source() -> JSearchSource:
    return JSearchSource("test-key", client=httpx.Client(), wait=wait_none())


# --- _to_job --------------------------------------------------------------------------


def test_to_job_maps_fields(raw_jobs: list[dict[str, Any]]) -> None:
    job = _to_job(raw_jobs[0], now=NOW)
    assert job is not None
    assert job.id == "FAKE_JOB_ID_1=="
    assert job.source == "jsearch"
    assert job.publisher == "LinkedIn"
    assert job.title == "Analista de Engenharia de IA"
    assert job.company == "Empresa Alfa"
    assert job.location == "Camaçari, BA"
    assert job.is_remote is False
    assert job.employment_type == "FULLTIME"
    assert job.url == "https://example.com/jobs/view/1001"
    assert job.posted_at == NOW - timedelta(days=4)
    assert job.fingerprint and len(job.fingerprint) == 40


def test_to_job_detects_contractor_from_localized_text(raw_jobs: list[dict[str, Any]]) -> None:
    job = _to_job(raw_jobs[3], now=NOW)
    assert job is not None
    assert job.employment_type == "CONTRACTOR,FULLTIME"
    assert job.posted_at is None


def test_to_job_prefers_iso_datetime(raw_jobs: list[dict[str, Any]]) -> None:
    job = _to_job(raw_jobs[2], now=NOW)
    assert job is not None
    assert job.posted_at == datetime(2026, 11, 8, 14, 0, tzinfo=UTC)


def test_to_job_skips_incomplete(raw_jobs: list[dict[str, Any]]) -> None:
    assert _to_job(raw_jobs[0] | {"job_id": None}) is None
    assert _to_job(raw_jobs[0] | {"job_title": "  "}) is None
    assert _to_job(raw_jobs[0] | {"job_apply_link": None, "job_google_link": None}) is None


def test_to_job_low_fidelity_when_description_short(raw_jobs: list[dict[str, Any]]) -> None:
    job = _to_job(raw_jobs[0] | {"job_description": ""})
    assert job is not None and job.low_fidelity is True


def test_employment_types_merges_sources() -> None:
    raw = {"job_employment_types": ["FULLTIME"], "job_employment_type": "Tempo integral e Prestador de serviços"}
    assert employment_types(raw) == ["CONTRACTOR", "FULLTIME"]
    assert employment_types({}) == []


@pytest.mark.parametrize(
    "text,expected",
    [
        ("há 4 dias", NOW - timedelta(days=4)),
        ("há 12 horas", NOW - timedelta(hours=12)),
        ("3 days ago", NOW - timedelta(days=3)),
        ("há 2 semanas", NOW - timedelta(weeks=2)),
        ("há 1 mês", NOW - timedelta(days=30)),
        ("30+ days ago", NOW - timedelta(days=30)),
        ("hoje", NOW),
        ("ontem", NOW - timedelta(days=1)),
        ("recentemente", None),
        (None, None),
    ],
)
def test_parse_relative(text: str | None, expected: datetime | None) -> None:
    assert parse_relative(text, NOW) == expected


# --- publishers / quota ---------------------------------------------------------------


def test_filter_publishers_case_insensitive(raw_jobs: list[dict[str, Any]]) -> None:
    jobs = [j for raw in raw_jobs if (j := _to_job(raw))]
    assert [j.publisher for j in filter_publishers(jobs, ["linkedin"])] == ["LinkedIn"]
    assert len(filter_publishers(jobs, [])) == len(jobs)
    assert len(filter_publishers(jobs, ["LINKEDIN", "glassdoor"])) == 2


def test_query_variants() -> None:
    assert query_variants("AI Engineer") == ["AI Engineer"]


def test_estimate_monthly_requests() -> None:
    cfg = _cfg(queries=["a", "b", "c"], pages_per_query=2)
    assert estimate_monthly_requests(cfg) == 3 * 2 * 22


def test_repo_config_fits_free_quota() -> None:
    from vagas_bot.config import load_app_config

    cfg = load_app_config(Path(__file__).resolve().parent.parent / "config.yaml")
    assert estimate_monthly_requests(cfg.search) <= 200


# --- HTTP (respx) ---------------------------------------------------------------------


@respx.mock
def test_fetch_sends_params_and_filters_publishers(payload: dict[str, Any]) -> None:
    route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=payload))
    source = _source()
    jobs = source.fetch(_cfg(queries=["AI Engineer", "Data Scientist"], publishers=["LinkedIn"]))

    queries = [call.request.url.params["query"] for call in route.calls]
    assert queries == ["AI Engineer", "Data Scientist"]
    first = route.calls[0].request
    assert first.headers["X-RapidAPI-Key"] == "test-key"
    assert first.headers["X-RapidAPI-Host"] == "jsearch.p.rapidapi.com"
    assert first.url.params["country"] == "br"
    assert first.url.params["date_posted"] == "3days"
    assert "work_from_home" not in first.url.params
    assert source.requests_made == 2
    assert [j.publisher for j in jobs] == ["LinkedIn", "LinkedIn"]


@respx.mock
def test_remote_only_sends_work_from_home(payload: dict[str, Any]) -> None:
    route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(200, json=payload))
    _source().fetch(_cfg(remote_only=True))
    assert route.calls[0].request.url.params["work_from_home"] == "true"


@respx.mock
def test_retry_on_429_then_success(payload: dict[str, Any]) -> None:
    route = respx.get(SEARCH_URL).mock(
        side_effect=[
            httpx.Response(429),
            httpx.Response(503),
            httpx.Response(200, json=payload, headers={"x-ratelimit-requests-remaining": "150"}),
        ]
    )
    source = _source()
    jobs = source.fetch(_cfg())
    assert route.call_count == 3
    assert source.requests_made == 3
    assert source.quota_remaining == 150
    assert len(jobs) == 4


@respx.mock
def test_failed_query_is_logged_and_skipped(payload: dict[str, Any]) -> None:
    respx.get(SEARCH_URL, params={"query": "AI Engineer"}).mock(return_value=httpx.Response(429))
    respx.get(SEARCH_URL, params={"query": "Data Scientist"}).mock(return_value=httpx.Response(200, json=payload))
    source = JSearchSource("k", client=httpx.Client(), wait=wait_none(), max_attempts=3)
    jobs = source.fetch(_cfg(queries=["AI Engineer", "Data Scientist"]))
    assert len(jobs) == 4
    assert source.requests_made == 3 + 1


@respx.mock
def test_timeout_is_retried(payload: dict[str, Any]) -> None:
    route = respx.get(SEARCH_URL).mock(
        side_effect=[httpx.ReadTimeout("slow"), httpx.Response(200, json=payload)]
    )
    source = _source()
    assert len(source.fetch(_cfg())) == 4
    assert route.call_count == 2 and source.requests_made == 2


@respx.mock
def test_client_error_is_not_retried() -> None:
    route = respx.get(SEARCH_URL).mock(return_value=httpx.Response(403, json={"message": "not subscribed"}))
    source = _source()
    assert source.fetch(_cfg()) == []
    assert route.call_count == 1


@respx.mock
def test_pagination_follows_cursor(payload: dict[str, Any]) -> None:
    page1 = json.loads(json.dumps(payload))
    page1["data"]["cursor"] = "NEXT"
    route = respx.get(SEARCH_URL).mock(
        side_effect=[httpx.Response(200, json=page1), httpx.Response(200, json=payload)]
    )
    source = _source()
    jobs = source.fetch(_cfg(pages_per_query=3))
    assert route.call_count == 2  # cursor None na 2ª página encerra antes da 3ª
    assert route.calls[1].request.url.params["cursor"] == "NEXT"
    assert "cursor" not in route.calls[0].request.url.params
    assert len(jobs) == 8
