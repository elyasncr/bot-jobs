# SPEC — Bot de Vagas PJ (vagas-pj-bot)

> Documento de especificação para implementação com o Claude Code.
> Dono: Elyas Ribeiro. Idioma do código: inglês. Idioma de logs, email e prompts ao LLM: português.
> **v3:** LLM e embeddings 100% locais via Ollama (custo zero), execução local agendada. Providers plugáveis: Claude via API (LLM) e sentence-transformers (embeddings, com fine-tuning opcional nas minhas próprias avaliações).

## 1. Objetivo

Um bot que roda diariamente na minha máquina, coleta vagas (prioridade: LinkedIn) da área de IA/ML/Dados, filtra as que são **PJ** (ou aceitam PJ), calcula um **% de aderência ao meu currículo** com um LLM local e me envia **um email HTML** com as vagas novas ordenadas por esse %.

### Ambiente alvo
- PC pessoal com **NVIDIA RTX 5070 Ti (16 GB VRAM)**.
- Ollama instalado e rodando como serviço (`http://localhost:11434`).
- Custo recorrente: **zero** (JSearch plano gratuito, Ollama local, Gmail).

### Fora de escopo (v1)
- Candidatura automática.
- Scraping logado no LinkedIn com Selenium/Playwright (viola os termos do LinkedIn e arrisca bloqueio da conta). **Não implementar.**
- Interface web/dashboard.

## 2. Visão geral do pipeline

```
[Sources] → normalize → dedupe (seen.json) → hard filters → PJ regex
   → embedding pre-rank (Ollama, top N) → LLM scoring (Ollama) → rank → email HTML → persist state
```

Cada etapa é uma função pura sempre que possível, recebendo e devolvendo `list[Job]`, para facilitar testes.

## 3. Estrutura do projeto

```
vagas-pj-bot/
├── SPEC.md
├── README.md
├── pyproject.toml
├── config.yaml
├── .env.example
├── data/
│   ├── cv.md              # currículo em markdown (fonte única do perfil)
│   ├── seen.json          # estado: vagas já enviadas (não versionar)
│   ├── history.jsonl      # todas as vagas pontuadas (não versionar)
│   └── eval/
│       ├── jobs/          # snapshots de vagas para avaliação (JSON)
│       └── labels.yaml    # minhas notas manuais (gold labels)
├── models/                # modelos de embedding fine-tunados (não versionar)
├── logs/                  # um arquivo por execução (não versionar)
├── scripts/
│   ├── run_daily.ps1      # Windows (Agendador de Tarefas)
│   └── run_daily.sh       # Linux/macOS (cron)
├── src/vagas_bot/
│   ├── __init__.py
│   ├── __main__.py        # CLI (typer)
│   ├── config.py          # pydantic-settings: config.yaml + env
│   ├── models.py          # Job, ScoreResult, PJStatus
│   ├── storage.py         # leitura/escrita/poda de seen.json
│   ├── sources/
│   │   ├── base.py        # Protocol Source
│   │   ├── jsearch.py     # fonte principal
│   │   └── linkedin_alerts.py  # opcional
│   ├── filters.py         # hard filters + PJ regex
│   ├── embeddings/
│   │   ├── base.py        # Protocol Embedder + get_embedder(cfg)
│   │   ├── ollama.py      # provider padrão
│   │   └── st.py          # provider sentence-transformers (opcional)
│   ├── training/
│   │   ├── dataset.py     # monta pares (CV, vaga, nota) a partir do history + labels
│   │   └── finetune.py    # fine-tuning do embedding (Fase 9)
│   ├── scoring/
│   │   ├── prerank.py     # similaridade CV × vaga usando o Embedder
│   │   ├── prompts.py     # system prompt, rubrica, montagem do user prompt
│   │   ├── llm_base.py    # Protocol LLMScorer
│   │   ├── llm_ollama.py  # provider padrão
│   │   ├── llm_anthropic.py  # provider opcional
│   │   └── ranker.py
│   ├── evaluation.py      # comparação de modelos (Fase 8)
│   └── notify/
│       ├── email.py
│       └── templates/email.html.j2
└── tests/
    ├── fixtures/          # respostas JSON reais anonimizadas
    └── test_*.py
```

