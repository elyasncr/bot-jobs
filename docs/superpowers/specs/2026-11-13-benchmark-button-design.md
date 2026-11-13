# Botão "Rodar benchmark" no dashboard

Data: 2026-11-13 · Status: aprovado no chat, aguardando revisão desta spec

## Objetivo

Hoje a tela Benchmark mostra só a comparação gerada por `eval-models` na linha de comando, sobre um conjunto
fixo de vagas (`data/eval/jobs/`, salvo em 09/11). As vagas que o bot diário captura depois nunca entram.
Queremos um botão na tela Benchmark que, com um clique:

1. inclua no conjunto do benchmark as vagas novas do bot diário (as que chegaram a ser avaliadas pelo LLM);
2. rode a comparação nos modelos escolhidos;
3. mostre o andamento e, ao terminar, exiba a rodada nova.

Fora do escopo: limitar o tamanho do conjunto, cancelar uma rodada em andamento, sobreviver a uma queda do
dashboard no meio da rodada, agendar rodadas.

## Decisões (do chat)

- O botão **inclui as vagas novas e roda** (não há botão separado para só incluir).
- Os modelos são escolhidos em **caixas de seleção** com os modelos instalados no Ollama.
- Abordagem: a rodada roda **dentro do servidor do dashboard, numa thread**, chamando as mesmas funções da
  linha de comando (não um subprocesso nem tarefa agendada).

## Backend

### `vagas_bot/eval_runner.py` (novo)

O miolo hoje dentro dos comandos `eval-snapshot --from-archive` e `eval-models` sai do `__main__.py` para cá,
para ser usado pela linha de comando e pelo dashboard. Os comandos mantêm o comportamento atual.

- `add_archive_jobs(settings, n: int | None = None) -> AddResult`
  Lê `data/jobs.jsonl`, pega as vagas com etapa `evaluated` ou `emailed` e grava em `data/eval/jobs/` as que
  ainda não estão lá (`save_eval_jobs` já ignora as existentes). `n=None` (dashboard) inclui **todas** as novas;
  um número (linha de comando, padrão 15) mantém a escolha diversificada de hoje (`pick_diverse`). Depois chama
  `ensure_label_entries`. Retorna `AddResult(added: int, total: int, new_labels: int)`.
- `pending_archive_jobs(settings) -> int`
  Quantas vagas avaliadas/enviadas do arquivo ainda não estão no conjunto (para o aviso do painel).
- `run_benchmark(settings, models, runs=2, on_progress=None) -> Path`
  Carrega o conjunto e o CV, chama `evaluation.run_models`, salva em `data/eval/results/` e regera o
  `eval_report.md` (a função `_write_report` do `__main__.py` vem para cá). Retorna o caminho do resultado.
  Erros de pré-condição (conjunto vazio, CV ausente) viram `EvalRunnerError` com mensagem em português;
  a linha de comando imprime e sai com código 1, o dashboard mostra no painel.

### `evaluation.py`

- `run_models(..., on_progress=None)` e `evaluate_model(..., on_progress=None)`: callback opcional
  `on_progress(model: str, done: int, total: int)` chamado após cada tentativa (`total = rodadas × vagas`
  do modelo atual). Um modelo indisponível também conta como concluído (o callback é chamado com `done = total`),
  para a barra não travar.

### `ollama_utils.py`

- `list_models(host, timeout_s=5.0) -> list[OllamaModel]` via `GET /api/tags`: `name` e `family`.

### `dashboard/benchmark_job.py` (novo)

`BenchmarkJob`: uma rodada por vez por processo do dashboard.

- `start(models) -> None`: com uma trava, recusa se já houver rodada (`DashboardError(409, ...)`); senão marca
  `running` e dispara uma thread daemon que faz `add_archive_jobs(settings)` e `run_benchmark(...)`.
- `status() -> dict`: cópia do estado, protegida pela trava.
- Estado: `state` (`idle` | `running` | `done` | `error`), `phase` (`adding` | `running`), `models`,
  `current_model`, `model_index` (1-based), `model_count`, `done`, `total`, `added`, `started_at`,
  `finished_at`, `result_file` (nome do arquivo em `data/eval/results/`), `error`.
