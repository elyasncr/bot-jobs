# Dashboard local (Angular) — vagas capturadas e benchmark de modelos

Data: 2026-11-09 · Status: aprovado

## Objetivo

Uma tela local para:

1. navegar por **todas as vagas capturadas** pelo bot (inclusive as filtradas, com o motivo);
2. **analisar o benchmark** dos LLMs (`eval-models`);
3. **dar notas manuais** (0–100) às vagas. As notas gravam em `data/eval/labels.yaml` e alimentam o Spearman "você × modelo" e o fine-tuning (Fase 9).

Fora de escopo: acompanhamento de candidaturas (status "candidatei", "descartada" etc.), autenticação, acesso por outras máquinas e edição do `config.yaml`.

## Arquitetura

```
navegador ──HTTP──► vagas_bot dashboard (http.server, 127.0.0.1:8765)
                     ├── /            → dashboard/dist/<app>/browser (SPA, fallback index.html)
                     └── /api/*       → src/vagas_bot/dashboard/data.py
                                          lê  data/jobs.jsonl, data/history.jsonl,
                                              data/eval/jobs/, data/eval/results/*.json
                                          grava data/eval/labels.yaml, data/eval/jobs/
```

- Sem dependências Python novas: `http.server.ThreadingHTTPServer` da biblioteca padrão.
- O servidor escuta só em `127.0.0.1`. Nada é exposto na rede.
- O cálculo das métricas reaproveita `evaluation.summarize`, `evaluation.agreement`, `eval_report.reading`, `evaluation.set_label` e `archive.load_archive`. A tela mostra exatamente os mesmos números do `eval_report.md`.

### Comando

`uv run python -m vagas_bot dashboard [--port 8765] [--no-browser] [--config config.yaml]`

- Se `dashboard/dist/` não existir: sai com código 1 e a instrução `cd dashboard && npm ci && npm run build`.
- Abre o navegador (`webbrowser.open`), a não ser com `--no-browser`. Ctrl+C encerra.

### Desenvolvimento da tela

`cd dashboard && npm start` (`ng serve` com `proxy.conf.json` apontando `/api` para `http://127.0.0.1:8765`), com `vagas_bot dashboard --no-browser` rodando ao lado.

## API

Todas as respostas são JSON (UTF-8). Erros: `{"error": "<mensagem em português>"}` com status 400, 404 ou 500.

### `GET /api/jobs`

Lista de `JobRow`, uma por vaga, na versão mais recente de cada `id`. Ordem: `run_date` decrescente, depois a nota decrescente.

```
JobRow {
  id, run_date (YYYY-MM-DD), stage: "emailed"|"evaluated"|"filtered"|"history"|"benchmark",
  filter_reason: "title"|"modality"|"clt"|"limit"|null,
  source, publisher, title, company, location, modality: "remote"|"hybrid"|"onsite"|"unknown",
  url, posted_at (ISO|null), low_fidelity, pj_status, description,
  embedding_score (float|null), total (int|null), is_estimate (bool),
  scores: {technical, seniority, domain, modality_contract, language} | null,
  strengths: [], gaps: [], summary (str|null), llm_model (str|null),
  my_score (int|null), my_note (str)
}
```

**Origem dos dados:**

- `data/jobs.jsonl`: arquivo de vagas, gravado desde a Fase 8.
- Importação inicial: vagas do `data/history.jsonl` ausentes do arquivo entram com `stage="history"`. A descrição sai do `job_text`, e as notas parciais e o total vêm do registro. Não há pontos fortes nem resumo.
- Vagas de `data/eval/jobs/` ausentes de ambos entram com `stage="benchmark"` e sem nota.
- `modality` é calculada por `filters.detect_modality`.
- `is_estimate` é verdadeiro quando há `embedding_score` mas não há nota do LLM. Nesse caso, `total` é a estimativa min-max do lote do mesmo `run_date` (`ranker.estimate_totals`).

### `GET /api/benchmark/runs`

`[{file: "eval_20261109_135215.json", date, models: [...], jobs: N}]`, do mais recente para o mais antigo.

### `GET /api/benchmark?run=<file>`

Sem `run`, usa o mais recente; `404` se não houver nenhum. O nome de arquivo é validado: só nomes `eval_*.json` dentro de `data/eval/results/`.

```
{
  meta: {...do arquivo...},
  summaries: [ModelSummary sem mean_totals, + invalid_rate, fail_rate, agreement_with_ref],
  reading: ["…linhas da leitura automática…"],
  jobs: [{id, title, company, url, clt_signals, my_score,
          models: {<model>: {totals: [int|null por rodada], pj_status: [..], mean: float|null}}}]
}
```