`.gitignore` deve incluir `.env`, `data/seen.json`, `data/history.jsonl`, `models/`, `logs/`, `preview.html`.

## 4. Stack

- Python 3.12, gerenciado com `uv`.
- `httpx` (HTTP), `pydantic` v2 + `pydantic-settings`, `typer` (CLI), `pyyaml`, `jinja2`, `tenacity` (retry), `rich` (logs).
- `ollama` (cliente Python oficial) para LLM **e** embeddings. **Sem torch e sem sentence-transformers** — tudo passa pelo Ollama, que já usa a GPU.
- Dependências **opcionais** (`[project.optional-dependencies]`), importadas só quando o provider correspondente estiver configurado:
  - `anthropic` → provider LLM `anthropic`.
  - `st` → `sentence-transformers`, `torch`, `datasets`, `scipy` → provider de embeddings `sentence-transformers` e fine-tuning.
- **PyTorch e RTX 5070 Ti (Blackwell):** só funciona com builds recentes do PyTorch compilados com CUDA 12.8 ou superior. Instalar pelo índice oficial do PyTorch com a variante CUDA correta (ex.: `--index-url https://download.pytorch.org/whl/cu128` ou mais novo, conforme a doc atual) e configurar isso no `pyproject.toml` via `[tool.uv.sources]`. O comando `doctor` deve verificar `torch.cuda.is_available()` e o nome da GPU quando o extra `st` estiver instalado.
- `pytest` + `respx` para mock de HTTP.
- Envio de email via `smtplib` (stdlib) com Gmail + senha de app.

## 5. Configuração

### 5.1 `config.yaml`

```yaml
search:
  queries:
    - "AI Engineer"
    - "Machine Learning Engineer"
    - "Engenheiro de IA"
    - "Engenheiro de Machine Learning"
    - "LLM Engineer"
    - "Generative AI Engineer"
    - "Cientista de Dados"
    - "Data Scientist"
    - "MLOps Engineer"
  country: "br"
  date_posted: "3days"        # today | 3days | week | month
  pages_per_query: 1
  publishers: ["LinkedIn"]    # [] = aceitar todos os publishers
  include_international_remote: true   # vagas contractor remotas fora do BR

filters:
  modalities: ["remote", "hybrid"]
  hybrid_allowed_cities: ["Rio de Janeiro"]
  exclude_title_keywords: ["estágio", "estagiário", "intern", "trainee", "júnior", "junior", "jr"]
  include_uncertain_contract: true    # vagas sem contrato explícito entram marcadas

embeddings:
  provider: "ollama"          # ollama | sentence-transformers
  top_n: 40                   # quantas vão para o LLM (local = sem custo, só tempo)
  cv_representation: "blocks_mean"   # blocks_mean | compact (usar compact com modelo fine-tunado)
  ollama:
    model: "bge-m3"           # multilíngue, sem prefixos especiais
  sentence_transformers:
    model: "BAAI/bge-m3"      # ou caminho local de um modelo fine-tunado, ex.: "models/bge-m3-elyas-v1"
    device: "cuda"            # cuda | cpu
    batch_size: 16
    query_prefix: ""          # para modelos e5: "query: "
    passage_prefix: ""        # para modelos e5: "passage: "

llm:
  provider: "ollama"          # ollama | anthropic
  max_calls_per_run: 60
  ollama:
    host: "http://localhost:11434"
    model: "qwen3.5:9b"       # ver seção 9.4 para alternativas
    num_ctx: 16384            # OBRIGATÓRIO: o padrão do Ollama trunca o prompt em silêncio
    temperature: 0
    think: false              # modo raciocínio; true = mais lento, às vezes mais preciso
    keep_alive: "10m"
    request_timeout_s: 180
  anthropic:
    model: "claude-haiku-5-5"

scoring:
  min_score_to_email: 50

email:
  send_when_empty: false
  max_jobs: 30

state:
  prune_after_days: 60
```

