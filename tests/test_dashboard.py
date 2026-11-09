import json
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from helpers import llm_output, make_job

from vagas_bot import evaluation
from vagas_bot.archive import append_archive, archive_records
from vagas_bot.config import FiltersConfig, Settings, load_settings
from vagas_bot.dashboard import data
from vagas_bot.dashboard.data import DashboardError
from vagas_bot.evaluation import JobMeta, ModelRun, Trial
from vagas_bot.models import Job
from vagas_bot.scoring.llm_stage import to_score_result

CFG = FiltersConfig(modalities=["remote"], exclude_title_keywords=["junior"])


@pytest.fixture
def settings(project_dir: Path) -> Settings:
    return load_settings(project_dir / "config.yaml")


def _scored(job: Job, technical: int = 80) -> Job:
    out = llm_output(technical=technical, strengths=["RAG"], gaps=["Go"], summary="Boa.")
    return job.model_copy(update={"score": to_score_result(out, "ollama/x", 2.0), "embedding_score": 0.7})


def _archive(settings: Settings, day: date, after_dedupe: list[Job], processed: list[Job], emailed: set[str]) -> None:
    append_archive(settings.jobs_archive_path, archive_records(after_dedupe, processed, emailed, CFG, day))


def _write_history(settings: Settings, records: list[dict[str, Any]]) -> None:
    settings.history_path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")


# --- job_rows ---


def test_job_rows_from_archive(settings: Settings) -> None:
    a, b, junior = make_job(title="AI A"), make_job(title="AI B"), make_job(title="AI Junior")
    _archive(settings, date(2026, 11, 9), [a, b, junior], [_scored(a), b.model_copy(update={"embedding_score": 0.5})],
             {a.id})
    rows = {r["title"]: r for r in data.job_rows(settings)}

    first = rows["AI A"]
    assert first["stage"] == "emailed" and first["total"] == first["total"] and not first["is_estimate"]
    assert first["scores"]["technical"] == 80 and first["strengths"] == ["RAG"] and first["summary"] == "Boa."
    assert first["llm_model"] == "ollama/x" and first["modality"] == "remote" and first["my_score"] is None
    assert rows["AI B"]["is_estimate"] and rows["AI B"]["total"] is not None and rows["AI B"]["scores"] is None
    assert rows["AI Junior"]["stage"] == "filtered" and rows["AI Junior"]["filter_reason"] == "title"
    assert rows["AI Junior"]["total"] is None


def test_job_rows_latest_version_wins_and_order(settings: Settings) -> None:
    job = make_job(title="AI A")
    other = make_job(title="AI Z")
    _archive(settings, date(2026, 11, 9), [job], [job], set())
    _archive(settings, date(2026, 11, 10), [job, other], [_scored(job, 90), _scored(other, 10)], {job.id})
    rows = data.job_rows(settings)
    assert [r["title"] for r in rows] == ["AI A", "AI Z"]  # mesma data: nota maior primeiro
    assert rows[0]["run_date"] == "2026-11-10" and rows[0]["stage"] == "emailed"


def test_job_rows_backfill_history_and_benchmark(settings: Settings) -> None:
    _write_history(settings, [{
        "date": "2026-11-08", "id": "h1", "title": "ML Eng", "company": "ACME",
        "job_text": "ML Eng\nACME\nDescrição antiga", "embedding_score": 0.6, "embedder": "ollama/bge-m3",
        "technical": 70, "seniority": 60, "domain": 50, "modality_contract": 40, "language": 30,
        "total": 60, "pj_status": "uncertain", "llm_model": "ollama/x",
    }])
    bench = make_job(title="AI Bench", company="B")
    evaluation.save_eval_jobs([bench], settings.eval_dir / "jobs")
    evaluation.set_label(settings.eval_dir / "labels.yaml", bench.id, bench.title, bench.company, 75, "ok")

    rows = {r["id"]: r for r in data.job_rows(settings)}
    hist = rows["h1"]
    assert hist["stage"] == "history" and hist["description"] == "Descrição antiga" and hist["total"] == 60
    assert hist["scores"]["technical"] == 70 and hist["run_date"] == "2026-11-08"
    b = rows[bench.id]
    assert b["stage"] == "benchmark" and b["total"] is None and b["my_score"] == 75 and b["my_note"] == "ok"


