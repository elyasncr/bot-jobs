from pathlib import Path

import pytest
from helpers import ScriptedScorer, llm_output, make_job
from typer.testing import CliRunner

from vagas_bot import evaluation
from vagas_bot.__main__ import app
from vagas_bot.config import Settings, load_settings
from vagas_bot.eval_report import render_report
from vagas_bot.evaluation import (
    JobMeta,
    ModelRun,
    Trial,
    ensure_label_entries,
    evaluate_model,
    load_eval_jobs,
    load_labels,
    load_results,
    pick_diverse,
    rankdata,
    results_payload,
    save_eval_jobs,
    save_results,
    spearman,
    summarize,
)
from vagas_bot.models import Job, PJStatus, Prefs
from vagas_bot.scoring.ranker import weighted_total

PREFS = Prefs(modalities=["remote"], hybrid_allowed_cities=[])
runner = CliRunner()


def _jobs(n: int) -> list[Job]:
    return [make_job(title=f"AI Engineer {i}", company=f"Empresa {i}") for i in range(n)]


# --- estatística ---


def test_rankdata_averages_ties() -> None:
    assert rankdata([10, 20, 20, 30]).tolist() == [1.0, 2.5, 2.5, 4.0]


def test_spearman() -> None:
    assert spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert spearman([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)
    assert spearman([1, 2], [1, 2]) is None  # poucos pares
    assert spearman([1, 2, 3], [5, 5, 5]) is None  # lado constante


# --- snapshots e labels ---


def test_snapshots_roundtrip_without_scores(tmp_path: Path) -> None:
    jobs = [j.model_copy(update={"embedding_score": 0.7}) for j in _jobs(3)]
    assert save_eval_jobs(jobs, tmp_path) == 3
    assert save_eval_jobs(jobs, tmp_path) == 0  # não sobrescreve
    loaded = load_eval_jobs(tmp_path)
    assert {j.id for j in loaded} == {j.id for j in jobs}
    assert all(j.embedding_score is None and j.score is None for j in loaded)


def test_pick_diverse_round_robin() -> None:
    jobs = _jobs(5)
    groups = {jobs[0].id: "a", jobs[1].id: "a", jobs[2].id: "a", jobs[3].id: "b", jobs[4].id: "c"}
    picked = pick_diverse(jobs, 3, key=lambda j: groups[j.id])
    assert [groups[j.id] for j in picked] == ["a", "b", "c"]


def test_label_entries_keep_existing_scores(tmp_path: Path) -> None:
    path = tmp_path / "labels.yaml"
    jobs = _jobs(2)
    assert ensure_label_entries(path, jobs[:1]) == 1
    text = path.read_text(encoding="utf-8").replace("score:\n", "score: 80\n", 1)
    path.write_text(text, encoding="utf-8")

    assert ensure_label_entries(path, jobs) == 1  # só a nova
    assert load_labels(path) == {jobs[0].id: 80}  # vazias não contam


def test_load_labels_ignores_invalid(tmp_path: Path) -> None:
    path = tmp_path / "labels.yaml"
    path.write_text('a: {score: 70}\nb: {score: 150}\nc: {score: "x"}\nd: 5\n', encoding="utf-8")
    assert load_labels(path) == {"a": 70}


# --- execução e métricas ---


def test_evaluate_model_runs_and_counts_invalid() -> None:
    jobs = _jobs(2)
    scorer = ScriptedScorer("fake/a", [99, 80, 60, None, 62])  # aquecimento, r1 j0, r1 j1, r2 j0 (falha), r2 j1
    run = evaluate_model(scorer, jobs, "cv", PREFS, runs=2)
    assert run.available and run.load_s is not None
    assert [(t.run, t.total) for t in run.trials] == [(1, 80), (1, 60), (2, None), (2, 62)]
    failed = run.trials[2]
    assert failed.error and failed.invalid == 2 and failed.calls == 2


def test_evaluate_model_unavailable() -> None:
    run = evaluate_model(ScriptedScorer("fake/x", [], down=True), _jobs(2), "cv", PREFS, runs=2)
    assert not run.available and "ollama pull" in (run.error or "")
    assert run.trials == []


def test_evaluate_model_reports_progress() -> None:
    seen: list[tuple[int, int]] = []
    evaluate_model(ScriptedScorer("fake/a", [50] * 5), _jobs(2), "cv", PREFS, runs=2,
                   on_progress=lambda done, total: seen.append((done, total)))
    assert seen == [(1, 4), (2, 4), (3, 4), (4, 4)]


def test_run_models_reports_progress_per_model(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings(project_dir / "config.yaml")
    monkeypatch.setattr(evaluation, "gpu_memory_used_gb", lambda: None)
    monkeypatch.setattr(evaluation, "loaded_vram_gb", lambda host, model: None)
    monkeypatch.setattr(evaluation, "unload_model", lambda host, model: None)
    seen: list[tuple[str, int, int]] = []
    evaluation.run_models(
        settings, ["a:1b", "b:1b"], _jobs(1), "cv", PREFS, runs=1,
        make_scorer=lambda s, m: ScriptedScorer(f"ollama/{m}", [50, 50], down=m == "b:1b"),
        on_progress=lambda model, done, total: seen.append((model, done, total)),
    )
    # início do modelo (0), 1 tentativa, fechamento; b:1b indisponível: início + concluído
    assert seen == [("a:1b", 0, 1), ("a:1b", 1, 1), ("a:1b", 1, 1), ("b:1b", 0, 1), ("b:1b", 1, 1)]


def test_run_models_unloads_when_evaluation_raises(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    settings = load_settings(project_dir / "config.yaml")
    monkeypatch.setattr(evaluation, "gpu_memory_used_gb", lambda: None)
    monkeypatch.setattr(evaluation, "loaded_vram_gb", lambda host, model: None)
    unloaded: list[str] = []
    monkeypatch.setattr(evaluation, "unload_model", lambda host, model: unloaded.append(model))

    def boom(model: str, done: int, total: int) -> None:
        if done == 1:  # primeiro evento por tentativa
            raise RuntimeError("cancelado")

    with pytest.raises(RuntimeError, match="cancelado"):
        evaluation.run_models(
            settings, ["a:1b"], _jobs(1), "cv", PREFS, runs=1,
            make_scorer=lambda s, m: ScriptedScorer(f"ollama/{m}", [50, 50]), on_progress=boom,
        )
    assert unloaded == ["a:1b"]


def test_summarize_metrics() -> None:
    jobs = [make_job(title="AI Engineer A", description="Contrato PJ."),
            make_job(title="AI Engineer B", description="Sem nada sobre contrato.")]
    a, b = jobs[0].id, jobs[1].id
    clt = llm_output(pj_status=PJStatus.CLT)
    run = ModelRun(model="fake/m", trials=[
        Trial(a, 1, 2.0, llm_output(technical=80)),
        Trial(a, 2, 4.0, llm_output(technical=90)),
        Trial(b, 1, 3.0, clt),
        Trial(b, 2, 3.0, None, error="JSON inválido", calls=2, invalid=2),
    ])
    metas = {j.id: JobMeta.from_job(j) for j in jobs}
    s = summarize(run, metas, labels={a: 90, b: 20})

    assert (s.ok, s.failed, s.calls, s.invalid) == (3, 1, 5, 2)
    assert s.mean_s == pytest.approx(3.0)
    diff = weighted_total(llm_output(technical=90)) - weighted_total(llm_output(technical=80))
    assert s.max_diff == diff and s.mean_abs_diff == pytest.approx(diff)
    assert s.clt_answers == 1 and s.clt_without_evidence == 1
    assert s.pj_consistency == pytest.approx(1.0)  # só a vaga A tem 2 rodadas ok
    assert s.n_gold == 2 and s.spearman_gold is None  # 2 pares é pouco


def test_results_roundtrip(tmp_path: Path) -> None:
    job = make_job()
    run = ModelRun(model="fake/m", load_s=10.0, vram_gb=6.1, trials=[Trial(job.id, 1, 2.5, llm_output())])
    path = save_results(tmp_path, results_payload([run], [JobMeta.from_job(job)], {"runs": 1}))
    runs, metas, meta = load_results(path)
    assert runs[0].trials[0].total == run.trials[0].total
    assert metas[0].title == job.title and meta == {"runs": 1}


def test_report_has_tables_and_reading() -> None:
    jobs = _jobs(6)
    labels = {j.id: 10 * i for i, j in enumerate(jobs)}
    good = ModelRun(model="fake/bom", trials=[Trial(j.id, r, 2.0, llm_output(technical=10 * i))
                                              for r in (1, 2) for i, j in enumerate(jobs)])
    down = ModelRun(model="fake/fora", available=False, error="não encontrado")
    metas = [JobMeta.from_job(j) for j in jobs]
    by_id = {m.id: m for m in metas}
    summaries = [summarize(r, by_id, labels) for r in (good, down)]
    report = render_report([good, down], summaries, metas, labels, {"runs": 2, "date": "2026-11-09"})

    assert "| fake/bom |" in report and "indisponível" in report
    assert "Sugestão de padrão: fake/bom" in report
    assert "Fora da disputa" in report and "fake/fora" in report


# --- CLI ---


@pytest.fixture
def eval_project(project_dir: Path) -> Settings:
    settings = load_settings(project_dir / "config.yaml")
    save_eval_jobs(_jobs(3), settings.eval_dir / "jobs")
    return settings


def test_cli_eval_models_and_report(eval_project: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    made: list[str] = []

    def fake_scorer(settings: Settings, model: str) -> ScriptedScorer:
        made.append(model)
        return ScriptedScorer(f"ollama/{model}", [70] * 10, down=model == "ausente:1b")

    monkeypatch.setattr(evaluation, "ollama_scorer_for", fake_scorer)
    monkeypatch.setattr(evaluation, "loaded_vram_gb", lambda host, model: 5.5)
    monkeypatch.setattr(evaluation, "gpu_memory_used_gb", lambda: None)  # sem nvidia-smi → usa ollama ps
    monkeypatch.setattr(evaluation, "unload_model", lambda host, model: None)
    config = str(eval_project.root / "config.yaml")

    result = runner.invoke(app, ["eval-models", "m1:7b", "ausente:1b", "--runs", "2", "--config", config])
    assert result.exit_code == 0, result.output
    assert made == ["m1:7b", "ausente:1b"]
    report = (eval_project.root / "eval_report.md").read_text(encoding="utf-8")
    assert "ollama/m1:7b" in report and "5.5 GB" in report and "indisponível" in report
    assert len(list((eval_project.eval_dir / "results").glob("eval_*.json"))) == 1

    (eval_project.root / "eval_report.md").unlink()
    again = runner.invoke(app, ["eval-report", "--config", config])
    assert again.exit_code == 0, again.output
    assert (eval_project.root / "eval_report.md").is_file()


def test_cli_eval_models_without_snapshots(project_dir: Path) -> None:
    result = runner.invoke(app, ["eval-models", "--config", str(project_dir / "config.yaml")])
    assert result.exit_code == 1
    assert "eval-snapshot" in result.output


def test_vram_delta() -> None:
    assert evaluation._vram_delta(1.9, 11.4) == 9.5
    assert evaluation._vram_delta(None, 11.4) is None
    assert evaluation._vram_delta(5.0, 4.0) is None


def test_set_label_keeps_other_entries_and_comments(tmp_path: Path) -> None:
    path = tmp_path / "labels.yaml"
    jobs = _jobs(2)
    ensure_label_entries(path, jobs)
    evaluation.set_label(path, jobs[1].id, jobs[1].title, jobs[1].company, 65, note="stack ok, sênior demais")
    evaluation.set_label(path, "novo", "ML Eng", "ACME", 40)
    assert load_labels(path) == {jobs[1].id: 65, "novo": 40}
    text = path.read_text(encoding="utf-8")
    assert f"# {jobs[0].title} · {jobs[0].company}" in text and "sênior demais" in text


def test_remove_label_keeps_others(tmp_path: Path) -> None:
    path = tmp_path / "labels.yaml"
    jobs = _jobs(2)
    ensure_label_entries(path, jobs)
    evaluation.set_label(path, jobs[0].id, jobs[0].title, jobs[0].company, 70)
    assert evaluation.remove_label(path, jobs[0].id) is True
    assert load_labels(path) == {}
    text = path.read_text(encoding="utf-8")
    assert jobs[0].id not in text and f"# {jobs[1].title} · {jobs[1].company}" in text
    assert evaluation.remove_label(path, "nao-existe") is False