### 5.2 Variáveis de ambiente (`.env.example`)

```
RAPIDAPI_KEY=
GMAIL_USER=
GMAIL_APP_PASSWORD=
EMAIL_TO=
# Opcionais
OLLAMA_HOST=              # sobrescreve llm.ollama.host
ANTHROPIC_API_KEY=        # só se llm.provider = anthropic
```

Nenhum segredo vai para o repositório. Validar na inicialização só as variáveis exigidas pelos providers configurados (sem `ANTHROPIC_API_KEY` com provider `ollama` não é erro).

## 6. Modelo de dados (`models.py`)

```python
class PJStatus(str, Enum):
    PJ = "pj"            # explicitamente PJ / contractor
    BOTH = "both"        # aceita CLT ou PJ
    CLT = "clt"          # explicitamente só CLT → descartar
    UNCERTAIN = "uncertain"

class Job(BaseModel):
    id: str                       # id da fonte
    fingerprint: str              # sha1(normalize(title) + normalize(company))
    source: str                   # "jsearch", "linkedin_alerts"
    publisher: str | None         # "LinkedIn", "Indeed", ...
    title: str
    company: str
    location: str | None
    is_remote: bool | None
    employment_type: str | None
    description: str
    url: str
    posted_at: datetime | None
    low_fidelity: bool = False    # sem descrição completa
    pj_status: PJStatus = PJStatus.UNCERTAIN
    embedding_score: float | None = None
    score: ScoreResult | None = None

class LLMScoreOutput(BaseModel):   # o que o LLM devolve
    technical: int = Field(ge=0, le=100)
    seniority: int = Field(ge=0, le=100)
    domain: int = Field(ge=0, le=100)
    modality_contract: int = Field(ge=0, le=100)
    language: int = Field(ge=0, le=100)
    pj_status: PJStatus
    strengths: list[str] = Field(max_length=3)
    gaps: list[str] = Field(max_length=3)
    summary: str

class ScoreResult(LLMScoreOutput):
    total: int                    # 0–100, calculado no código; é o "%" exibido
    model: str                    # ex.: "ollama/qwen3.5:9b"
    latency_s: float
```

## 7. Fontes

### 7.1 `Source` (Protocol)
```python
class Source(Protocol):
    name: str
    def fetch(self, cfg: SearchConfig) -> list[Job]: ...
```

### 7.2 JSearch (principal)
- API agregadora (RapidAPI) que indexa vagas do Google for Jobs, incluindo LinkedIn.
- Endpoint de busca: `GET https://jsearch.p.rapidapi.com/search` com headers `X-RapidAPI-Key` e `X-RapidAPI-Host`.
- Parâmetros usados: `query`, `country`, `date_posted`, `page`, `num_pages`. Para cada termo, rodar `"{query} PJ"` **e** `"{query}"` puro (a segunda pega vagas que só citam PJ na descrição).
- **Antes de codar, conferir na documentação atual da JSearch os nomes exatos de parâmetros e campos da resposta** (ex.: `job_id`, `job_title`, `employer_name`, `job_publisher`, `job_description`, `job_apply_link`, `job_is_remote`, `job_employment_type`, `job_posted_at_datetime_utc`). Mapear tudo numa única função `_to_job()`.
- Filtrar por `publishers` do config (case-insensitive) quando a lista não estiver vazia.
- Retry com backoff exponencial (tenacity) em 429/5xx; logar e seguir se uma query falhar.
- Contar requisições por execução e logar (o plano gratuito tem cota mensal). Avisar no log se a configuração atual, rodando em dias úteis, tende a estourar a cota.

### 7.3 LinkedIn Job Alerts via IMAP (opcional, Fase 10)
- Lê emails de alerta do LinkedIn na caixa Gmail (IMAP, mesma senha de app).
- Extrai título, empresa, local e o link `/jobs/view/<id>`.
- Sem descrição: `low_fidelity=True`, scoring só pelo título, sinalizado no email. **Não buscar a página da vaga.**