def test_job_rows_empty(settings: Settings) -> None:
    assert data.job_rows(settings) == []


# --- benchmark ---


def _save_run(settings: Settings, name_time: str, jobs: list[Job]) -> Path:
    from datetime import datetime

    runs = [ModelRun(model="ollama/a", load_s=5, vram_gb=6.0,
                     trials=[Trial(j.id, r, 2.0 + i, llm_output(technical=20 * i)) for r in (1, 2)
                             for i, j in enumerate(jobs)])]
    payload = evaluation.results_payload(runs, [JobMeta.from_job(j) for j in jobs], {"runs": 2, "date": name_time})
    return evaluation.save_results(settings.eval_dir / "results", payload, datetime.fromisoformat(name_time))


def test_benchmark_runs_and_payload(settings: Settings) -> None:
    jobs = [make_job(title=f"AI {i}") for i in range(4)]
    _save_run(settings, "2026-11-08T10:00:00", jobs)
    latest = _save_run(settings, "2026-11-09T10:00:00", jobs)
    for i, job in enumerate(jobs):
        evaluation.set_label(settings.eval_dir / "labels.yaml", job.id, job.title, job.company, 10 * i)

    runs = data.benchmark_runs(settings)
    assert [r["file"] for r in runs] == [latest.name, "eval_20261108_100000.json"]
    assert runs[0]["models"] == ["ollama/a"] and runs[0]["jobs"] == 4

    payload = data.benchmark_payload(settings, None)
    summary = payload["summaries"][0]
    assert summary["model"] == "ollama/a" and summary["spearman_gold"] == pytest.approx(1.0)
    assert "mean_totals" not in summary and "invalid_rate" in summary
    assert payload["reading"] and payload["meta"]["date"] == "2026-11-09T10:00:00"
    first = payload["jobs"][0]
    assert first["my_score"] == 0 and len(first["models"]["ollama/a"]["totals"]) == 2


@pytest.mark.parametrize("run", ["../labels.yaml", "x.json", "eval_nao_existe.json"])
def test_benchmark_rejects_bad_run(settings: Settings, run: str) -> None:
    with pytest.raises(DashboardError) as exc:
        data.benchmark_payload(settings, run)
    assert exc.value.status == 404


def test_benchmark_without_results(settings: Settings) -> None:
    assert data.benchmark_runs(settings) == []
    with pytest.raises(DashboardError):
        data.benchmark_payload(settings, None)


# --- labels ---


def test_save_label_from_archive_creates_snapshot(settings: Settings) -> None:
    job = make_job(title="AI A")
    _archive(settings, date(2026, 11, 9), [job], [job], set())
    assert data.save_label(settings, job.id, {"score": 80, "note": "boa"}) == {
        "id": job.id, "my_score": 80, "my_note": "boa"}
    assert evaluation.load_labels(settings.eval_dir / "labels.yaml") == {job.id: 80}
    assert [j.id for j in evaluation.load_eval_jobs(settings.eval_dir / "jobs")] == [job.id]

    assert data.save_label(settings, job.id, {"score": None})["my_score"] is None
    assert evaluation.load_labels(settings.eval_dir / "labels.yaml") == {}


@pytest.mark.parametrize("body", [{"score": 101}, {"score": -1}, {"score": "80"}, {"score": 7.5}, {}, []])
def test_save_label_validates(settings: Settings, body: Any) -> None:
    job = make_job()
    _archive(settings, date(2026, 11, 9), [job], [job], set())
    with pytest.raises(DashboardError) as exc:
        data.save_label(settings, job.id, body)
    assert exc.value.status == 400


