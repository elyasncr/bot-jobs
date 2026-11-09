# Dashboard local — plano de implementação

> Execução: inline, tarefa por tarefa, com TDD na parte Python. Passos marcados com `- [ ]`.

**Objetivo:** tela Angular local para navegar pelas vagas capturadas, analisar o benchmark de LLMs e gravar notas manuais. Spec: `docs/superpowers/specs/2026-11-09-dashboard-design.md`.

**Arquitetura:** `vagas_bot dashboard` (stdlib `ThreadingHTTPServer`, 127.0.0.1) serve `dashboard/dist/` e uma API JSON montada por funções puras em `src/vagas_bot/dashboard/data.py`. As métricas reutilizam `evaluation.py` e `eval_report.py`.

**Stack:** Python 3.12 (stdlib + pacotes atuais do projeto), Angular 22 (standalone, signals, Vitest), CSS próprio.

---

## Mapa de arquivos

| Arquivo | Responsabilidade |
|---|---|
| `src/vagas_bot/evaluation.py` (mod.) | `remove_label(path, job_id) -> bool` |
| `src/vagas_bot/dashboard/__init__.py` | pacote |
| `src/vagas_bot/dashboard/data.py` | `job_rows`, `benchmark_runs`, `benchmark_payload`, `find_job`, `save_label`, `DashboardError` |
| `src/vagas_bot/dashboard/server.py` | `find_dist`, `make_server`, handler (rotas, estáticos, SPA fallback) |
| `src/vagas_bot/__main__.py` (mod.) | comando `dashboard` |
| `tests/test_dashboard.py` | data + servidor real |
| `dashboard/` | app Angular (`ng new`) |
| `dashboard/src/app/core/models.ts` | interfaces da API |
| `dashboard/src/app/core/api.service.ts` | 4 chamadas HTTP |
| `dashboard/src/app/jobs/job-filters.ts` | filtro/ordenação puros |
| `dashboard/src/app/jobs/{jobs-page,jobs-table,job-detail}.ts` | tela Vagas |
| `dashboard/src/app/shared/{label-input,score-badge}.ts` | campo de nota, badge de faixa |
| `dashboard/src/app/benchmark/{benchmark-page,benchmark-summary,score-chart}.ts` | tela Benchmark |
| `.gitignore`, `README.md` (mod.) | `dashboard/node_modules/`, `dashboard/dist/`, `dashboard/.angular/`; docs |

## Tarefas

### Tarefa 1: `remove_label`
- [ ] Teste em `tests/test_evaluation.py`: `ensure_label_entries` com 2 vagas, depois `set_label` em uma e `remove_label` nela → `load_labels == {}`, o comentário da outra é preservado e a função retorna `True`. `remove_label` de um id inexistente → `False`.
- [ ] Implementar reescrevendo com o mesmo formato de `set_label` (extrair `_write_labels(path, entries, comments)` e usar nas duas).
- [ ] `uv run pytest tests/test_evaluation.py -q` → passa.

### Tarefa 2: `job_rows`
- [ ] Testes (`tests/test_dashboard.py`):
  - registros do arquivo: a versão mais recente por `id` vence; `stage`, `filter_reason`, `scores`, `strengths` e `summary` vêm de `score`; `total = score.total`; `is_estimate=False`;
  - sem `score` e com `embedding_score`: `is_estimate=True`, com `total` min-max dentro do mesmo `run_date`;
  - histórico ausente do arquivo: `stage="history"`, descrição a partir do `job_text`, notas parciais do registro;
  - `data/eval/jobs` ausente de ambos: `stage="benchmark"`, `total=None`;
  - `my_score` e `my_note` vêm do `labels.yaml`; `modality` sai de `detect_modality`;
  - ordem: `run_date` decrescente e, dentro dele, `total` decrescente (None por último).
- [ ] Implementar `job_rows(settings) -> list[dict]`.
- [ ] Testes passam.

### Tarefa 3: benchmark e notas
- [ ] Testes:
  - `benchmark_runs` lista `eval_*.json` do mais novo para o mais antigo, com `models` e `jobs`;
  - `benchmark_payload(settings, None)` usa o mais recente;
  - `summaries[i]` bate com `summarize` (`mean_s`, `spearman_gold`), há `reading` e há `jobs[].models[m].totals` por rodada;
  - `run` com `..` ou que não começa com `eval_` → `DashboardError` com status 404;
  - `save_label`: nota válida grava e cria o snapshot; `None` remove; 101 → 400; id desconhecido → 404.
- [ ] Implementar `DashboardError(status:int, message:str)`, `benchmark_runs`, `benchmark_payload`, `find_job` (arquivo → snapshots → histórico) e `save_label`.
- [ ] Testes passam.

### Tarefa 4: servidor
- [ ] Testes com servidor real (`make_server(settings, dist, port=0)` em thread, `urllib.request`):
  - `GET /api/jobs` → 200 com lista;
  - `GET /api/benchmark/runs`;
  - `GET /api/benchmark?run=../x` → 404 JSON;
  - `PUT /api/labels/<id quoted>` com JSON → 200; corpo inválido → 400;
  - `GET /` e `GET /vagas` → `index.html`;
  - `GET /main.js` → o arquivo, com content-type JS;
  - `GET /../config.yaml` → nunca sai do `dist`;
  - rota `/api/x` desconhecida → 404 JSON.