## 8. Filtros (`filters.py`)

Ordem de aplicação:

1. **Dedupe**: descartar se `id` **ou** `fingerprint` já estiver em `seen.json`; deduplicar dentro do lote (mesma vaga em vários publishers → manter a do LinkedIn, senão a de descrição mais longa).
2. **Título excluído**: match case-insensitive, palavra inteira, em `exclude_title_keywords`.
3. **Modalidade**: manter remoto; híbrido/presencial só se a localização casar com `hybrid_allowed_cities`. Internacionais só se `include_international_remote` e remotas.
4. **Classificador PJ por regex** sobre título + descrição (normalizados: sem acento, lowercase):
   - Positivos: `\bpj\b`, `pessoa juridica`, `\bcnpj\b`, `contrato pj`, `modelo pj`, `contractor`, `\bb2b\b`, `freelanc`.
   - Negativos: `\bclt\b`, `carteira assinada`, `regime clt`.
   - Positivo e negativo → `BOTH`; só positivo → `PJ`; só negativo → `CLT` (descartar); nenhum → `UNCERTAIN`. `employment_type == CONTRACTOR` conta como positivo.
   - `UNCERTAIN` segue adiante e o LLM dá a palavra final. Se o LLM disser `CLT`, descartar. Se continuar incerta e `include_uncertain_contract=false`, descartar.

## 9. Scoring

### 9.1 Pré-rank com embeddings (`embeddings/` + `scoring/prerank.py`)

**Papel:** peneira rápida antes do LLM. Embeddings levam milissegundos por vaga; o LLM leva segundos. O pré-rank descarta o que obviamente não combina e manda só as `embeddings.top_n` melhores para o LLM. O `embedding_score` também é o % de reserva quando o LLM falha e no modo `--no-llm`.

**Interface plugável:**
```python
class Embedder(Protocol):
    name: str                                       # "ollama/bge-m3", "st/models/bge-m3-elyas-v1"
    def healthcheck(self) -> None: ...
    def embed_queries(self, texts: list[str]) -> np.ndarray: ...   # vagas
    def embed_passages(self, texts: list[str]) -> np.ndarray: ...  # blocos do CV
    def release(self) -> None: ...                  # libera VRAM antes da etapa de LLM
```
Fábrica `get_embedder(cfg)` escolhe pelo `embeddings.provider`. `prerank.py` não conhece o provider. Vetores sempre normalizados (L2), para o cosseno ser um produto escalar.

**Lógica do pré-rank:**
- CV representado como a média normalizada dos embeddings de 3 blocos: resumo + competências; experiências; formação + portfólio (seções do `cv.md` separadas por `##`). Calculado uma vez por execução.
- Texto da vaga: `título + empresa + descrição` truncado em ~2.000 caracteres (função única `job_to_text()`, reutilizada no treino para garantir o mesmo formato).
- `embedding_score` = similaridade de cosseno CV × vaga. Ordenar e mandar os `top_n` primeiros para o LLM.
- Embeddar em lote.
- **Gestão de VRAM:** rodar a etapa de embeddings inteira antes da de LLM e chamar `release()` no fim.

**Provider `ollama` (padrão):** `ollama.embed()` com `bge-m3`. `release()` = chamada com `keep_alive=0`. Prefixos não se aplicam.

**Provider `sentence-transformers` (opcional, extra `st`):**
- `SentenceTransformer(model, device=...)`; `encode(..., batch_size, normalize_embeddings=True)`.
- Aplica `query_prefix` / `passage_prefix` do config (necessário para famílias como e5; vazio para bge-m3).
- Aceita nome do Hugging Face **ou** caminho local em `models/` (modelo fine-tunado).
- `release()` = apagar o modelo e chamar `torch.cuda.empty_cache()`.
- Import de `torch`/`sentence_transformers` só dentro deste módulo, para o projeto funcionar sem o extra instalado.

