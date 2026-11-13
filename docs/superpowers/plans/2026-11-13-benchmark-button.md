# Botão "Rodar benchmark" — plano de implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Um botão na tela Benchmark que inclui as vagas novas do bot diário no conjunto do benchmark, roda os modelos escolhidos em segundo plano e mostra o progresso até exibir a rodada nova.

**Architecture:** O miolo dos comandos `eval-snapshot --from-archive`/`eval-models` sai do `__main__.py` para `vagas_bot/eval_runner.py`, usado pela linha de comando e por um `BenchmarkJob` (thread única no servidor do dashboard). A API ganha `GET /api/benchmark/models`, `POST /api/benchmark/run` e `GET /api/benchmark/status`; a tela Angular ganha o componente `RunBenchmark` (botão + painel + faixa de progresso, consultando o status a cada 3 s).

**Tech Stack:** Python 3.12 (stdlib `http.server`, `threading`), pytest; Angular 22 (signals, standalone, OnPush), Vitest.

**Spec:** `docs/superpowers/specs/2026-11-13-benchmark-button-design.md`

**Regras do repositório:**
- Commits **sem** linha `Co-Authored-By` nem qualquer atribuição ao Claude. Antes de cada commit, conferir que não entram `.env`, `data/cv.md` ou segredos.
- Usar `git add` com caminhos explícitos: a árvore tem mudanças do tema claro/escuro (`dashboard/src/app/app.ts`, `index.html`, `styles.css`, `core/theme.service*.ts`) que **não** fazem parte deste plano.
- Comandos Python a partir da raiz: `uv run pytest ...`. Frontend a partir de `dashboard/`: `npm test`, `npm run build`.
- Base atual: `uv run pytest -q` → 258 passed; `npm test` → 35 passed.

---

## Mapa de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `src/vagas_bot/evaluation.py` (mod.) | `on_progress` opcional em `evaluate_model` e `run_models` |
| `src/vagas_bot/ollama_utils.py` (mod.) | `OllamaModel` + `list_models` (nome e família) |
| `src/vagas_bot/eval_runner.py` (novo) | incluir vagas do arquivo, contar pendentes, rodar benchmark, gravar relatório |
| `src/vagas_bot/__main__.py` (mod.) | `eval-snapshot`, `eval-models`, `eval-report` passam a usar `eval_runner` |
| `src/vagas_bot/dashboard/benchmark_job.py` (novo) | uma rodada por vez numa thread, com estado consultável |
| `src/vagas_bot/dashboard/data.py` (mod.) | `benchmark_models`, `validate_benchmark_models` |
| `src/vagas_bot/dashboard/server.py` (mod.) | rotas GET novas, `do_POST`, `BenchmarkJob` compartilhado |
| `tests/helpers.py` (mod.) | `ScriptedScorer` passa a morar aqui (usado por dois arquivos de teste) |
| `tests/test_evaluation.py`, `tests/test_ollama_utils.py`, `tests/test_dashboard.py` (mod.) | testes novos |
| `tests/test_eval_runner.py`, `tests/test_benchmark_job.py` (novos) | testes novos |
| `dashboard/src/app/core/models.ts`, `api.service.ts`, `api.service.spec.ts` (mod.) | tipos e chamadas novas |
| `dashboard/src/app/benchmark/run-progress.ts` + `.spec.ts` (novos) | funções puras do painel |
| `dashboard/src/app/benchmark/run-benchmark.ts` (novo) | componente botão + painel + faixa |
| `dashboard/src/app/benchmark/benchmark-page.ts` (mod.) | encaixa o componente e recarrega ao terminar |
| `README.md` (mod.) | documenta o botão |

---

### Task 1: Progresso em `evaluate_model` e `run_models`

**Files:**
- Modify: `tests/helpers.py` (adicionar `ScriptedScorer` no fim)
- Modify: `tests/test_evaluation.py` (remover a classe local, importar de `helpers`, testes novos)
- Modify: `src/vagas_bot/evaluation.py:230-312`

- [ ] **Step 1: Mover `ScriptedScorer` para `tests/helpers.py`**

Recortar a classe `ScriptedScorer` de `tests/test_evaluation.py` (linhas 36-56) e colar no fim de `tests/helpers.py`, sem mudanças. `helpers.py` já importa `Job`, `LLMScoreOutput`, `Prefs`, `LLMInvalidOutput`, `LLMUnavailable` e define `llm_output`. Em `tests/test_evaluation.py`, trocar a linha de import:

```python
from helpers import ScriptedScorer, llm_output, make_job
```

- [ ] **Step 2: Escrever os testes que falham** (em `tests/test_evaluation.py`, logo após `test_evaluate_model_unavailable`)

```python
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
    # a:1b: 1 tentativa + o fechamento do modelo; b:1b indisponível conta como concluído
    assert seen == [("a:1b", 1, 1), ("a:1b", 1, 1), ("b:1b", 1, 1)]
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `uv run pytest tests/test_evaluation.py -q -k progress`
Expected: FAIL com `TypeError: evaluate_model() got an unexpected keyword argument 'on_progress'`

- [ ] **Step 4: Implementar**

Em `src/vagas_bot/evaluation.py`, `evaluate_model`:

```python
def evaluate_model(
    scorer: LLMScorer, jobs: list[Job], cv_md: str, prefs: Prefs, runs: int, warmup: bool = True,
    on_progress: Callable[[int, int], None] | None = None,
) -> ModelRun:
```

e, dentro do laço, logo depois do `log.info("  %s [%d/%d] rodada %d: ...")`:

```python
            if on_progress:
                on_progress(done, total_calls)
