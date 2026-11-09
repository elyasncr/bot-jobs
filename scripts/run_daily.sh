#!/usr/bin/env bash
# vagas-pj-bot — execução diária (cron no Linux/macOS).
# Garante o Ollama no ar, roda o bot e grava a saída em logs/YYYY-MM-DD.log.
# Argumentos extras são repassados ao "run" (ex.: scripts/run_daily.sh --force).
# Cron (dias úteis, 11h):  0 11 * * 1-5 /caminho/para/vagas-pj-bot/scripts/run_daily.sh
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 1
mkdir -p logs
LOG="$ROOT/logs/$(date +%F).log"
OLLAMA_URL="${OLLAMA_URL:-http://localhost:11434}"
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:/usr/local/bin:/opt/homebrew/bin:$PATH"
export PYTHONIOENCODING=utf-8 COLUMNS=200

log() { echo "$(date '+%F %T') [run_daily] $*" >> "$LOG"; }
ollama_up() { curl -sf -m 3 "$OLLAMA_URL/api/version" > /dev/null 2>&1; }

if ! ollama_up; then
    log "Ollama não responde em $OLLAMA_URL; iniciando 'ollama serve'..."
    nohup ollama serve > /dev/null 2>&1 &
    for _ in $(seq 1 15); do ollama_up && break; sleep 2; done
    if ollama_up; then log "Ollama no ar."; else log "AVISO: Ollama não respondeu em 30 s; o bot tenta mesmo assim."; fi
fi

log "Iniciando: uv run python -m vagas_bot run $*"
uv run python -m vagas_bot run "$@" >> "$LOG" 2>&1
code=$?
log "Fim (código de saída $code)."
exit "$code"