### 9.2 Interface do scorer (`scoring/llm_base.py`)
```python
class LLMScorer(Protocol):
    name: str                                   # "ollama/qwen3.5:9b"
    def healthcheck(self) -> None: ...          # levanta erro claro se indisponível
    def score(self, job: Job, cv_md: str, prefs: Prefs) -> LLMScoreOutput: ...
```
Fábrica `get_scorer(cfg)` escolhe o provider pelo `llm.provider`. O resto do código não conhece o provider.

### 9.3 Prompt e rubrica (`scoring/prompts.py`, compartilhado pelos providers)
- System prompt (português): papel de recrutador técnico sênior de IA/ML; instruções de avaliar com rigor e sem inflar notas; a rubrica abaixo com âncoras do que é 0, 50 e 100 em cada critério; instrução de responder somente no schema.
- User prompt: `cv.md` completo, preferências (modalidade, contrato, cidade) e a vaga (título, empresa, local, tipo, descrição).
- Rubrica e pesos — **o `total` é calculado no código**, o LLM só dá as notas parciais:

| Critério | Peso | O que avalia |
|---|---|---|
| technical | 45% | Sobreposição de stack e skills exigidas (LLMs, RAG, agentes, ML, cloud, MLOps) |
| seniority | 20% | Nível pedido vs. pleno com 4+ anos; sênior forte ainda pontua razoável |
| domain | 15% | Tipo de problema e setor (GenAI, saúde, finanças, indústria) |
| modality_contract | 10% | PJ explícito e remoto/híbrido RJ pontuam máximo |
| language | 10% | Inglês exigido vs. B2; "fluente/nativo obrigatório" penaliza |

### 9.4 Provider Ollama (`scoring/llm_ollama.py`) — padrão
- `ollama.chat()` com:
  - `format=LLMScoreOutput.model_json_schema()` (saída estruturada nativa do Ollama);
  - `options={"num_ctx": cfg.num_ctx, "temperature": cfg.temperature}`;
  - `think=cfg.think`, `keep_alive=cfg.keep_alive`.
- Validar a resposta com `LLMScoreOutput.model_validate_json()`. Em erro, 1 retry; se falhar de novo, logar e cair no `embedding_score` (marcado como "estimativa").
- **Contexto**: antes de chamar, estimar tokens do prompt (~4 caracteres/token) e logar aviso se passar de 85% do `num_ctx`.
- `healthcheck()`: consultar o servidor (listar modelos); se o Ollama estiver fora do ar ou o modelo não estiver baixado, abortar a etapa com mensagem do tipo `Modelo qwen3.5:9b não encontrado. Rode: ollama pull qwen3.5:9b` e seguir com fallback para embeddings (o email ainda sai).
- Processar vagas em sequência (uma GPU, um modelo). Logar latência por vaga e total.

**Modelos recomendados para 16 GB de VRAM** (tarefa: leitura em PT/EN + julgamento por rubrica + JSON):

| Modelo | Por quê | Observação |
|---|---|---|
| `qwen3.5:9b` (padrão) | Bom em português e em saída estruturada; cabe folgado com contexto de 16k | Melhor equilíbrio velocidade/qualidade |
| `gpt-oss:20b` | MoE: qualidade de modelo maior com velocidade de modelo pequeno | Ocupa ~14 GB; pode ficar apertado com contexto grande. Testar com `num_ctx` 16384 |
| `gemma4:12b` | Forte em multilíngue | Alternativa caso o Qwen erre o tom em PT |

Evitar modelos de 27B+ em Q4: o peso sozinho já ocupa ~16 GB e o excedente transborda para a RAM, ficando muito mais lento. A escolha final deve vir da Fase 8 (comparação), não desta tabela.

### 9.5 Provider Anthropic (`scoring/llm_anthropic.py`) — opcional
- Mesmo prompt e schema. Structured output/tool use do SDK; prompt caching no system prompt + `cv.md`; `temperature=0`.
- Logar tokens e custo estimado.

### 9.6 Ranking final (`scoring/ranker.py`)
- `total = round(0.45*technical + 0.20*seniority + 0.15*domain + 0.10*modality_contract + 0.10*language)`.
- Vagas sem score de LLM usam o `embedding_score` reescalado min-max no lote para 0–100, marcadas como "estimativa".
- Descartar abaixo de `min_score_to_email`; ordenar decrescente; limitar a `email.max_jobs`.