```

`run_models`:

```python
def run_models(
    settings: Settings,
    models: list[str],
    jobs: list[Job],
    cv_md: str,
    prefs: Prefs,
    runs: int,
    warmup: bool = True,
    make_scorer: Callable[[Settings, str], LLMScorer] = ollama_scorer_for,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> list[ModelRun]:
    """One model at a time; each is unloaded at the end so the next gets the whole GPU.

    on_progress(model, done, total) after each attempt, plus once with done=total when the model ends
    (also when it is unavailable), so a progress bar never gets stuck.
    """
    results = []
    total = runs * len(jobs)
    for model in models:
        log.info("Avaliando %s: %d vagas × %d rodadas.", model, len(jobs), runs)
        scorer = make_scorer(settings, model)
        baseline = gpu_memory_used_gb()
        step = (lambda done, tot, m=model: on_progress(m, done, tot)) if on_progress else None
        run = evaluate_model(scorer, jobs, cv_md, prefs, runs, warmup, on_progress=step)
        if run.available or run.trials:
            run.vram_gb = _vram_delta(baseline, gpu_memory_used_gb()) or loaded_vram_gb(settings.ollama_host, model)
            unload_model(settings.ollama_host, model)
        if on_progress:
            on_progress(model, total, total)
        results.append(run)
    return results
```

(`Callable` já é importado em `evaluation.py`; conferir com `grep -n "Callable" src/vagas_bot/evaluation.py`.)

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest tests/test_evaluation.py -q`
Expected: todos passam.

- [ ] **Step 6: Commit**

```bash
git add tests/helpers.py tests/test_evaluation.py src/vagas_bot/evaluation.py
git commit -m "feat: progresso por tentativa no eval-models"
```

---

### Task 2: `list_models` no `ollama_utils`

**Files:**
- Modify: `src/vagas_bot/ollama_utils.py`
- Modify: `tests/test_ollama_utils.py`

- [ ] **Step 1: Escrever o teste que falha** (fim de `tests/test_ollama_utils.py`; acrescentar `OllamaModel, list_models` ao import de `vagas_bot.ollama_utils`)

```python
class _FamilyClient:
    def __init__(self, **_: object) -> None:
        pass

    def list(self) -> SimpleNamespace:
        return SimpleNamespace(models=[
            SimpleNamespace(model="qwen3:14b", details=SimpleNamespace(family="qwen3")),
            SimpleNamespace(model="bge-m3:latest", details=SimpleNamespace(family="bert")),
            SimpleNamespace(model="sem-detalhes:1b", details=None),
        ])


def test_list_models_with_family(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ollama_utils.ollama, "Client", lambda **kw: _FamilyClient())
    assert list_models("http://x") == [
        OllamaModel("bge-m3:latest", "bert"),
        OllamaModel("qwen3:14b", "qwen3"),
        OllamaModel("sem-detalhes:1b", ""),
    ]


def test_list_models_down(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ollama_utils.ollama, "Client", lambda **kw: _FakeClient(down=True))
    with pytest.raises(OllamaUnavailable, match="ollama serve"):
        list_models("http://x")
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_ollama_utils.py -q`
Expected: FAIL com `ImportError: cannot import name 'OllamaModel'`

- [ ] **Step 3: Implementar** (`src/vagas_bot/ollama_utils.py`; `list_local_models` passa a reaproveitar `list_models`)

```python
import time
from dataclasses import dataclass

import ollama


class OllamaUnavailable(Exception):
    """Ollama server is down or unreachable."""


@dataclass(frozen=True)
class OllamaModel:
    name: str
    family: str  # ex.: "qwen3", "gemma4"; "bert" = modelo de embedding


def normalize_model_name(name: str) -> str:
    """Ollama implies ':latest' when no tag is given."""
    return name if ":" in name else f"{name}:latest"


def list_models(host: str, timeout_s: float = 5.0) -> list[OllamaModel]:
    """Installed models with their family, sorted by name."""
    client = ollama.Client(host=host, timeout=timeout_s)
    try:
        response = client.list()
    except ConnectionError as exc:
        raise OllamaUnavailable(f"Ollama não responde em {host}. Rode: ollama serve") from exc
    found = []
    for item in response.models:
        if item.model:
            details = getattr(item, "details", None)
            found.append(OllamaModel(item.model, (getattr(details, "family", None) or "") if details else ""))
    return sorted(found, key=lambda m: m.name)


def list_local_models(host: str, timeout_s: float = 5.0) -> set[str]:
    return {normalize_model_name(m.name) for m in list_models(host, timeout_s)}
```

(O resto do arquivo — `is_model_available`, `pull_hint`, `loaded_vram_gb`, `unload_model` — fica igual.)

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/test_ollama_utils.py -q`
Expected: todos passam (inclusive os antigos de `list_local_models`).

- [ ] **Step 5: Commit**

```bash
git add src/vagas_bot/ollama_utils.py tests/test_ollama_utils.py
git commit -m "feat: list_models do Ollama com a família de cada modelo"
```

---

### Task 3: `eval_runner.py` e linha de comando usando ele

**Files:**
- Create: `src/vagas_bot/eval_runner.py`
- Create: `tests/test_eval_runner.py`
- Modify: `src/vagas_bot/__main__.py` (imports no topo; `eval_snapshot` 132-162; `eval_models` 165-202; `eval_report` 205-217; remover `_write_report` 220-228)

- [ ] **Step 1: Escrever os testes que falham** (`tests/test_eval_runner.py`)

```python
from datetime import date
from pathlib import Path

import pytest
from helpers import ScriptedScorer, llm_output, make_job
from typer.testing import CliRunner

from vagas_bot import eval_runner, evaluation
from vagas_bot.__main__ import app
from vagas_bot.archive import append_archive, archive_records
from vagas_bot.config import FiltersConfig, Settings, load_settings
from vagas_bot.eval_runner import AddResult, EvalRunnerError
from vagas_bot.models import Job
from vagas_bot.scoring.llm_stage import to_score_result

CFG = FiltersConfig(modalities=["remote"], exclude_title_keywords=["junior"])
runner = CliRunner()


@pytest.fixture
def settings(project_dir: Path) -> Settings:
    return load_settings(project_dir / "config.yaml")


def _scored(job: Job, technical: int = 80) -> Job:
    return job.model_copy(update={"score": to_score_result(llm_output(technical=technical), "ollama/x", 2.0)})


def _archive(settings: Settings, after_dedupe: list[Job], processed: list[Job], emailed: set[str]) -> None:
    records = archive_records(after_dedupe, processed, emailed, CFG, date(2026, 11, 12))
    append_archive(settings.jobs_archive_path, records)


def _fake_ollama(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(evaluation, "ollama_scorer_for", lambda s, m: ScriptedScorer(f"ollama/{m}", [70] * 10))
    monkeypatch.setattr(evaluation, "loaded_vram_gb", lambda host, model: 5.5)
    monkeypatch.setattr(evaluation, "gpu_memory_used_gb", lambda: None)
    monkeypatch.setattr(evaluation, "unload_model", lambda host, model: None)


def test_add_archive_jobs_adds_only_new_evaluated(settings: Settings) -> None:
    old, new, junior = make_job(title="AI Old"), make_job(title="AI New"), make_job(title="AI Junior")
    _archive(settings, [old, new, junior], [_scored(old), _scored(new)], {old.id})  # junior: filtrada
    evaluation.save_eval_jobs([old], settings.eval_dir / "jobs")

    assert eval_runner.pending_archive_jobs(settings) == 1
    assert eval_runner.add_archive_jobs(settings) == AddResult(added=1, total=2, new_labels=2)
    assert eval_runner.pending_archive_jobs(settings) == 0
    assert {j.title for j in evaluation.load_eval_jobs(settings.eval_dir / "jobs")} == {"AI Old", "AI New"}


def test_add_archive_jobs_respects_n(settings: Settings) -> None:
    jobs = [make_job(title=f"AI {i}") for i in range(3)]
    _archive(settings, jobs, [_scored(j, 20 * i) for i, j in enumerate(jobs)], set())
    assert eval_runner.add_archive_jobs(settings, n=2).added == 2
    assert eval_runner.pending_archive_jobs(settings) == 1


def test_add_archive_jobs_without_archive(settings: Settings) -> None:
    assert eval_runner.pending_archive_jobs(settings) == 0
    assert eval_runner.add_archive_jobs(settings) == AddResult(added=0, total=0, new_labels=0)


def test_run_benchmark_saves_results_and_report(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    _fake_ollama(monkeypatch)
    evaluation.save_eval_jobs([make_job(title=f"AI {i}") for i in range(2)], settings.eval_dir / "jobs")
    seen: list[tuple[str, int, int]] = []

    path = eval_runner.run_benchmark(settings, ["m1:7b"], runs=1,
                                     on_progress=lambda m, d, t: seen.append((m, d, t)))

    assert path.is_file() and path.parent == settings.eval_dir / "results"
    assert evaluation.load_results(path)[2]["models"] == ["m1:7b"]
    assert "ollama/m1:7b" in (settings.root / "eval_report.md").read_text(encoding="utf-8")
    assert seen[-1] == ("m1:7b", 2, 2)


def test_run_benchmark_without_jobs(settings: Settings) -> None:
    with pytest.raises(EvalRunnerError, match="eval-snapshot"):
        eval_runner.run_benchmark(settings, ["m1:7b"])


def test_run_benchmark_without_cv(settings: Settings) -> None:
    evaluation.save_eval_jobs([make_job()], settings.eval_dir / "jobs")
    settings.cv_path.unlink()
    with pytest.raises(EvalRunnerError, match="cv.md"):
        eval_runner.run_benchmark(settings, ["m1:7b"])


def test_cli_eval_snapshot_from_archive(settings: Settings) -> None:
    job = make_job(title="AI A")
    _archive(settings, [job], [_scored(job)], set())
    result = runner.invoke(app, ["eval-snapshot", "--from-archive", "--config", str(settings.root / "config.yaml")])
    assert result.exit_code == 0, result.output
    assert "1 vagas novas salvas; 1 no total" in result.output
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_eval_runner.py -q`
Expected: FAIL com `ImportError: cannot import name 'eval_runner'`

- [ ] **Step 3: Criar `src/vagas_bot/eval_runner.py`**

```python
"""Benchmark steps shared by the CLI (eval-snapshot / eval-models / eval-report) and the dashboard button."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from vagas_bot import evaluation
from vagas_bot.archive import archived_jobs, load_archive
from vagas_bot.config import Settings
from vagas_bot.cv import CVError, load_cv
from vagas_bot.eval_report import render_report
from vagas_bot.models import Job
from vagas_bot.scoring.prompts import prefs_from_config

ARCHIVE_STAGES = {"evaluated", "emailed"}
NO_JOBS_MESSAGE = "Nenhuma vaga em data/eval/jobs/. Rode antes: python -m vagas_bot eval-snapshot"


class EvalRunnerError(Exception):
    """A precondition failed (no jobs, no CV); the message is ready for the user."""


@dataclass(frozen=True)
class AddResult:
    added: int  # vagas gravadas agora em data/eval/jobs/
    total: int  # vagas no conjunto depois de gravar
    new_labels: int  # entradas novas em labels.yaml


def _jobs_dir(settings: Settings) -> Path:
    return settings.eval_dir / "jobs"


def _new_archive_jobs(settings: Settings) -> list[Job]:
    """Evaluated/emailed jobs from data/jobs.jsonl not yet in the benchmark set, newest first."""
    have = {job.id for job in evaluation.load_eval_jobs(_jobs_dir(settings))}
    jobs = archived_jobs(load_archive(settings.jobs_archive_path), ARCHIVE_STAGES)
    return [job for job in reversed(jobs) if job.id not in have]


def pending_archive_jobs(settings: Settings) -> int:
    return len(_new_archive_jobs(settings))


def add_archive_jobs(settings: Settings, n: int | None = None) -> AddResult:
    """n=None: every new job (dashboard). A number: a diverse pick of n (CLI, by score band)."""
    candidates = _new_archive_jobs(settings)
    if n is not None:
        candidates = evaluation.pick_diverse(
            candidates, n, key=lambda j: str(j.score.total // 20) if j.score else "estimativa"
        )
    added = evaluation.save_eval_jobs(candidates, _jobs_dir(settings))
    all_jobs = evaluation.load_eval_jobs(_jobs_dir(settings))
    new_labels = evaluation.ensure_label_entries(settings.eval_dir / "labels.yaml", all_jobs)
    return AddResult(added=added, total=len(all_jobs), new_labels=new_labels)


def run_benchmark(
    settings: Settings,
    models: list[str],
    runs: int = 2,
    warmup: bool = True,
    limit: int | None = None,
    report_path: Path | None = None,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> Path:
    """Score the benchmark set with each model, save data/eval/results/eval_*.json and the report."""
    jobs = evaluation.load_eval_jobs(_jobs_dir(settings))[:limit]
    if not jobs:
        raise EvalRunnerError(NO_JOBS_MESSAGE)
    try:
        cv_md = load_cv(settings.cv_path)
    except CVError as exc:
        raise EvalRunnerError(str(exc)) from exc
    llm = settings.config.llm.ollama
    results = evaluation.run_models(
        settings, models, jobs, cv_md, prefs_from_config(settings.config.filters), runs, warmup,
        make_scorer=evaluation.ollama_scorer_for,  # lido na hora da chamada: os testes trocam esta função
        on_progress=on_progress,
    )
    meta = {
        "date": datetime.now().isoformat(timespec="seconds"),
        "runs": runs,
        "num_ctx": llm.num_ctx,
        "temperature": llm.temperature,
        "think": llm.think,
        "models": models,
    }
    payload = evaluation.results_payload(results, [evaluation.JobMeta.from_job(j) for j in jobs], meta)
    results_path = evaluation.save_results(settings.eval_dir / "results", payload)
    write_report(settings, results_path, report_path or settings.root / "eval_report.md")
    return results_path


def write_report(settings: Settings, results_path: Path, out: Path) -> None:
    runs, metas, meta = evaluation.load_results(results_path)
    labels = evaluation.load_labels(settings.eval_dir / "labels.yaml")
    by_id = {m.id: m for m in metas}
    summaries = [evaluation.summarize(r, by_id, labels) for r in runs]
    meta = meta | {"results_file": results_path.relative_to(settings.root).as_posix()
                   if results_path.is_relative_to(settings.root) else str(results_path)}
    out.write_text(render_report(runs, summaries, metas, labels, meta), encoding="utf-8")
```

- [ ] **Step 4: Rodar os testes de `eval_runner` (exceto o de CLI)**

Run: `uv run pytest tests/test_eval_runner.py -q -k "not cli"`
Expected: PASS

- [ ] **Step 5: Linha de comando passa a usar `eval_runner`** (`src/vagas_bot/__main__.py`)

Imports no topo: remover `from datetime import datetime` e `from vagas_bot.eval_report import render_report` (deixam de ser usados; `archived_jobs`/`load_archive` continuam, o comando `label` usa) e acrescentar:

```python
from vagas_bot import eval_runner, evaluation
```

(no lugar de `from vagas_bot import evaluation`).

Em `eval_snapshot`, trocar o corpo a partir de `jobs_dir = ...` por:

```python
    jobs_dir = settings.eval_dir / "jobs"
    if from_archive:
        result = eval_runner.add_archive_jobs(settings, n)
    else:
        if missing_env(settings, ["RAPIDAPI_KEY"]):
            console.print("[red]RAPIDAPI_KEY ausente[/] (ou use --from-archive).")
            raise typer.Exit(1)
        key = settings.secrets.rapidapi_key
        assert key is not None
        source = JSearchSource(key.get_secret_value())
        search = settings.config.search.model_copy(update={"date_posted": date_posted})
        jobs = apply_filters(dedupe(source.fetch(search), set()), settings.config.filters)
        picked = evaluation.pick_diverse(jobs, n, key=lambda j: source.origin_by_fingerprint.get(j.fingerprint, "?"))
        written = evaluation.save_eval_jobs(picked, jobs_dir)
        all_jobs = evaluation.load_eval_jobs(jobs_dir)
        added = evaluation.ensure_label_entries(settings.eval_dir / "labels.yaml", all_jobs)
        result = eval_runner.AddResult(added=written, total=len(all_jobs), new_labels=added)
    console.print(f"{result.added} vagas novas salvas; {result.total} no total em {jobs_dir}.")
    console.print(f"{result.new_labels} entradas novas em data/eval/labels.yaml (preencha score 0-100 para o Spearman).")
```

`eval_models` (assinatura igual; corpo novo):

```python
    """Compara modelos nas vagas de data/eval/jobs/ e gera eval_report.md."""
    settings = _load(config)
    setup_logging(settings.logs_dir)
    report = _resolve(settings, out)
    try:
        eval_runner.run_benchmark(settings, models or [settings.config.llm.ollama.model], runs=runs,
                                  warmup=warmup, limit=limit, report_path=report)
    except eval_runner.EvalRunnerError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1) from exc
    console.print(f"[green]Relatório:[/] {report}")
```

`eval_report`: trocar a última linha `_write_report(settings, path, _resolve(settings, out))` por:

```python
    report = _resolve(settings, out)
    eval_runner.write_report(settings, path, report)
    console.print(f"[green]Relatório:[/] {report}")
```

Apagar a função `_write_report`. Conferir que nada mais a usa: `grep -n "_write_report\|render_report\|datetime" src/vagas_bot/__main__.py` → só deve sobrar `ee.render_report` (embeddings).

- [ ] **Step 6: Rodar toda a suíte**

Run: `uv run pytest -q`
Expected: todos passam (258 antigos + os novos), inclusive `test_cli_eval_models_and_report` e `test_cli_eval_models_without_snapshots`.

- [ ] **Step 7: Commit**

```bash
git add src/vagas_bot/eval_runner.py src/vagas_bot/__main__.py tests/test_eval_runner.py
git commit -m "refactor: eval_runner com o miolo do eval-snapshot e do eval-models"
```

---

### Task 4: `BenchmarkJob` (uma rodada por vez, em thread)

**Files:**
- Create: `src/vagas_bot/dashboard/benchmark_job.py`
- Create: `tests/test_benchmark_job.py`

- [ ] **Step 1: Escrever os testes que falham** (`tests/test_benchmark_job.py`)

```python
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from vagas_bot.config import Settings, load_settings
from vagas_bot.dashboard.benchmark_job import BenchmarkJob
from vagas_bot.dashboard.data import DashboardError
from vagas_bot.eval_runner import AddResult, EvalRunnerError

Progress = Callable[[str, int, int], None]


@pytest.fixture
def settings(project_dir: Path) -> Settings:
    return load_settings(project_dir / "config.yaml")


def _add(_: Settings) -> AddResult:
    return AddResult(added=3, total=18, new_labels=3)


def test_runs_to_done_with_progress(settings: Settings) -> None:
    calls: list[list[str]] = []

    def fake_run(s: Settings, models: list[str], on_progress: Progress) -> Path:
        for model in models:
            on_progress(model, 1, 2)
            on_progress(model, 2, 2)
        calls.append(models)
        return Path("data/eval/results/eval_20261113_100000.json")

    job = BenchmarkJob(settings, add=_add, run=fake_run)
    assert job.status()["state"] == "idle"
    first = job.start(["a:1b", "b:2b"])
    assert first["state"] == "running" and first["model_count"] == 2 and first["started_at"]
    job.wait(5)

    status = job.status()
    assert status["state"] == "done" and status["result_file"] == "eval_20261113_100000.json"
    assert status["added"] == 3 and status["finished_at"] and status["error"] is None
    assert (status["current_model"], status["model_index"], status["done"], status["total"]) == ("b:2b", 2, 2, 2)
    assert calls == [["a:1b", "b:2b"]]


def test_second_start_conflicts_until_done(settings: Settings) -> None:
    release = threading.Event()

    def slow_run(s: Settings, models: list[str], on_progress: Progress) -> Path:
        release.wait(5)
        return Path("eval_20261113_100000.json")

    job = BenchmarkJob(settings, add=_add, run=slow_run)
    job.start(["a:1b"])
    with pytest.raises(DashboardError) as err:
        job.start(["a:1b"])
    assert err.value.status == 409
    release.set()
    job.wait(5)
    assert job.status()["state"] == "done"
    assert job.start(["a:1b"])["state"] == "running"  # depois de terminar, pode rodar de novo
    job.wait(5)


def test_failure_becomes_error_state(settings: Settings) -> None:
    def failing_run(s: Settings, models: list[str], on_progress: Progress) -> Path:
        raise EvalRunnerError("Nenhuma vaga em data/eval/jobs/.")

    job = BenchmarkJob(settings, add=_add, run=failing_run)
    job.start(["a:1b"])
    job.wait(5)
    status = job.status()
    assert status["state"] == "error" and status["error"] == "Nenhuma vaga em data/eval/jobs/."
    assert status["finished_at"]
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_benchmark_job.py -q`
Expected: FAIL com `ModuleNotFoundError: No module named 'vagas_bot.dashboard.benchmark_job'`

- [ ] **Step 3: Implementar** (`src/vagas_bot/dashboard/benchmark_job.py`)

```python
"""The dashboard's "Rodar benchmark" button: one run at a time, in a background thread.

State lives in memory only: if the dashboard restarts mid-run, the run is lost (results are only
written at the end, so nothing is left half-written on disk).
"""

import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from vagas_bot import eval_runner
from vagas_bot.config import Settings
from vagas_bot.dashboard.data import DashboardError
from vagas_bot.eval_runner import AddResult
from vagas_bot.log import get_logger

log = get_logger("dashboard")

AddFn = Callable[[Settings], AddResult]
RunFn = Callable[..., Path]  # (settings, models, on_progress=...) -> caminho do resultado


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _idle() -> dict[str, Any]:
    return {
        "state": "idle", "phase": None, "models": [], "current_model": None, "model_index": 0,
        "model_count": 0, "done": 0, "total": 0, "added": 0, "started_at": None, "finished_at": None,
        "result_file": None, "error": None,
    }


class BenchmarkJob:
    def __init__(self, settings: Settings, add: AddFn | None = None, run: RunFn | None = None) -> None:
        self._settings = settings
        self._add = add or eval_runner.add_archive_jobs
        self._run = run or eval_runner.run_benchmark
        self._lock = threading.Lock()
        self._state = _idle()
        self._thread: threading.Thread | None = None

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state, models=list(self._state["models"]))

    def start(self, models: list[str]) -> dict[str, Any]:
        with self._lock:
            if self._state["state"] == "running":
                raise DashboardError(409, "Já existe um benchmark rodando. Aguarde terminar.")
            self._state = _idle() | {
                "state": "running", "phase": "adding", "models": list(models), "model_count": len(models),
                "started_at": _now(),
            }
            self._thread = threading.Thread(target=self._work, args=(list(models),), name="benchmark", daemon=True)
            self._thread.start()
        return self.status()

    def wait(self, timeout: float | None = None) -> None:
        """Block until the current run ends (tests)."""
        if self._thread is not None:
            self._thread.join(timeout)

    def _work(self, models: list[str]) -> None:
        try:
            added = self._add(self._settings)
            self._update(phase="running", added=added.added)
            path = self._run(self._settings, models, on_progress=self._on_progress)
            self._update(state="done", phase=None, result_file=path.name, finished_at=_now())
        except Exception as exc:  # noqa: BLE001 — a tela recebe a mensagem em vez de uma rodada "rodando" para sempre
            log.exception("Benchmark iniciado pelo dashboard falhou")
            self._update(state="error", error=str(exc) or type(exc).__name__, finished_at=_now())

    def _on_progress(self, model: str, done: int, total: int) -> None:
        with self._lock:
            models = self._state["models"]
            index = models.index(model) + 1 if model in models else self._state["model_index"]
            self._state.update(current_model=model, model_index=index, done=done, total=total)

    def _update(self, **changes: Any) -> None:
        with self._lock:
            self._state.update(changes)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `uv run pytest tests/test_benchmark_job.py -q`
Expected: PASS (3 testes)

- [ ] **Step 5: Commit**

```bash
git add src/vagas_bot/dashboard/benchmark_job.py tests/test_benchmark_job.py
git commit -m "feat: BenchmarkJob roda o benchmark em segundo plano no dashboard"
```

---

### Task 5: API — modelos, iniciar e status

**Files:**
- Modify: `src/vagas_bot/dashboard/data.py` (imports; nova seção após `benchmark_payload`)
- Modify: `src/vagas_bot/dashboard/server.py` (`DashboardHandler.__init__`, `do_GET`, novo `do_POST`, `_api`, `make_server`)
- Modify: `tests/test_dashboard.py`

- [ ] **Step 1: Escrever os testes que falham** (fim de `tests/test_dashboard.py`)

```python
# --- botão Rodar benchmark ---

from datetime import datetime  # noqa: E402

from vagas_bot.dashboard.benchmark_job import BenchmarkJob  # noqa: E402
from vagas_bot.eval_runner import AddResult  # noqa: E402
from vagas_bot.ollama_utils import OllamaModel, OllamaUnavailable  # noqa: E402

INSTALLED = [
    OllamaModel("bge-m3:latest", "bert"),
    OllamaModel("gemma4:12b", "gemma4"),
    OllamaModel("gpt-oss:20b", "gpt-oss"),
    OllamaModel("qwen3.5:9b", "qwen35"),
]


def test_benchmark_models_without_previous_run(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data, "list_models", lambda host: INSTALLED)
    job = make_job(title="AI A")
    _archive(settings, date(2026, 11, 12), [job], [_scored(job)], set())

    result = data.benchmark_models(settings)

    assert [m["name"] for m in result["models"]] == ["gemma4:12b", "gpt-oss:20b", "qwen3.5:9b"]  # sem embedding
    by_name = {m["name"]: m for m in result["models"]}
    assert by_name["qwen3.5:9b"]["default"]  # sem rodada salva: o modelo do config.yaml
    assert not by_name["gemma4:12b"]["default"]
    assert by_name["gpt-oss:20b"]["warning"] and not by_name["gpt-oss:20b"]["default"]
    assert result["pending_jobs"] == 1 and result["total_jobs"] == 0


def test_benchmark_models_defaults_from_last_run(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data, "list_models", lambda host: INSTALLED)
    payload = evaluation.results_payload([], [], {"date": "2026-11-09T10:00:00",
                                                  "models": ["gemma4:12b", "gpt-oss:20b"]})
    evaluation.save_results(settings.eval_dir / "results", payload, datetime(2026, 11, 9, 10))

    by_name = {m["name"]: m for m in data.benchmark_models(settings)["models"]}
    assert by_name["gemma4:12b"]["default"]
    assert not by_name["gpt-oss:20b"]["default"]  # instável: nunca vem marcado
    assert not by_name["qwen3.5:9b"]["default"]


def test_benchmark_models_ollama_down(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    def down(host: str) -> list[OllamaModel]:
        raise OllamaUnavailable("Ollama não responde em http://x. Rode: ollama serve")

    monkeypatch.setattr(data, "list_models", down)
    with pytest.raises(DashboardError) as err:
        data.benchmark_models(settings)
    assert err.value.status == 503 and "Ollama" in err.value.message


@pytest.mark.parametrize("body", [None, [], {}, {"models": []}, {"models": "qwen3.5:9b"}, {"models": [1]},
                                  {"models": ["nao-instalado:1b"]}, {"models": ["bge-m3:latest"]}])
def test_validate_benchmark_models_rejects(settings: Settings, monkeypatch: pytest.MonkeyPatch, body: Any) -> None:
    monkeypatch.setattr(data, "list_models", lambda host: INSTALLED)
    with pytest.raises(DashboardError) as err:
        data.validate_benchmark_models(settings, body)
    assert err.value.status == 400


def test_validate_benchmark_models_dedupes(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(data, "list_models", lambda host: INSTALLED)
    body = {"models": ["gemma4:12b", "qwen3.5:9b", "gemma4:12b"]}
    assert data.validate_benchmark_models(settings, body) == ["gemma4:12b", "qwen3.5:9b"]


@pytest.fixture
def bench_server(settings: Settings, dist: Path,
                 monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[tuple[str, int], BenchmarkJob]]:
    monkeypatch.setattr(data, "list_models", lambda host: INSTALLED)
    job = BenchmarkJob(settings, add=lambda s: AddResult(0, 1, 0),
                       run=lambda s, models, on_progress: Path("eval_20261113_100000.json"))
    httpd = make_server(settings, dist, port=0, benchmark=job)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield (httpd.server_address[0], httpd.server_address[1]), job
    httpd.shutdown()
    httpd.server_close()


def test_server_benchmark_routes(bench_server: tuple[tuple[str, int], BenchmarkJob]) -> None:
    server, job = bench_server
    status, _, body = _request(server, "GET", "/api/benchmark/models")
    assert status == 200 and [m["name"] for m in json.loads(body)["models"]][0] == "gemma4:12b"
    assert json.loads(_request(server, "GET", "/api/benchmark/status")[2])["state"] == "idle"

    assert _request(server, "POST", "/api/benchmark/run", {"models": []})[0] == 400
    assert _request(server, "POST", "/api/benchmark/run", b"{nao e json")[0] == 400
    status, _, body = _request(server, "POST", "/api/benchmark/run", {"models": ["gemma4:12b"]})
    assert status == 202 and json.loads(body)["state"] == "running"
    job.wait(5)
    final = json.loads(_request(server, "GET", "/api/benchmark/status")[2])
    assert final["state"] == "done" and final["result_file"] == "eval_20261113_100000.json"
    assert _request(server, "POST", "/api/nada", {})[0] == 404
```

E em `test_lan_requires_access_code`, acrescentar:

```python
    assert _raw(lan_server, "POST", "/api/benchmark/run").status == 401
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `uv run pytest tests/test_dashboard.py -q`
Expected: FAIL (`AttributeError: ... has no attribute 'list_models'` / `make_server() got an unexpected keyword argument 'benchmark'`)

- [ ] **Step 3: Implementar em `data.py`**

Imports (junto dos existentes):

```python
from vagas_bot import eval_runner, evaluation
from vagas_bot.ollama_utils import OllamaUnavailable, list_models, normalize_model_name
```

(no lugar de `from vagas_bot import evaluation`.)

Nova seção depois de `benchmark_payload`:

```python
# --- botão Rodar benchmark -------------------------------------------------------------

EMBEDDING_FAMILIES = {"bert", "nomic-bert"}
UNSTABLE_MODELS = {"gpt-oss": "Derruba o Ollama nesta GPU"}  # prefixo do nome → aviso


def _llm_models(settings: Settings) -> list[str]:
    """Installed Ollama models usable as the LLM (embedding models left out)."""
    try:
        installed = list_models(settings.ollama_host)
    except OllamaUnavailable as exc:
        raise DashboardError(503, f"Ollama indisponível: {exc}") from exc
    embedder = normalize_model_name(settings.config.embeddings.ollama.model)
    return [m.name for m in installed
            if m.family not in EMBEDDING_FAMILIES and normalize_model_name(m.name) != embedder]


def _warning(name: str) -> str | None:
    return next((text for prefix, text in UNSTABLE_MODELS.items() if name.startswith(prefix)), None)


def benchmark_models(settings: Settings) -> dict[str, Any]:
    """GET /api/benchmark/models: options for the button, pre-checked like the last run."""
    names = _llm_models(settings)
    latest = evaluation.latest_results(_results_dir(settings))
    previous = evaluation.load_results(latest)[2].get("models", []) if latest else [settings.config.llm.ollama.model]
    wanted = {normalize_model_name(m) for m in previous}
    models = []
    for name in names:
        warning = _warning(name)
        models.append({"name": name, "default": warning is None and normalize_model_name(name) in wanted,
                       "warning": warning})
    return {
        "models": models,
        "pending_jobs": eval_runner.pending_archive_jobs(settings),
        "total_jobs": len(evaluation.load_eval_jobs(settings.eval_dir / "jobs")),
    }


def validate_benchmark_models(settings: Settings, body: Any) -> list[str]:
    """POST /api/benchmark/run body: {"models": [...]} with installed LLM models (no repeats)."""
    models = body.get("models") if isinstance(body, dict) else None
    if not isinstance(models, list) or not models or not all(isinstance(m, str) for m in models):
        raise DashboardError(400, 'Corpo inválido: envie {"models": ["qwen3:14b", ...]}')
    installed = set(_llm_models(settings))
    unknown = [m for m in models if m not in installed]
    if unknown:
        raise DashboardError(400, f"Modelo não instalado no Ollama: {', '.join(unknown)}")
    return list(dict.fromkeys(models))
```

- [ ] **Step 4: Implementar em `server.py`**

Import:

```python
from vagas_bot.dashboard.benchmark_job import BenchmarkJob
```

`DashboardHandler.__init__` ganha o `BenchmarkJob` compartilhado:

```python
    def __init__(
        self, *args: Any, settings: Settings, dist: Path, benchmark: BenchmarkJob, token: str | None = None,
        trust_local: bool = True, **kwargs: Any,
    ) -> None:
        self.settings = settings
        self.dist = dist.resolve()
        self.benchmark = benchmark
        self.token = token
        self.trust_local = trust_local
        super().__init__(*args, **kwargs)
```

Em `do_GET`, o dicionário `routes` ganha:

```python
                "/api/benchmark/models": lambda: data.benchmark_models(self.settings),
                "/api/benchmark/status": lambda: self.benchmark.status(),
```

Novo `do_POST`, depois de `do_PUT`:

```python
    def do_POST(self) -> None:  # noqa: N802
        url = urlsplit(self.path)
        if not self._authorized():
            self._send_json(HTTPStatus.UNAUTHORIZED, {"error": "Acesso restrito: abra o link com o código de acesso."})
            return
        if url.path != "/api/benchmark/run":
            self._api(_not_found)
            return
        self._api(lambda: self.benchmark.start(data.validate_benchmark_models(self.settings, self._json_body())),
                  status=HTTPStatus.ACCEPTED)
```

`_api` aceita o status de sucesso:

```python
    def _api(self, produce: Any, status: int = HTTPStatus.OK) -> None:
        try:
            self._send_json(status, produce())
```

(o resto do método igual.)

`make_server`:

```python
def make_server(
    settings: Settings, dist: Path, host: str = "127.0.0.1", port: int = 8765, token: str | None = None,
    trust_local: bool = True, benchmark: BenchmarkJob | None = None,
) -> ThreadingHTTPServer:
    """token=None: localhost only, no code. With a token (LAN mode), other devices need it."""
    job = benchmark or BenchmarkJob(settings)  # um só por servidor: todas as abas veem a mesma rodada
    handler = partial(DashboardHandler, settings=settings, dist=dist, benchmark=job, token=token,
                      trust_local=trust_local)
    return ThreadingHTTPServer((host, port), handler)
```

- [ ] **Step 5: Rodar e ver passar**

Run: `uv run pytest -q`
Expected: todos passam.

- [ ] **Step 6: Commit**

```bash
git add src/vagas_bot/dashboard/data.py src/vagas_bot/dashboard/server.py tests/test_dashboard.py
git commit -m "feat: API do dashboard para listar modelos, rodar o benchmark e ver o andamento"
```

---

### Task 6: Frontend — tipos, `ApiService` e funções puras do painel

**Files:**
- Modify: `dashboard/src/app/core/models.ts` (após `BenchmarkRun`)
- Modify: `dashboard/src/app/core/api.service.ts`
- Modify: `dashboard/src/app/core/api.service.spec.ts`
- Create: `dashboard/src/app/benchmark/run-progress.ts`
- Create: `dashboard/src/app/benchmark/run-progress.spec.ts`

- [ ] **Step 1: Tipos** (`models.ts`, logo depois da interface `BenchmarkRun`)

```ts
export interface BenchmarkModelOption {
  name: string;
  default: boolean;
  warning: string | null;
}

export interface BenchmarkModels {
  models: BenchmarkModelOption[];
  pending_jobs: number;
  total_jobs: number;
}

export interface BenchmarkStatus {
  state: 'idle' | 'running' | 'done' | 'error';
  phase: 'adding' | 'running' | null;
  models: string[];
  current_model: string | null;
  model_index: number;
  model_count: number;
  done: number;
  total: number;
  added: number;
  started_at: string | null;
  finished_at: string | null;
  result_file: string | null;
  error: string | null;
}
```

- [ ] **Step 2: Testes que falham** (`api.service.spec.ts`, dentro do `describe`, no fim)

```ts
  it('lista os modelos, inicia o benchmark com POST e consulta o status', () => {
    api.benchmarkModels().subscribe();
    http.expectOne({ method: 'GET', url: '/api/benchmark/models' }).flush({ models: [], pending_jobs: 0, total_jobs: 0 });
    api.startBenchmark(['qwen3:14b']).subscribe();
    const req = http.expectOne({ method: 'POST', url: '/api/benchmark/run' });
    expect(req.request.body).toEqual({ models: ['qwen3:14b'] });
    req.flush({ state: 'running' });
    api.benchmarkStatus().subscribe();
    http.expectOne({ method: 'GET', url: '/api/benchmark/status' }).flush({ state: 'idle' });
  });

  it('erros do painel do benchmark voltam como mensagem, sem o aviso global', () => {
    let message = '';
    api.startBenchmark(['x']).subscribe({ error: (e: Error) => (message = e.message) });
    http.expectOne('/api/benchmark/run').flush({ error: 'Já existe um benchmark rodando.' }, { status: 409, statusText: 'Conflict' });
    expect(message).toBe('Já existe um benchmark rodando.');
    api.benchmarkModels().subscribe({ error: () => undefined });
    http.expectOne('/api/benchmark/models').flush({ error: 'Ollama indisponível' }, { status: 503, statusText: 'Unavailable' });
    expect(api.lastError()).toBeNull();
  });
```

`run-progress.spec.ts`:

```ts
import { BenchmarkModelOption, BenchmarkStatus } from '../core/models';
import { defaultSelection, jobsSummary, progressPercent, progressText } from './run-progress';

function status(overrides: Partial<BenchmarkStatus>): BenchmarkStatus {
  return {
    state: 'running', phase: 'running', models: ['a:1b', 'b:2b'], current_model: null, model_index: 0, model_count: 2,
    done: 0, total: 0, added: 0, started_at: null, finished_at: null, result_file: null, error: null, ...overrides,
  };
}

describe('run-progress', () => {
  it('defaultSelection pega só os marcados por padrão, na ordem', () => {
    const opts: BenchmarkModelOption[] = [
      { name: 'a', default: true, warning: null },
      { name: 'b', default: false, warning: 'x' },
      { name: 'c', default: true, warning: null },
    ];
    expect(defaultSelection(opts)).toEqual(['a', 'c']);
  });

  it('progressText cobre inclusão, início e andamento', () => {
    expect(progressText(status({ phase: 'adding' }))).toBe('Incluindo vagas novas…');
    expect(progressText(status({}))).toBe('Carregando a:1b…');
    expect(progressText(status({ current_model: 'b:2b', model_index: 2, done: 34, total: 46 }))).toBe('b:2b (2/2) · 34/46');
  });

  it('progressPercent soma os modelos já concluídos', () => {
    expect(progressPercent(status({}))).toBe(0);
    expect(progressPercent(status({ current_model: 'a:1b', model_index: 1, done: 23, total: 46 }))).toBe(25);
    expect(progressPercent(status({ current_model: 'b:2b', model_index: 2, done: 46, total: 46 }))).toBe(100);
  });

  it('jobsSummary no singular e no plural', () => {
    expect(jobsSummary(1, 15)).toBe('1 vaga nova será incluída · 16 no total');
    expect(jobsSummary(8, 15)).toBe('8 vagas novas serão incluídas · 23 no total');
    expect(jobsSummary(0, 15)).toBe('Nenhuma vaga nova · 15 no total');
  });
});
```

- [ ] **Step 3: Rodar e ver falhar**

Run (em `dashboard/`): `npm test`
Expected: FAIL (erros de compilação: `benchmarkModels` não existe; `./run-progress` não encontrado)

- [ ] **Step 4: Implementar `api.service.ts`**

Import dos tipos:

```ts
import { BenchmarkModels, BenchmarkPayload, BenchmarkRun, BenchmarkStatus, JobRow, LabelResult } from './models';
```

Comentário da classe: `/** Chamadas da API local. Erros das telas viram mensagem em \`lastError\` (aviso no topo); os de formulário/painel voltam para quem chamou. */`

Métodos novos (depois de `benchmark`) e `saveLabel` usando o helper `local`:

```ts
  /** Erros (ex.: Ollama fora do ar) voltam para o painel, não para o aviso global. */
  benchmarkModels(): Observable<BenchmarkModels> {
    return this.local(this.http.get<BenchmarkModels>('/api/benchmark/models'));
  }

  startBenchmark(models: string[]): Observable<BenchmarkStatus> {
    return this.local(this.http.post<BenchmarkStatus>('/api/benchmark/run', { models }));
  }

  benchmarkStatus(): Observable<BenchmarkStatus> {
    return this.track(this.http.get<BenchmarkStatus>('/api/benchmark/status'));
  }

  /** Sem `note`, o comentário atual é mantido. Erros de nota não vão para o aviso global. */
  saveLabel(id: string, score: number | null, note?: string): Observable<LabelResult> {
    const body = note === undefined ? { score } : { score, note };
    return this.local(this.http.put<LabelResult>(`/api/labels/${encodeURIComponent(id)}`, body));
  }

  private local<T>(request: Observable<T>): Observable<T> {
    return request.pipe(catchError((err: HttpErrorResponse) => throwError(() => new Error(errorMessage(err)))));
  }
```

- [ ] **Step 5: Implementar `run-progress.ts`**

```ts
import { BenchmarkModelOption, BenchmarkStatus } from '../core/models';

/** Funções puras do botão "Rodar benchmark" (testadas sem montar o componente). */

export function defaultSelection(options: BenchmarkModelOption[]): string[] {
  return options.filter((o) => o.default).map((o) => o.name);
}

/** "Incluindo vagas novas…" → "Carregando <1º modelo>…" → "gemma4:12b (2/3) · 34/46". */
export function progressText(s: BenchmarkStatus): string {
  if (s.phase === 'adding') return 'Incluindo vagas novas…';
  if (!s.current_model) return `Carregando ${s.models[0] ?? 'modelo'}…`;
  return `${s.current_model} (${s.model_index}/${s.model_count}) · ${s.done}/${s.total}`;
}

/** 0–100, contando os modelos já concluídos. */
export function progressPercent(s: BenchmarkStatus): number {
  if (!s.model_count || !s.total || s.model_index < 1) return 0;
  const perModel = 100 / s.model_count;
  return Math.round((s.model_index - 1) * perModel + (s.done / s.total) * perModel);
}

export function jobsSummary(pending: number, total: number): string {
  const novas =
    pending === 0 ? 'Nenhuma vaga nova' : pending === 1 ? '1 vaga nova será incluída' : `${pending} vagas novas serão incluídas`;
  return `${novas} · ${total + pending} no total`;
}
```

- [ ] **Step 6: Rodar e ver passar**

Run (em `dashboard/`): `npm test`
Expected: todos passam.

- [ ] **Step 7: Commit**

```bash
git add dashboard/src/app/core/models.ts dashboard/src/app/core/api.service.ts dashboard/src/app/core/api.service.spec.ts dashboard/src/app/benchmark/run-progress.ts dashboard/src/app/benchmark/run-progress.spec.ts
git commit -m "feat: chamadas e funções do painel Rodar benchmark na tela"
```

---

### Task 7: Componente `RunBenchmark` e integração na tela

**Files:**
- Create: `dashboard/src/app/benchmark/run-benchmark.ts`
- Modify: `dashboard/src/app/benchmark/benchmark-page.ts` (imports, `imports: [...]`, `<header class="head">`, texto do estado vazio, estilos `.head`, método novo)

- [ ] **Step 1: Criar `run-benchmark.ts`**

```ts
import { ChangeDetectionStrategy, Component, DestroyRef, ElementRef, computed, inject, output, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { EMPTY, Subscription, catchError, switchMap, takeWhile, timer } from 'rxjs';

import { ApiService } from '../core/api.service';
import { BenchmarkModelOption, BenchmarkStatus } from '../core/models';
import { defaultSelection, jobsSummary, progressPercent, progressText } from './run-progress';

const POLL_MS = 3000;

/**
 * Botão "Rodar benchmark": painel com os modelos do Ollama, faixa de progresso enquanto roda
 * e `finished` com o arquivo do resultado novo. `display: contents`: o botão e a faixa viram
 * itens do cabeçalho da página (a faixa ocupa uma linha inteira embaixo).
 */
@Component({
  selector: 'app-run-benchmark',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    '(document:click)': 'onDocumentClick($event)',
    '(document:keydown.escape)': 'open.set(false)',
  },
  template: `
    <div class="wrap">
      <button type="button" class="trigger" [disabled]="running()" [attr.aria-expanded]="open()" (click)="toggle()">
        {{ running() ? 'Rodando…' : 'Rodar benchmark' }}
      </button>
      @if (open()) {
        <div class="backdrop" (click)="open.set(false)"></div>
        <div class="panel" role="dialog" aria-label="Rodar benchmark">
          <strong class="title">Rodar benchmark</strong>
          @if (loadingOptions()) {
            <p class="muted">Consultando o Ollama…</p>
          }
          @if (panelError(); as e) {
            <p class="error">{{ e }}</p>
          }
          @if (options().length) {
            <fieldset>
              <legend>Modelos</legend>
              @for (o of options(); track o.name) {
                <label class="opt">
                  <input type="checkbox" [checked]="selected().includes(o.name)"
                         (change)="toggleModel(o.name, $any($event.target).checked)" />
                  <span>{{ o.name }}</span>
                </label>
                @if (o.warning) {
                  <span class="warn">{{ o.warning }}</span>
                }
              }
            </fieldset>
            <p class="muted">{{ jobsText() }}</p>
            <div class="actions">
              <button type="button" class="ghost" (click)="open.set(false)">Cancelar</button>
              <button type="button" [disabled]="!selected().length || starting()" (click)="start()">Rodar</button>
            </div>
          }
        </div>
      }
    </div>
    @if (status(); as s) {
      @if (s.state === 'running') {
        <div class="strip" role="status">
          <span>{{ progressText(s) }}</span>
          <div class="bar"><div class="fill" [style.width.%]="progressPercent(s)"></div></div>
        </div>
      } @else if (s.state === 'error') {
        <div class="strip error" role="alert">
          <span>O benchmark falhou: {{ s.error }}</span>
          <button type="button" class="close" (click)="status.set(null)" aria-label="Fechar aviso">✕</button>
        </div>
      }
    }
  `,
  styles: `
    :host { display: contents; }
    .wrap { position: relative; }
    .trigger {
      all: unset; box-sizing: border-box; cursor: pointer; display: inline-flex; align-items: center; height: 36px; padding: 0 14px;
      border-radius: 8px; background: var(--accent); color: var(--on-accent); font-size: 0.88rem; font-weight: 600; white-space: nowrap;
    }
    .trigger:hover:not(:disabled) { background: var(--accent-strong); }
    .trigger:disabled { opacity: 0.6; cursor: default; }
    .trigger:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
    .panel {
      position: absolute; top: calc(100% + 6px); right: 0; z-index: 30; width: 300px; padding: 14px; display: grid; gap: 10px;
      background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow-pop);
    }
    .title { font-size: 0.95rem; }
    fieldset { border: 0; margin: 0; padding: 0; display: grid; gap: 2px; }
    legend { padding: 0; margin-bottom: 4px; font-size: 0.72rem; font-weight: 600; color: var(--faint);
             text-transform: uppercase; letter-spacing: 0.04em; }
    .opt { display: flex; align-items: center; gap: 8px; padding: 4px 2px; cursor: pointer; }
    .warn { margin: -2px 0 4px 26px; font-size: 0.78rem; color: var(--maybe); }
    .muted { margin: 0; color: var(--muted); font-size: 0.85rem; }
    .error { margin: 0; color: var(--danger); font-size: 0.85rem; }
    .actions { display: flex; justify-content: flex-end; gap: 8px; }
    .ghost { all: unset; cursor: pointer; padding: 7px 12px; border-radius: 8px; color: var(--muted); font-weight: 500; }
    .ghost:hover { background: var(--hover); color: var(--text); }
    .backdrop { display: none; }
    .strip {
      flex: 1 0 100%; order: 10; display: grid; grid-template-columns: auto 1fr; align-items: center; gap: 8px 16px;
      padding: 10px 14px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); font-size: 0.88rem;
    }
    .bar { height: 6px; border-radius: 999px; background: var(--surface-2); overflow: hidden; }
    .fill { height: 100%; background: var(--accent); transition: width 0.4s ease; }
    .strip.error { grid-template-columns: 1fr auto; background: var(--danger-bg); color: var(--danger); border-color: var(--danger); }
    .close { all: unset; cursor: pointer; }
    @media (max-width: 720px) {
      .backdrop { display: block; position: fixed; inset: 0; z-index: 29; background: var(--backdrop); }
      .panel { position: fixed; top: auto; left: 0; right: 0; bottom: 0; width: auto; border-radius: 16px 16px 0 0;
               padding: 16px 16px calc(16px + env(safe-area-inset-bottom)); }
      .strip { grid-template-columns: 1fr; }
    }
  `,
})
export class RunBenchmark {
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private polling?: Subscription;

  /** Nome do arquivo do resultado novo (data/eval/results/eval_*.json). */
  readonly finished = output<string>();

  protected readonly open = signal(false);
  protected readonly options = signal<BenchmarkModelOption[]>([]);
  protected readonly selected = signal<string[]>([]);
  protected readonly counts = signal({ pending: 0, total: 0 });
  protected readonly loadingOptions = signal(false);
  protected readonly starting = signal(false);
  protected readonly panelError = signal<string | null>(null);
  protected readonly status = signal<BenchmarkStatus | null>(null);
  protected readonly running = computed(() => this.status()?.state === 'running');
  protected readonly jobsText = computed(() => jobsSummary(this.counts().pending, this.counts().total));
  protected readonly progressText = progressText;
  protected readonly progressPercent = progressPercent;

  constructor() {
    // Rodada iniciada em outra aba ou no celular: retoma o acompanhamento.
    this.api.benchmarkStatus().subscribe((s) => {
      if (s.state === 'running') {
        this.status.set(s);
        this.poll();
      }
    });
  }

  protected toggle(): void {
    if (this.open()) {
      this.open.set(false);
      return;
    }
    this.open.set(true);
    this.panelError.set(null);
    this.loadingOptions.set(true);
    this.api.benchmarkModels().subscribe({
      next: (r) => {
        this.options.set(r.models);
        this.selected.set(defaultSelection(r.models));
        this.counts.set({ pending: r.pending_jobs, total: r.total_jobs });
        this.loadingOptions.set(false);
      },
      error: (e: Error) => {
        this.panelError.set(e.message);
        this.loadingOptions.set(false);
      },
    });
  }

  protected toggleModel(name: string, checked: boolean): void {
    this.selected.update((list) => (checked ? [...list, name] : list.filter((n) => n !== name)));
  }

  protected start(): void {
    const chosen = this.options()
      .map((o) => o.name)
      .filter((n) => this.selected().includes(n)); // na ordem da lista
    this.starting.set(true);
    this.panelError.set(null);
    this.api.startBenchmark(chosen).subscribe({
      next: (s) => {
        this.starting.set(false);
        this.open.set(false);
        this.status.set(s);
        this.poll();
      },
      error: (e: Error) => {
        this.starting.set(false);
        this.panelError.set(e.message);
      },
    });
  }

  protected onDocumentClick(event: MouseEvent): void {
    if (this.open() && !this.host.nativeElement.contains(event.target as Node)) this.open.set(false);
  }

  private poll(): void {
    this.polling?.unsubscribe();
    this.polling = timer(POLL_MS, POLL_MS)
      .pipe(
        switchMap(() => this.api.benchmarkStatus().pipe(catchError(() => EMPTY))), // falha pontual: tenta no próximo ciclo
        takeWhile((s) => s.state === 'running', true),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((s) => {
        this.status.set(s);
        if (s.state === 'done' && s.result_file) this.finished.emit(s.result_file);
      });
  }
}
```

Nota: com `display: contents` no host, `host.nativeElement.contains(...)` continua valendo (o DOM não muda, só a caixa de layout).

- [ ] **Step 2: Integrar em `benchmark-page.ts`**

Import: `import { RunBenchmark } from './run-benchmark';` e `imports: [BenchmarkSummary, ScoreChart, LabelInput, RunBenchmark],`.

No template, dentro de `<header class="head">`, logo depois do bloco `@if (runs().length) { <label class="run">...</label> }`:

```html
      <app-run-benchmark (finished)="onBenchmarkFinished($event)" />
```

Estado vazio (trocar o `<p>` atual):

```html
        <p>Clique em <strong>Rodar benchmark</strong> (ou rode <code>uv run python -m vagas_bot eval-models qwen3.5:9b gemma4:12b</code>) e recarregue.</p>
```

Estilos: trocar a regra `.head` por estas duas (título à esquerda, seletor e botão à direita):

```css
    .head { display: flex; flex-wrap: wrap; align-items: end; gap: 12px; margin-bottom: 12px; }
    .head > div:first-child { margin-right: auto; }
```

Método novo na classe (depois de `selectRun`):

```ts
  /** Rodada nova terminou: recarrega a lista e mostra o resultado novo. */
  protected onBenchmarkFinished(file: string): void {
    this.api.benchmarkRuns().subscribe((runs) => {
      this.runs.set(runs);
      if (runs.length) this.selectRun(runs.some((r) => r.file === file) ? file : runs[0].file);
    });
  }
```

- [ ] **Step 3: Testes e build**

Run (em `dashboard/`): `npm test && npm run build`
Expected: testes passam; `Application bundle generation complete.` sem erros.

- [ ] **Step 4: Commit**

```bash
git add dashboard/src/app/benchmark/run-benchmark.ts dashboard/src/app/benchmark/benchmark-page.ts
git commit -m "feat: botão Rodar benchmark na tela Benchmark"
```

---

### Task 8: Documentação e verificação no app real

**Files:**
- Modify: `README.md` (seção do Dashboard, item **Benchmark**)

- [ ] **Step 1: README** — no item `- **Benchmark:** ...` da seção Dashboard, acrescentar ao fim:

```markdown
 O botão **Rodar benchmark** inclui no conjunto as vagas novas avaliadas pelo bot (as de `data/jobs.jsonl` que ainda não estão em `data/eval/jobs/`), roda os modelos marcados (os da última rodada vêm marcados) e mostra o andamento; ao terminar, a rodada nova aparece selecionada. Uma rodada por vez; se o dashboard for reiniciado no meio, ela se perde (nada fica pela metade em disco).
```

- [ ] **Step 2: Suítes completas**

Run: `uv run pytest -q` e (em `dashboard/`) `npm test`
Expected: tudo passa.

- [ ] **Step 3: Reiniciar o dashboard em uso e conferir as rotas** (o Python novo só vale depois de reiniciar a tarefa)

```powershell
Stop-ScheduledTask -TaskName vagas-pj-bot-dashboard; Start-ScheduledTask -TaskName vagas-pj-bot-dashboard
```

Depois de ~8 s:

```bash
curl -s http://127.0.0.1:8765/api/benchmark/models
curl -s http://127.0.0.1:8765/api/benchmark/status
```

Expected: a primeira lista `gemma4:12b`, `gpt-oss:20b` (com `warning`), `qwen3.5:9b`, `qwen3:14b` (sem `bge-m3`), com `total_jobs` = 16 e `pending_jobs` entre 1 e 8 (vagas que você já notou pelo dashboard podem já estar no conjunto); a segunda devolve `"state": "idle"`.

**Não** disparar `POST /api/benchmark/run` aqui: a rodada real ocupa a GPU por vários minutos; quem decide quando rodar é o usuário, pelo botão.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: botão Rodar benchmark no README"
```