def test_save_label_unknown_job(settings: Settings) -> None:
    with pytest.raises(DashboardError) as exc:
        data.save_label(settings, "nao-existe", {"score": 50})
    assert exc.value.status == 404


# --- servidor HTTP ---

import http.client  # noqa: E402
import threading  # noqa: E402
from collections.abc import Iterator  # noqa: E402
from urllib.parse import quote  # noqa: E402

from vagas_bot.dashboard.server import find_dist, make_server  # noqa: E402


@pytest.fixture
def dist(settings: Settings) -> Path:
    folder = settings.root / "dashboard" / "dist" / "dashboard" / "browser"
    folder.mkdir(parents=True)
    (folder / "index.html").write_text("<html>app</html>", encoding="utf-8")
    (folder / "main-ABC.js").write_text("console.log(1)", encoding="utf-8")
    return folder


@pytest.fixture
def server(settings: Settings, dist: Path) -> Iterator[tuple[str, int]]:
    httpd = make_server(settings, dist, port=0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[0], httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def _request(server: tuple[str, int], method: str, path: str, body: Any = None) -> tuple[int, str, bytes]:
    conn = http.client.HTTPConnection(*server, timeout=10)
    payload = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
    conn.request(method, path, body=payload, headers={"Content-Type": "application/json"})
    resp = conn.getresponse()
    data_ = resp.read()
    conn.close()
    return resp.status, resp.getheader("Content-Type") or "", data_


def test_find_dist(settings: Settings, dist: Path) -> None:
    assert find_dist(settings.root) == dist
    assert find_dist(settings.root / "outro") is None


def test_server_api_routes(server: tuple[str, int], settings: Settings) -> None:
    job = make_job(title="AI A")
    _archive(settings, date(2026, 11, 9), [job], [job], set())

    status, ctype, body = _request(server, "GET", "/api/jobs")
    assert status == 200 and ctype.startswith("application/json")
    assert json.loads(body)[0]["title"] == "AI A"

    assert _request(server, "GET", "/api/benchmark/runs")[2] == b"[]"
    status, _, body = _request(server, "GET", "/api/benchmark?run=../labels.yaml")
    assert status == 404 and "error" in json.loads(body)
    assert _request(server, "GET", "/api/nada")[0] == 404

    path = "/api/labels/" + quote(job.id, safe="")
    status, _, body = _request(server, "PUT", path, {"score": 77, "note": "ok"})
    assert status == 200 and json.loads(body)["my_score"] == 77
    assert _request(server, "PUT", path, {"score": 300})[0] == 400
    assert _request(server, "PUT", path, b"{nao e json")[0] == 400
    assert _request(server, "PUT", "/api/labels/" + quote("x/y", safe=""), {"score": 1})[0] == 404


def test_server_static_and_spa_fallback(server: tuple[str, int]) -> None:
    status, ctype, body = _request(server, "GET", "/")
    assert status == 200 and body == b"<html>app</html>" and ctype.startswith("text/html")
    assert _request(server, "GET", "/vagas?q=ai")[2] == b"<html>app</html>"
    status, ctype, body = _request(server, "GET", "/main-ABC.js")
    assert status == 200 and "javascript" in ctype and body == b"console.log(1)"
    assert _request(server, "GET", "/nao-existe.js")[0] == 404


@pytest.mark.parametrize("path", ["/../../config.yaml", "/%2e%2e/%2e%2e/config.yaml", "/..%5c..%5cconfig.yaml"])
def test_server_blocks_path_traversal(server: tuple[str, int], path: str) -> None:
    status, _, body = _request(server, "GET", path)
    assert b"search:" not in body  # conteúdo do config.yaml nunca sai
    assert status in (200, 404)


def test_cli_dashboard_without_build(project_dir: Path) -> None:
    from typer.testing import CliRunner

    from vagas_bot.__main__ import app

    result = CliRunner().invoke(app, ["dashboard", "--no-browser", "--config", str(project_dir / "config.yaml")])
    assert result.exit_code == 1
    assert "npm ci && npm run build" in result.output
