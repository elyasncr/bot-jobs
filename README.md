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
uv run python -m vagas_bot run --dry-run     # não envia email nem grava estado; gera preview.html
uv run python -m vagas_bot run               # pipeline completo
uv run pytest                                # testes (sem chamadas reais)
```

## Status

- [x] Fase 1 — Esqueleto (config, modelos, CLI, `doctor`)
- [x] Fase 2 — Fonte JSearch (endpoint `/search-v2`; cota gratuita: 200 req/mês)
- [x] Fase 3 — Dedupe, filtros, regex PJ, estado
- [x] Fase 4 — Embeddings (Ollama)
- [x] Fase 5 — Scorer Ollama + histórico
- [ ] Fase 6 — Email
- [ ] Fase 7 — Agendamento local
