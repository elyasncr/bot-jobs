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