### 9.7 Fine-tuning do embedding (`training/`) — opcional, Fase 9

**Objetivo:** ensinar o modelo de embedding o que é uma vaga boa *para mim*, para o pré-rank parar de descartar vagas que eu (ou o LLM) avaliaria bem. Só faz sentido depois de algumas semanas de histórico acumulado.

**Dados:**
- **Silver labels:** `history.jsonl` → pares `(cv_text, job_text, total/100)` pontuados pelo LLM. Volume grande, qualidade média.
- **Gold labels:** `data/eval/labels.yaml` → `{job_id: {score: 0-100, note: "opcional"}}`, preenchido pelo comando `label`, que sorteia vagas do histórico (priorizando as de nota intermediária, 40–75, onde há mais dúvida), mostra título, empresa, resumo e link, e pede minha nota. Volume pequeno, qualidade alta. Os snapshots das vagas rotuladas ficam em `data/eval/jobs/`.
- **Texto do CV no treino:** função `cv_to_text_compact()` = resumo + competências + títulos dos cargos. Adicionar `embeddings.cv_representation: "blocks_mean" | "compact"` ao config; modelos fine-tunados devem usar `compact` (o mesmo formato do treino). Texto da vaga sempre via `job_to_text()`.
- **Split por vaga** (seed fixa): gold vai 100% para validação/teste, a não ser que existam 150+ gold labels, quando 50% podem entrar no treino. Silver: 90% treino, 10% validação. A mesma vaga nunca aparece em treino e validação.
- **Mínimo para treinar:** 300 pares silver e 40 gold. Abaixo disso o comando recusa (ignorável com `--force`, com aviso).

**Treino** (`SentenceTransformerTrainer`, conferir API atual):
- Base padrão: `BAAI/bge-m3`. Loss: `CoSENTLoss` (adequada para similaridade graduada 0–1).
- Hiperparâmetros iniciais: lr `2e-5`, 2 épocas, batch 8–16, warmup 10%, `bf16=True`, `max_seq_length=512`; gradient checkpointing se faltar VRAM. Tudo configurável via CLI.
- Pesos: gold (quando usado no treino) com peso maior que silver, via duplicação controlada ou amostragem.
- Salvar em `models/<nome>/` junto com `training_meta.json`: base, data, nº de pares, hiperparâmetros, métricas.

**Avaliação** (`eval-embeddings`, compara o modelo base e o fine-tunado nos mesmos dados de validação):
- Spearman entre cosseno e nota gold (métrica principal).
- Spearman entre cosseno e nota do LLM (silver de validação).
- **Recall@top_n:** das vagas que eu dei nota ≥ 70, quantas ficariam dentro do `top_n` do pré-rank. É a métrica que mais importa, porque o papel do pré-rank é não deixar vaga boa para trás.
- Relatório em `finetune_report.md` com uma recomendação: trocar só se o Spearman gold melhorar ≥ 0,05 **e** o recall@top_n não piorar.
- **Nunca alterar o `config.yaml` automaticamente.** A troca de modelo é decisão minha.

**Cuidados documentados no relatório:** treinar só com silver ensina o embedding a imitar o LLM, inclusive os erros dele, e por isso o gold manda na decisão. Como a âncora (CV) é quase sempre a mesma, o modelo aprende essencialmente uma "direção de vaga boa para mim"; retreinar se o `cv.md` mudar muito.

## 10. Email (`notify/`)

- **Assunto**: `[Vagas PJ] {n} novas vagas — {dd/mm} (top {max}%)`.
- **Corpo HTML** (Jinja2), mobile-first, CSS inline (o Gmail remove `<style>` em vários clientes):
  - Cabeçalho: data, total coletado, após filtros, avaliadas pelo LLM e enviadas.
  - Vagas agrupadas por faixa: **≥ 80% Alta aderência**, **65–79% Boa**, **50–64% Possível**.
  - Card por vaga: título (link), empresa, local/modalidade, badge do % colorido por faixa, badge de contrato (PJ / CLT ou PJ / Não informado), publisher, data, resumo de 1 frase, até 3 pontos fortes e 3 gaps, selo "estimativa" ou "baixa fidelidade" quando aplicável.
  - Rodapé: modelo usado, tempo total de execução, tempo médio por vaga, chamadas à JSearch.
