"""CLI entry point: uv run python -m vagas_bot <command>."""

import sys
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from vagas_bot.config import ConfigError, Settings, load_settings
from vagas_bot.cv import CVError
from vagas_bot.doctor import Status, run_checks
from vagas_bot.embeddings.base import EmbedderUnavailable
from vagas_bot.log import get_logger, setup_logging
from vagas_bot.pipeline import RunOptions, run_pipeline
from vagas_bot.storage import StorageError


def _force_utf8_stdio() -> None:
    """Windows consoles/Task Scheduler default to cp1252, which breaks accents and arrows."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


_force_utf8_stdio()

app =typer.Typer(add_completion=False, no_args_is_help=True, help="Bot de vagas PJ de IA/ML.")
console = Console()

ConfigOption = Annotated[
    Path, typer.Option("--config", "-c", help="Caminho do config.yaml (define a raiz do projeto).")
]

_STATUS_STYLE = {
    Status.OK: "[green]ok[/]",
    Status.WARN: "[yellow]aviso[/]",
    Status.FAIL: "[red]falha[/]",
    Status.SKIP: "[dim]pulado[/]",
}


def _load(config: Path) -> Settings:
    try:
        return load_settings(config)
    except (ConfigError, ValidationError) as exc:
        console.print(f"[red]Configuração inválida:[/] {exc}")
        raise typer.Exit(2) from exc


@app.command()
def run(
    config: ConfigOption = Path("config.yaml"),
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Não envia email nem grava estado; salva preview.html.")] = False,
    no_llm: Annotated[bool, typer.Option("--no-llm", help="Só embeddings, sem LLM.")] = False,
    limit: Annotated[int | None, typer.Option("--limit", min=1, help="Limita vagas processadas (debug).")] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
) -> None:
    """Pipeline completo."""
    settings = _load(config)
    log_file = setup_logging(settings.logs_dir, verbose=verbose)
    log = get_logger()
    log.info("Execução iniciada (dry_run=%s, no_llm=%s, limit=%s). Log: %s", dry_run, no_llm, limit, log_file)
    try:
        run_pipeline(settings, RunOptions(dry_run=dry_run, no_llm=no_llm, limit=limit))
    except (ConfigError, CVError, StorageError, EmbedderUnavailable) as exc:
        log.error("%s", exc)
        raise typer.Exit(1) from exc


@app.command()
def doctor(
    config: ConfigOption = Path("config.yaml"),
    no_smtp: Annotated[bool, typer.Option("--no-smtp", help="Não testar login SMTP.")] = False,
) -> None:
    """Checa env, Ollama no ar, modelos baixados e SMTP."""
    settings = _load(config)
    checks = run_checks(settings, smtp=not no_smtp)

    table = Table(title="vagas-pj-bot · doctor")
    table.add_column("Item")
    table.add_column("Status")
    table.add_column("Detalhe", overflow="fold")
    for check in checks:
        table.add_row(check.name, _STATUS_STYLE[check.status], check.detail)
    console.print(table)

    if any(c.status is Status.FAIL for c in checks):
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