As notas são recalculadas a cada requisição com o `labels.yaml` atual.

### `PUT /api/labels/{id}`

Corpo `{"score": 0–100 | null, "note": "texto opcional"}`. O `id` vem codificado na URL.

- `score` inteiro de 0 a 100: grava com `set_label` e salva o snapshot da vaga em `data/eval/jobs/` (se ainda não existir), como o comando `label`. A vaga é procurada no arquivo, no histórico ou nos snapshots; `404` se não for encontrada.
- `score: null`: remove a entrada do `labels.yaml` (nova função `evaluation.remove_label`).
- Corpo inválido ou nota fora da faixa: `400`.
- Resposta: `{id, my_score, my_note}`.

## Telas

Interface em português, tema claro e escuro (`prefers-color-scheme`), layout responsivo e cores das faixas iguais às do email (≥80 verde, 65–79 azul, 50–64 amarelo).

### Vagas (`/vagas`, rota padrão)

- **Contadores**, com os filtros aplicados: capturadas, enviadas, avaliadas, filtradas (por motivo) e com nota minha.
- **Filtros:** busca (título ou empresa), etapa, motivo do descarte, fonte, contrato, faixa de nota (mínimo e máximo), período (de/até pelo `run_date`) e "sem nota minha". Os filtros ficam na URL (query params).
- **Tabela** ordenável por data, nota, cosseno e sua nota. Colunas: data, título (link para a vaga), empresa, local · modalidade, fonte, contrato, nota do LLM (badge da faixa, ou "estimativa"), cosseno, **sua nota** (`label-input` inline) e etapa.
- **Detalhe:** clicar na linha abre um painel lateral com a descrição completa, resumo, pontos fortes e lacunas, as 5 notas parciais em barras horizontais, nota e comentário editáveis e os metadados (modelo, publisher, data de publicação).

### Benchmark (`/benchmark`)

- **Seletor** do resultado (padrão: o mais recente).
- **Tabela de resumo:** as mesmas colunas do `eval_report.md`, com o melhor valor de cada coluna destacado, mais a lista "Leitura automática".
- **Gráfico** (SVG próprio): uma linha por vaga, com um ponto por modelo na escala de 0 a 100 (cor por modelo) e a sua nota como marcador.
- **Notas lado a lado:** tabela por vaga com as notas de cada rodada, o pj_status (⚠ quando é CLT sem evidência) e **sua nota** editável. Salvar uma nota recarrega o benchmark, e o Spearman muda na hora.

## Front-end

- Angular 22, componentes standalone, signals, `HttpClient`, roteamento com lazy loading. Sem Angular Material e sem bibliotecas de gráfico.
- `dashboard/` na raiz do repositório. `node_modules/` e `dist/` ficam no `.gitignore`.
- Unidades:
  - `core/api.service.ts`: as 4 chamadas da API;
  - `core/models.ts`: interfaces espelhando a API;
  - `jobs/job-filters.ts`: lógica pura de filtro e ordenação, testável;
  - `jobs/jobs-page`, `jobs/jobs-table`, `jobs/job-detail`;
  - `shared/label-input`: valida de 0 a 100 e emite ao confirmar com Enter ou ao sair do campo, com estados salvando, salvo e erro;
  - `shared/score-badge`;
  - `benchmark/benchmark-page`, `benchmark/benchmark-summary`, `benchmark/score-chart`.
- **Erros:** falha da API exibe um aviso no topo com a mensagem. Uma nota não salva volta ao valor anterior e mostra o erro no campo.

## Testes

- **Python** (`tests/test_dashboard.py`):
  - montagem do `JobRow` (mesclagem com as notas, importação do histórico e do benchmark, versão mais recente por id, estimativa);
  - payload do benchmark igual a `summarize`;
  - `remove_label`;
  - servidor real numa porta livre, em thread: rotas GET, `PUT` válido, inválido e com 404, path traversal no `run` e nos arquivos estáticos recusado, fallback do SPA, e `dist` ausente gerando a mensagem do comando.
- **Angular** (Vitest, padrão do Angular 22): `job-filters` (cada filtro e a ordenação), `label-input` (validação e emissão) e `ApiService` (`HttpTestingController`).

## Riscos e decisões

- O `data/jobs.jsonl` começou na Fase 8. O histórico anterior tem só as vagas avaliadas pelo LLM, e as filtradas antes disso se perderam.
- O cálculo das métricas fica no Python, não é reimplementado no TypeScript, para não haver duas versões do Spearman.
- O `labels.yaml` é reescrito no formato padrão a cada nota salva, como no comando `label`. Comentários manuais fora desse formato se perdem.
