"""Phase 8: compare LLMs on saved jobs (data/eval/jobs/).

Each model scores every job `runs` times. Measured: latency per job, invalid JSON rate,
score variation between runs (consistency), "CLT" answers without CLT evidence in the text,
and — when data/eval/labels.yaml has my scores — Spearman between model and me.
Raw results go to data/eval/results/*.json (the report and the dashboard read them).
"""

import hashlib
import json
import statistics
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from itertools import zip_longest
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from vagas_bot.config import Settings
from vagas_bot.filters import has_clt_signals
from vagas_bot.gpu import gpu_memory_used_gb
from vagas_bot.log import get_logger
from vagas_bot.models import Job, LLMScoreOutput, PJStatus, Prefs
from vagas_bot.ollama_utils import loaded_vram_gb, unload_model
from vagas_bot.scoring.llm_base import LLMInvalidOutput, LLMScorer, LLMUnavailable
from vagas_bot.scoring.ranker import weighted_total

log = get_logger("eval")

LABELS_HEADER = (
    "# Minhas notas (0-100) para as vagas de data/eval/jobs/. Deixe score vazio para pular.\n"
    "# Usadas pelo eval-models / eval-report (Spearman modelo x eu) e pelo fine-tuning (Fase 9).\n"
)

# --- snapshots e labels ---------------------------------------------------------------


def snapshot_name(job: Job) -> str:
    return hashlib.sha1(job.id.encode("utf-8")).hexdigest()[:12] + ".json"


def save_eval_jobs(jobs: list[Job], jobs_dir: Path) -> int:
    """Write one JSON per job (without scores). Existing snapshots are kept. Returns new files."""
    jobs_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    for job in jobs:
        path = jobs_dir / snapshot_name(job)
        if path.exists():
            continue
        clean = job.model_copy(update={"score": None, "embedding_score": None})
        path.write_text(clean.model_dump_json(indent=2), encoding="utf-8")
        written += 1
    return written


def load_eval_jobs(jobs_dir: Path) -> list[Job]:
    return [Job.model_validate_json(p.read_text(encoding="utf-8")) for p in sorted(jobs_dir.glob("*.json"))]


def pick_diverse(jobs: list[Job], n: int, key: Callable[[Job], str]) -> list[Job]:
    """Round-robin across groups (e.g. the query that found each job), keeping order inside."""
    groups: dict[str, list[Job]] = {}
    for job in jobs:
        groups.setdefault(key(job), []).append(job)
    interleaved = [j for row in zip_longest(*groups.values()) for j in row if j is not None]
    return interleaved[:n]


def ensure_label_entries(path: Path, jobs: list[Job]) -> int:
    """Append an empty entry for each job not yet in labels.yaml. Never touches existing scores."""
    existing = _read_labels_raw(path)
    missing = [j for j in jobs if j.id not in existing]
    if not missing:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    text = path.read_text(encoding="utf-8") if path.is_file() else LABELS_HEADER
    if text and not text.endswith("\n"):
        text += "\n"
    for job in missing:
        comment = f"{job.title} · {job.company}".replace("\n", " ")[:100]
        text += f"\n{json.dumps(job.id)}:  # {comment}\n  score:\n  note: \"\"\n"
    path.write_text(text, encoding="utf-8")
    return len(missing)


def _read_labels_raw(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): v for k, v in data.items()} if isinstance(data, dict) else {}


def load_labels(path: Path) -> dict[str, int]:
    """{job_id: score} only for entries with a numeric score in 0-100."""
    labels: dict[str, int] = {}
    for job_id, entry in _read_labels_raw(path).items():
        score = entry.get("score") if isinstance(entry, dict) else None
        if isinstance(score, (int, float)) and 0 <= score <= 100:
            labels[job_id] = int(score)
    return labels


# --- estatística ----------------------------------------------------------------------


def rankdata(values: list[float]) -> np.ndarray:
    """Ranks 1..n with ties averaged (same as scipy.stats.rankdata 'average')."""
    arr = np.asarray(values, dtype=float)
    order = np.argsort(arr, kind="mergesort")
    ranks = np.empty(len(arr))
    ranks[order] = np.arange(1, len(arr) + 1)
    _, inverse = np.unique(arr, return_inverse=True)
    sums = np.bincount(inverse, weights=ranks)
    counts = np.bincount(inverse)
    return (sums / counts)[inverse]


def spearman(x: list[float], y: list[float]) -> float | None:
    """Spearman's rho; None with fewer than 3 pairs or a constant side."""
    if len(x) != len(y) or len(x) < 3:
        return None
    rx, ry = rankdata(x), rankdata(y)
    if rx.std() == 0 or ry.std() == 0:
        return None
    return float(np.corrcoef(rx, ry)[0, 1])


# --- execução -------------------------------------------------------------------------


@dataclass(frozen=True)
class JobMeta:
    id: str
    title: str
    company: str
    url: str
    publisher: str | None
    clt_signals: bool  # o texto tem evidência de CLT (para julgar um "clt" do modelo)

    @classmethod
    def from_job(cls, job: Job) -> "JobMeta":
        return cls(job.id, job.title, job.company, job.url, job.publisher, has_clt_signals(job))