- Versão `text/plain` junto (multipart/alternative).
- Envio via `smtp.gmail.com:465` (SSL) com `GMAIL_USER` + `GMAIL_APP_PASSWORD`.
- Sem vagas e `send_when_empty=false` → não envia.

## 11. Estado (`storage.py`)

- `data/seen.json`: `{ "<id ou fingerprint>": "YYYY-MM-DD" }`.
- Gravar **só depois** do email enviado com sucesso.
- Podar entradas mais antigas que `prune_after_days`.
- Escrita atômica (arquivo temporário + rename).

**Histórico (`data/history.jsonl`):** a cada execução (exceto `--dry-run`), anexar uma linha por vaga que passou pelo LLM: `date`, `id`, `title`, `company`, `job_text` (o mesmo de `job_to_text()`), `embedding_score`, `embedder`, as 5 notas parciais, `total`, `pj_status`, `llm_model`. É a matéria-prima do fine-tuning (Fase 9) e de análises futuras. Nunca incluir dados do CV.

## 12. CLI

```
uv run python -m vagas_bot run              # pipeline completo
uv run python -m vagas_bot run --dry-run    # não envia email nem grava estado; salva preview.html
uv run python -m vagas_bot run --no-llm     # só embeddings
uv run python -m vagas_bot run --limit 5    # limita vagas processadas (debug)
uv run python -m vagas_bot doctor           # checa env, Ollama no ar, modelos baixados, SMTP
uv run python -m vagas_bot test-email       # envia email de teste
uv run python -m vagas_bot eval-models qwen3.5:9b gpt-oss:20b gemma4:12b   # Fase 8
uv run python -m vagas_bot label            # Fase 9: me mostra vagas do histórico e pede minha nota
uv run python -m vagas_bot finetune-embeddings --base BAAI/bge-m3 --out models/bge-m3-elyas-v1   # Fase 9
uv run python -m vagas_bot eval-embeddings ollama/bge-m3 st/models/bge-m3-elyas-v1                 # Fase 9
```

## 13. Agendamento local

- Horário: dias úteis, 8h.
- **Windows** (`scripts/run_daily.ps1` + Agendador de Tarefas):
  - O script entra na pasta do projeto, garante que o Ollama responde (se não, inicia `ollama serve` e espera até 30 s), roda `uv run python -m vagas_bot run` e grava a saída em `logs/YYYY-MM-DD.log`.
  - No README, documentar a criação da tarefa (`schtasks` ou interface) com a opção **"Executar a tarefa assim que possível após uma inicialização agendada ter sido perdida"**, para rodar quando o PC ligar se ele estava desligado às 8h.
- **Linux/macOS** (`scripts/run_daily.sh` + cron): mesma lógica; linha de exemplo `0 8 * * 1-5` no README.
- Evitar execução dupla no mesmo dia: arquivo de lock em `data/` com a data da última execução bem-sucedida (ignorável com `--force`).

## 14. Logs e observabilidade

- `rich` no console e arquivo em `logs/`, com contagem por etapa: coletadas → após dedupe → após filtros → enviadas ao LLM → enviadas no email.
- Logar modelo, latência por vaga, falhas de validação de JSON e avisos de contexto.
- Nunca logar segredos nem o conteúdo completo do CV.

## 15. Testes

