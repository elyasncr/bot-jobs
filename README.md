# vagas-pj-bot

Bot diário que coleta vagas de IA/ML/Dados, filtra as PJ, pontua a aderência ao currículo com um LLM local (Ollama) e envia um email HTML. Especificação completa em [SPEC.md](SPEC.md).

## Setup

```powershell
uv sync                         # instala dependências (Python 3.12)
copy .env.example .env          # preencha RAPIDAPI_KEY, GMAIL_USER, GMAIL_APP_PASSWORD, EMAIL_TO
ollama pull qwen3.5:9b          # LLM padrão (config.yaml → llm.ollama.model)
ollama pull bge-m3              # embeddings (config.yaml → embeddings.ollama.model)
```

O currículo fica em `data/cv.md` (seções separadas por `##`). Ele **não é versionado**: copie [data/cv.example.md](data/cv.example.md) para `data/cv.md` e preencha.

## Uso

```powershell
uv run python -m vagas_bot doctor            # checa env, Ollama, modelos e SMTP
uv run python -m vagas_bot test-email        # envia um email de teste com 3 vagas fictícias
uv run python -m vagas_bot run --dry-run     # não envia email nem grava estado; gera preview.html
uv run python -m vagas_bot run               # pipeline completo (1 execução bem-sucedida por dia)
uv run python -m vagas_bot run --force       # roda de novo no mesmo dia
uv run pytest                                # testes (sem chamadas reais)
```

## Agendamento (dias úteis, 11h)

O script [scripts/run_daily.ps1](scripts/run_daily.ps1) entra na pasta do projeto, inicia o `ollama serve` se o Ollama não responder (espera até 30 s), roda o bot e grava tudo em `logs/YYYY-MM-DD.log`. Uma trava em `data/.last_run` impede duas execuções bem-sucedidas no mesmo dia.

**Windows (Agendador de Tarefas):**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install_task.ps1               # 11h; outro horário: -Time 09:30
Start-ScheduledTask -TaskName vagas-pj-bot                                     # testar agora
Unregister-ScheduledTask -TaskName vagas-pj-bot -Confirm:$false                # remover
```

A tarefa é criada com a opção **"Executar a tarefa assim que possível após uma inicialização agendada ter sido perdida"**: se o PC estava desligado às 11h, ela roda quando ele ligar. Pela interface: Agendador de Tarefas → Criar Tarefa → Disparadores: Semanalmente, seg–sex, 11:00 → Ações: `powershell.exe` com `-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "<projeto>\scripts\run_daily.ps1"` → Configurações: marcar a opção acima.

**Linux/macOS (cron):** `crontab -e` e adicione

```
0 11 * * 1-5 /caminho/para/vagas-pj-bot/scripts/run_daily.sh
```

## Status

- [x] Fase 1 — Esqueleto (config, modelos, CLI, `doctor`)
- [x] Fase 2 — Fonte JSearch (endpoint `/search-v2`; cota gratuita: 200 req/mês)
- [x] Fase 3 — Dedupe, filtros, regex PJ, estado
- [x] Fase 4 — Embeddings (Ollama)
- [x] Fase 5 — Scorer Ollama + histórico
- [x] Fase 6 — Email
- [x] Fase 7 — Agendamento local (dias úteis, 11h)