@dataclass
class Trial:
    job_id: str
    run: int
    latency_s: float
    output: LLMScoreOutput | None = None
    error: str | None = None
    calls: int = 1  # chamadas ao modelo (1 + retries)
    invalid: int = 0  # respostas fora do schema

    @property
    def total(self) -> int | None:
        return weighted_total(self.output) if self.output else None


@dataclass
class ModelRun:
    model: str
    available: bool = True
    error: str | None = None
    load_s: float | None = None  # 1ª chamada (aquecimento), inclui carregar o modelo na GPU
    vram_gb: float | None = None
    trials: list[Trial] = field(default_factory=list)


def evaluate_model(
    scorer: LLMScorer, jobs: list[Job], cv_md: str, prefs: Prefs, runs: int, warmup: bool = True
) -> ModelRun:
    """Score every job `runs` times (whole pass per run, so runs don't sit back to back)."""
    result = ModelRun(model=scorer.name)
    try:
        scorer.healthcheck()
    except LLMUnavailable as exc:
        log.error("%s: indisponível (%s).", scorer.name, exc)
        return ModelRun(model=scorer.name, available=False, error=str(exc))
    if warmup and jobs:
        t0 = time.perf_counter()
        try:
            scorer.score(jobs[0], cv_md, prefs)
        except (LLMInvalidOutput, LLMUnavailable) as exc:
            log.warning("%s: aquecimento falhou (%s).", scorer.name, exc)
        result.load_s = round(time.perf_counter() - t0, 2)
        log.info("%s: aquecimento (carga do modelo) em %.1fs.", scorer.name, result.load_s)

    total_calls = runs * len(jobs)
    for run in range(1, runs + 1):
        for index, job in enumerate(jobs, start=1):
            trial = _score_once(scorer, job, cv_md, prefs, run)
            result.trials.append(trial)
            done = (run - 1) * len(jobs) + index
            shown = f"{trial.total:3d}%" if trial.total is not None else "erro"
            log.info("  %s [%d/%d] rodada %d: %s em %.1fs · %s",
                     scorer.name, done, total_calls, run, shown, trial.latency_s, job.title)
            if trial.error and trial.error.startswith("indisponível"):
                result.available = False
                result.error = trial.error
                return result
    return result


def _score_once(scorer: LLMScorer, job: Job, cv_md: str, prefs: Prefs, run: int) -> Trial:
    calls0 = getattr(scorer, "calls", 0)
    invalid0 = getattr(scorer, "invalid_attempts", 0)
    output: LLMScoreOutput | None = None
    error: str | None = None
    t0 = time.perf_counter()
    try:
        output = scorer.score(job, cv_md, prefs)
    except LLMInvalidOutput as exc:
        error = str(exc)
    except LLMUnavailable as exc:
        error = f"indisponível: {exc}"
    latency = round(time.perf_counter() - t0, 2)
    calls = getattr(scorer, "calls", calls0 + 1) - calls0
    invalid = getattr(scorer, "invalid_attempts", invalid0) - invalid0
    return Trial(job.id, run, latency, output, error, calls=max(calls, 1), invalid=invalid)


def ollama_scorer_for(settings: Settings, model: str) -> LLMScorer:
    """Same settings as the daily run (num_ctx, temperature, think), only the model changes."""
    from vagas_bot.scoring.llm_ollama import OllamaScorer  # noqa: PLC0415

    cfg = settings.config.llm.ollama.model_copy(update={"model": model, "keep_alive": "5m"})
    return OllamaScorer(cfg, host=settings.ollama_host)


def run_models(
    settings: Settings,
    models: list[str],
    jobs: list[Job],
    cv_md: str,
    prefs: Prefs,
    runs: int,
    warmup: bool = True,
    make_scorer: Callable[[Settings, str], LLMScorer] = ollama_scorer_for,
) -> list[ModelRun]:
    """One model at a time; each is unloaded at the end so the next gets the whole GPU."""
    results = []
    for model in models:
        log.info("Avaliando %s: %d vagas × %d rodadas.", model, len(jobs), runs)
        scorer = make_scorer(settings, model)
        baseline = gpu_memory_used_gb()
        run = evaluate_model(scorer, jobs, cv_md, prefs, runs, warmup)
        if run.available or run.trials:
            run.vram_gb = _vram_delta(baseline, gpu_memory_used_gb()) or loaded_vram_gb(settings.ollama_host, model)
            unload_model(settings.ollama_host, model)
        results.append(run)
    return results


def _vram_delta(before: float | None, after: float | None) -> float | None:
    """GPU memory the model added (nvidia-smi before x after loading); None if unmeasurable."""
    if before is None or after is None or after <= before:
        return None
    return round(after - before, 1)


# --- métricas -------------------------------------------------------------------------