- `test_filters.py`: regex PJ (PJ, CLT, ambos, incerto, acentos, "PJ" dentro de outra palavra não conta).
- `test_jsearch.py`: `_to_job()` com fixture JSON; filtro de publisher; retry em 429 (respx).
- `test_dedupe.py`: mesma vaga em dois publishers; vaga já vista por id e por fingerprint.
- `test_ranker.py`: cálculo ponderado do `total`; fallback para embedding.
- `test_llm_ollama.py`: resposta válida, inválida e Ollama fora do ar (mock do cliente); confere que `num_ctx` e `format` são enviados.
- `test_email.py`: template com 0, 1 e 30 vagas (snapshot do HTML).
- `test_embeddings.py`: fábrica escolhe o provider certo; `prerank` ordena corretamente com um Embedder fake (vetores fixos); provider `st` não é importado quando o extra não está instalado.
- `test_dataset.py`: montagem dos pares a partir de `history.jsonl` + `labels.yaml`, split sem vazamento (mesma vaga nunca em treino e validação).
- Nenhum teste chama APIs reais nem o Ollama. Testes de integração com Ollama real ficam marcados `@pytest.mark.integration` e fora do padrão.

## 16. Fases de implementação

Implementar **uma fase por vez**, rodando os testes ao fim de cada uma e parando para eu revisar.

1. **Esqueleto**: `pyproject.toml`, estrutura, `config.py`, `models.py`, CLI, leitura do `cv.md`, comando `doctor`. *Aceite:* `run --dry-run` executa sem erro e `doctor` mostra o status do Ollama.
2. **Fonte JSearch**: coleta, normalização, filtro de publisher, retry. *Aceite:* `--dry-run --no-llm` lista vagas reais no log.
3. **Dedupe + filtros + PJ regex + storage**. *Aceite:* testes passam; duas execuções seguidas (sem `--dry-run`) não repetem vagas.
4. **Embeddings via Ollama**, já com a interface `Embedder` e a fábrica, mas só o provider `ollama`. *Aceite:* `preview.html` com vagas ordenadas por estimativa; modelo de embedding descarregado ao fim da etapa.
5. **Scorer Ollama + histórico**. *Aceite:* JSON validado, `total` calculado no código, fallback funcionando com o Ollama desligado, latência logada, `history.jsonl` sendo gravado.
6. **Email**. *Aceite:* `test-email` chega no Gmail e renderiza bem no celular.
7. **Agendamento local**. *Aceite:* tarefa agendada roda sozinha, grava log e não executa duas vezes no mesmo dia.
8. **Comparação de modelos** (`eval-models`): roda 10–15 vagas salvas em `data/eval/jobs/` em cada modelo informado, 2 vezes cada, e gera tabela com tempo médio por vaga, taxa de JSON inválido, variação de nota entre as 2 rodadas (consistência) e as notas lado a lado. Opcional: arquivo `data/eval/labels.yaml` com minha nota manual de cada vaga, para calcular correlação de Spearman entre modelo e eu. *Aceite:* relatório em `eval_report.md` que me permita escolher o modelo padrão.
9. **(Opcional) Embeddings com sentence-transformers + fine-tuning**: provider `st`, extra `st` com PyTorch CUDA 12.8+, comandos `label`, `finetune-embeddings` e `eval-embeddings`. *Aceite:* `doctor` confirma a GPU no torch; provider `st` com `BAAI/bge-m3` gera o mesmo ranking (Spearman > 0,95) que o provider `ollama` nas vagas de `data/eval/jobs/`; fine-tuning roda de ponta a ponta e gera `finetune_report.md`.
10. **(Opcional) Provider Anthropic**.
11. **(Opcional) LinkedIn Alerts via IMAP**.

## 17. Instruções para o Claude Code

- Ler esta spec inteira antes de começar e seguir a ordem das fases.
- Verificar a documentação atual da JSearch, do cliente Python do Ollama (parâmetros `format`, `think`, `keep_alive`, `options`), do sentence-transformers (`SentenceTransformerTrainer`, `CoSENTLoss`) e do PyTorch (variante CUDA para Blackwell) quando chegar na Fase 9, e do SDK da Anthropic na Fase 10. Se algo aqui divergir da doc, seguir a doc e me avisar.
- Type hints em tudo, funções pequenas, sem dependências além das listadas sem me perguntar.
- Não implementar scraping logado do LinkedIn em nenhuma hipótese.
