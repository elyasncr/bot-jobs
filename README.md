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

Cada execução real (sem `--dry-run`) anexa a `data/jobs.jsonl` **todas** as vagas novas, com a etapa em que pararam (`filtered` + motivo, `evaluated`, `emailed`) e as notas. Esse arquivo não é versionado.

## Comparação de modelos (Fase 8)

```powershell
uv run python -m vagas_bot eval-snapshot                    # salva 15 vagas em data/eval/jobs/ (5 req. da JSearch, janela de 1 mês)
uv run python -m vagas_bot eval-snapshot --from-archive     # idem, a partir de data/jobs.jsonl (sem gastar cota)
uv run python -m vagas_bot eval-models qwen3.5:9b qwen3:14b gemma4:12b   # 2 rodadas por vaga → eval_report.md
uv run python -m vagas_bot eval-report                      # regera o relatório (ex.: depois de preencher labels.yaml)
```

O relatório mostra, por modelo: tempo por vaga, tempo de carga, VRAM, taxa de JSON inválido, variação da nota entre as rodadas, respostas "CLT" sem evidência no texto e as notas lado a lado. Para medir a qualidade **contra você**, preencha `score` (0–100) em `data/eval/labels.yaml` e rode `eval-report`: entra a correlação de Spearman entre cada modelo e as suas notas, sem chamar os modelos de novo. Os resultados brutos ficam em `data/eval/results/`. O `config.yaml` nunca é alterado: a troca de modelo é manual.

## Embeddings: sentence-transformers e fine-tuning (Fase 9, opcional)

```powershell
uv sync --extra st                    # PyTorch 2.15 com CUDA 13.2 (RTX 50xx/Blackwell exige CUDA 12.8+), ~3 GB
uv run python -m vagas_bot doctor     # deve mostrar "torch ..., GPU: NVIDIA ..."
uv run python -m vagas_bot label      # mostra vagas do histórico e pede sua nota (gold) → data/eval/labels.yaml
uv run python -m vagas_bot finetune-embeddings --base BAAI/bge-m3 --out models/bge-m3-elyas-v1
uv run python -m vagas_bot eval-embeddings ollama/bge-m3 st/BAAI/bge-m3 st/models/bge-m3-elyas-v1
```

Atenção: um `uv sync` sem `--extra st` **desinstala** o PyTorch; o `uv run` não mexe nele.

- **Dados:** pares (CV, vaga, nota). *Silver* vem do `history.jsonl` (nota do LLM); *gold* são as suas notas, dadas pelo `label`. O split é por vaga (a mesma vaga nunca cai em treino e validação), e as notas gold vão para a validação até haver 150 delas.
- **Mínimo para treinar:** 300 pares silver e 40 gold. Abaixo disso o comando recusa, a não ser com `--force`.
- **Resultado:** `finetune-embeddings` salva o modelo em `models/` com um `training_meta.json` e gera o `finetune_report.md` (base × fine-tunado: Spearman contra as suas notas e contra o LLM, recall@top_n).
- **Regra de troca:** a recomendação só manda trocar se o Spearman gold melhorar pelo menos 0,05 **e** o recall não piorar.
- **Como usar o fine-tunado:** troque você mesmo no `config.yaml`: `embeddings.provider: sentence-transformers`, `sentence_transformers.model: models/bge-m3-elyas-v1` e `cv_representation: compact`.

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
- [x] Fase 8 — Comparação de modelos (`eval-models`)
- [x] Fase 9 — Embeddings com sentence-transformers + fine-tuning (`label`, `finetune-embeddings`, `eval-embeddings`)