- [ ] Implementar `find_dist(root)` (primeira pasta `dashboard/dist/*/browser` com `index.html`) e `make_server`. O handler é um `BaseHTTPRequestHandler` com `log_message` silencioso e um `Cache-Control: no-store` na API.
- [ ] Testes passam.

### Tarefa 5: comando `dashboard`
- [ ] Teste: sem o `dist` → código 1 e a mensagem contém `npm ci && npm run build`.
- [ ] Implementar `dashboard(--config, --port 8765, --no-browser)`: `serve_forever` com `KeyboardInterrupt` tratado.
- [ ] Rodar a suíte inteira; commit "feat: API local do dashboard".

### Tarefa 6: scaffold Angular
- [ ] Conferir as opções atuais: `npx -y @angular/cli@22 new --help`.
- [ ] `npx -y @angular/cli@22 new dashboard --style=css --ssr=false --skip-git --routing` (zoneless e Vitest são padrão no 22; confirmar pelo help).
- [ ] `proxy.conf.json` (`/api` → `http://127.0.0.1:8765`); `npm start` = `ng serve --proxy-config proxy.conf.json`.
- [ ] `.gitignore` da raiz: `dashboard/node_modules/`, `dashboard/dist/`, `dashboard/.angular/`.
- [ ] `npm run build` e `npm test` passam no app vazio.

### Tarefa 7: `models.ts` e `api.service.ts`
- [ ] Interfaces `JobRow`, `BenchmarkRun`, `BenchmarkPayload`, `ModelSummary`, `BenchJob`, `LabelResult`, idênticas à spec.
- [ ] `ApiService`: `jobs()`, `benchmarkRuns()`, `benchmark(run?)` e `saveLabel(id, score|null, note)`. O `PUT` usa `encodeURIComponent(id)`.
- [ ] Spec com `HttpTestingController`: URL, método e corpo de cada chamada.

### Tarefa 8: `job-filters.ts` (puro)
- [ ] Tipo `JobFilters {q, stages[], reasons[], sources[], contracts[], minScore, maxScore, from, to, unlabeled}` e `SortKey` (`date|total|cosine|mine`) com `dir`.
- [ ] `applyFilters(rows, f)`, `sortRows(rows, key, dir)`, `countsBy(rows)`, `filtersFromParams(params)` e `filtersToParams(f)`.
- [ ] Spec: cada filtro isolado, combinação, ordenação com nulos por último e ida e volta dos params.

### Tarefa 9: componentes compartilhados
- [ ] `score-badge` (input `total`, `estimate`): classe da faixa (≥80 alta, 65–79 boa, 50–64 possível, <50 baixa).
- [ ] `label-input` (input `value: number|null`; output `save: number|null`): aceita vazio (apaga) ou inteiro de 0 a 100; emite no Enter ou ao sair do campo só se o valor mudou; estados `saving`, `saved` e `error` controlados pelo pai via inputs. Spec da validação e da emissão.

### Tarefa 10: tela Vagas
- [ ] `jobs-page`: carrega `jobs()`, guarda os filtros em signals sincronizados com os query params, mostra contadores, `job-filters-bar` (inline no page), `jobs-table` e `job-detail` (painel lateral, abre com `selectedId`).
- [ ] Salvar nota: chama `saveLabel` e atualiza a linha localmente (`my_score`/`my_note`); em erro, reverte e mostra a mensagem.

### Tarefa 11: tela Benchmark
- [ ] `benchmark-page`: seletor de run (`benchmarkRuns`), `benchmark-summary` (tabela + melhor valor por coluna + leitura), `score-chart` (SVG) e a tabela lado a lado com `label-input`. Após salvar, recarrega `benchmark(run)`.
- [ ] `score-chart`: uma linha por vaga, eixo de 0 a 100, círculo por modelo (paleta fixa de 6 cores) e losango para "você"; legenda.

### Tarefa 12: shell e tema
- [ ] `app.ts`: cabeçalho com nav (Vagas, Benchmark) e o aviso global de erro (signal em `ApiService.lastError`).
- [ ] `styles.css`: tokens em `:root`, dark mode por `prefers-color-scheme`, tabela responsiva (rolagem horizontal só na tabela) e painel lateral virando tela cheia abaixo de 720 px.

### Tarefa 13: verificação ponta a ponta
- [ ] `npm run build` → `uv run python -m vagas_bot dashboard --no-browser` em segundo plano → `curl` nas rotas → captura de tela headless de `/vagas` e `/benchmark` → conferir visualmente.
- [ ] Gravar uma nota real pela API, conferir o `labels.yaml` e reverter.

### Tarefa 14: docs e commit
- [ ] README: seção "Dashboard" (build, uso, desenvolvimento).
- [ ] `uv run pytest -q`, `npm test` e `npm run build` passam; auditoria de arquivos sensíveis; commit "feat: dashboard Angular (vagas e benchmark)" e push.