- Qualquer exceção na thread vira `state = error` com a mensagem, e vai para o log do dashboard.
- O estado vive só na memória: se o dashboard reiniciar, volta a `idle` e a rodada se perde. Como o resultado
  só é gravado no fim, nada fica pela metade em disco.
- A função de trabalho (`add` + `run`) é injetável, para os testes não precisarem do Ollama.

### API (`dashboard/server.py` e `dashboard/data.py`)

- `GET /api/benchmark/models` → `{"models": [{"name", "default", "warning"}], "pending_jobs": int,
  "total_jobs": int}`.
  - Lista os modelos do Ollama, **sem os de embedding**: família `bert`/`nomic-bert` ou nome igual ao modelo de
    embeddings do `config.yaml`.
  - `default`: estava na última rodada salva (se não houver rodada, o modelo LLM do `config.yaml`).
  - `warning`: texto para modelos sabidamente instáveis nesta máquina (`gpt-oss` → "Derruba o Ollama nesta GPU");
    esses nunca vêm marcados por padrão.
  - Ollama fora do ar → 503 com mensagem "Ollama indisponível".
- `POST /api/benchmark/run` com `{"models": ["..."]}` → 202 com o status.
  - 400 se a lista estiver vazia, tiver item que não é texto ou modelo que não está na lista acima.
  - 409 se já houver rodada em andamento.
  - Mesma autorização do `PUT` de notas (código de acesso na rede de casa; livre no próprio PC).
- `GET /api/benchmark/status` → o estado do `BenchmarkJob`.
- O servidor ganha `do_POST`. O `BenchmarkJob` é criado uma vez em `make_server` e compartilhado pelos handlers.

## Tela Benchmark (Angular)

- Botão **"Rodar benchmark"** no topo da tela. Ao clicar, abre um painel (mesmo estilo dos menus de filtro) com:
  - caixas dos modelos (marcadas conforme `default`; aviso em amarelo abaixo dos que têm `warning`);
  - texto "X vagas novas serão incluídas · N no total" (`pending_jobs`, `total_jobs + pending_jobs`);
  - botão "Rodar" (desabilitado sem modelo marcado).
- Rodando: o botão do topo vira "Rodando…" desabilitado e aparece uma faixa de progresso:
  "Incluindo vagas novas…" e depois "gemma4:12b (2/3) · 34/46" com barra.
  A tela consulta `GET /api/benchmark/status` a cada 3 s enquanto `running`.
- Ao abrir a tela, consulta o status uma vez: se houver rodada em andamento (iniciada por outra aba ou pelo
  celular), retoma o acompanhamento.
- Ao terminar (`done`): recarrega a lista de rodadas e seleciona `result_file`. Em `error`: mostra a mensagem
  na faixa, com botão para fechar.
- `ApiService`: `benchmarkModels()`, `startBenchmark(models)`, `benchmarkStatus()`; interfaces em `models.ts`.

## Pontos de atenção

- O conjunto só cresce (~4 vagas enviadas por dia → ~100 em um mês → ~30 min por rodada com 3 modelos).
  O painel mostra o total antes de rodar; limitar fica para depois, se incomodar.
- Rodar junto com o bot das 11:00 deixa os dois mais lentos (disputam a GPU), mas funciona.

## Testes

- pytest:
  - `eval_runner`: `add_archive_jobs` inclui só avaliadas/enviadas novas, não duplica, respeita `n`;
    `pending_archive_jobs`; `run_benchmark` com scorer falso grava o resultado e o relatório; erros de
    pré-condição.
  - `evaluation`: `on_progress` chamado com a contagem certa, inclusive para modelo indisponível.
  - `ollama_utils.list_models` com transporte falso.
  - `BenchmarkJob`: estados `running → done` e `running → error`, 409 na segunda chamada, progresso refletido
    no status.
  - Servidor: as três rotas (modelos filtrados e `default`, 400/409/202, autorização do POST na rede).
  - Linha de comando: `eval-snapshot --from-archive` e `eval-models` continuam passando nos testes existentes.
- Vitest: as três chamadas novas do `ApiService` e os cálculos puros do painel (texto de progresso, modelos
  marcados por padrão).