@dataclass
class ModelSummary:
    model: str
    available: bool
    error: str | None
    ok: int
    failed: int
    calls: int
    invalid: int
    mean_s: float | None
    median_s: float | None
    load_s: float | None
    vram_gb: float | None
    mean_total: float | None
    mean_abs_diff: float | None  # variação média da nota entre rodadas (mesma vaga)
    max_diff: int | None
    pj_consistency: float | None  # % de vagas com o mesmo pj_status em todas as rodadas
    clt_answers: int
    clt_without_evidence: int  # "clt" em vaga cujo texto não tem sinal de CLT
    spearman_gold: float | None
    n_gold: int
    mean_totals: dict[str, float]

    @property
    def invalid_rate(self) -> float:
        return self.invalid / self.calls if self.calls else 0.0

    @property
    def fail_rate(self) -> float:
        total = self.ok + self.failed
        return self.failed / total if total else 0.0


def summarize(run: ModelRun, metas: dict[str, JobMeta], labels: dict[str, int]) -> ModelSummary:
    ok = [t for t in run.trials if t.output is not None]
    latencies = [t.latency_s for t in ok]
    by_job: dict[str, list[Trial]] = {}
    for trial in ok:
        by_job.setdefault(trial.job_id, []).append(trial)

    diffs = [max(totals) - min(totals) for ts in by_job.values() if len(totals := [t.total or 0 for t in ts]) >= 2]
    multi = [ts for ts in by_job.values() if len(ts) >= 2]
    same_pj = [len({t.output.pj_status for t in ts if t.output}) == 1 for ts in multi]
    clt = [t for t in ok if t.output and t.output.pj_status is PJStatus.CLT]
    clt_no_evidence = [t for t in clt if t.job_id in metas and not metas[t.job_id].clt_signals]
    mean_totals = {jid: statistics.fmean(t.total or 0 for t in ts) for jid, ts in by_job.items()}
    gold_ids = [jid for jid in mean_totals if jid in labels]

    return ModelSummary(
        model=run.model,
        available=run.available,
        error=run.error,
        ok=len(ok),
        failed=len(run.trials) - len(ok),
        calls=sum(t.calls for t in run.trials),
        invalid=sum(t.invalid for t in run.trials),
        mean_s=statistics.fmean(latencies) if latencies else None,
        median_s=statistics.median(latencies) if latencies else None,
        load_s=run.load_s,
        vram_gb=run.vram_gb,
        mean_total=statistics.fmean(mean_totals.values()) if mean_totals else None,
        mean_abs_diff=statistics.fmean(diffs) if diffs else None,
        max_diff=max(diffs) if diffs else None,
        pj_consistency=sum(same_pj) / len(same_pj) if same_pj else None,
        clt_answers=len(clt),
        clt_without_evidence=len(clt_no_evidence),
        spearman_gold=spearman([mean_totals[j] for j in gold_ids], [labels[j] for j in gold_ids]),
        n_gold=len(gold_ids),
        mean_totals=mean_totals,
    )


def agreement(a: ModelSummary, b: ModelSummary) -> float | None:
    """Spearman between two models' mean totals on the jobs both scored."""
    common = [jid for jid in a.mean_totals if jid in b.mean_totals]
    return spearman([a.mean_totals[j] for j in common], [b.mean_totals[j] for j in common])


# --- persistência dos resultados ------------------------------------------------------


def results_payload(runs: list[ModelRun], metas: list[JobMeta], meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "meta": meta,
        "jobs": [asdict(m) for m in metas],
        "models": [
            {
                "model": r.model,
                "available": r.available,
                "error": r.error,
                "load_s": r.load_s,
                "vram_gb": r.vram_gb,
                "trials": [
                    {
                        "job_id": t.job_id,
                        "run": t.run,
                        "latency_s": t.latency_s,
                        "error": t.error,
                        "calls": t.calls,
                        "invalid": t.invalid,
                        "total": t.total,
                        "output": t.output.model_dump(mode="json") if t.output else None,
                    }
                    for t in r.trials
                ],
            }
            for r in runs
        ],
    }


def save_results(results_dir: Path, payload: dict[str, Any], now: datetime | None = None) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    path = results_dir / f"eval_{stamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def load_results(path: Path) -> tuple[list[ModelRun], list[JobMeta], dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    metas = [JobMeta(**m) for m in data["jobs"]]
    runs = [
        ModelRun(
            model=m["model"],
            available=m["available"],
            error=m["error"],
            load_s=m["load_s"],
            vram_gb=m["vram_gb"],
            trials=[
                Trial(
                    job_id=t["job_id"],
                    run=t["run"],
                    latency_s=t["latency_s"],
                    output=LLMScoreOutput.model_validate(t["output"]) if t["output"] else None,
                    error=t["error"],
                    calls=t["calls"],
                    invalid=t["invalid"],
                )
                for t in m["trials"]
            ],
        )
        for m in data["models"]
    ]
    return runs, metas, data["meta"]


def latest_results(results_dir: Path) -> Path | None:
    files = sorted(results_dir.glob("eval_*.json"))
    return files[-1] if files else None
