// Espelho da API Python (src/vagas_bot/dashboard/data.py). Manter em sincronia.

export type Stage = 'emailed' | 'evaluated' | 'filtered' | 'history' | 'benchmark';
export type FilterReason = 'title' | 'modality' | 'clt' | 'limit';
export type Modality = 'remote' | 'hybrid' | 'onsite' | 'unknown';
export type PjStatus = 'pj' | 'both' | 'clt' | 'uncertain';

export interface PartialScores {
  technical: number;
  seniority: number;
  domain: number;
  modality_contract: number;
  language: number;
}

export interface JobRow {
  id: string;
  run_date: string;
  stage: Stage;
  filter_reason: FilterReason | null;
  source: string;
  publisher: string | null;
  title: string;
  company: string;
  location: string | null;
  modality: Modality;
  url: string;
  posted_at: string | null;
  low_fidelity: boolean;
  pj_status: PjStatus;
  description: string;
  embedding_score: number | null;
  total: number | null;
  is_estimate: boolean;
  scores: PartialScores | null;
  strengths: string[];
  gaps: string[];
  summary: string | null;
  llm_model: string | null;
  my_score: number | null;
  my_note: string;
}

export interface BenchmarkRun {
  file: string;
  date: string | null;
  models: string[];
  jobs: number;
}

export interface BenchmarkModelOption {
  name: string;
  default: boolean;
  warning: string | null;
}

export interface BenchmarkModels {
  models: BenchmarkModelOption[];
  pending_jobs: number;
  total_jobs: number;
}

export interface BenchmarkStatus {
  state: 'idle' | 'running' | 'done' | 'error';
  phase: 'adding' | 'running' | null;
  models: string[];
  current_model: string | null;
  model_index: number;
  model_count: number;
  done: number;
  total: number;
  added: number;
  started_at: string | null;
  finished_at: string | null;
  result_file: string | null;
  error: string | null;
}

export interface ModelSummary {
  model: string;
  available: boolean;
  error: string | null;
  ok: number;
  failed: number;
  calls: number;
  invalid: number;
  mean_s: number | null;
  median_s: number | null;
  load_s: number | null;
  vram_gb: number | null;
  mean_total: number | null;
  mean_abs_diff: number | null;
  max_diff: number | null;
  pj_consistency: number | null;
  clt_answers: number;
  clt_without_evidence: number;
  spearman_gold: number | null;
  n_gold: number;
  invalid_rate: number;
  fail_rate: number;
  reliable: boolean;
  agreement_with_ref: number | null;
}

export interface BenchModelResult {
  totals: (number | null)[];
  pj_status: (PjStatus | null)[];
  mean: number | null;
}

export interface BenchJob {
  id: string;
  title: string;
  company: string;
  url: string;
  publisher: string | null;
  clt_signals: boolean;
  my_score: number | null;
  models: Record<string, BenchModelResult>;
}

export interface BenchmarkPayload {
  meta: { date?: string; runs?: number; num_ctx?: number; temperature?: number; think?: boolean; models?: string[] };
  summaries: ModelSummary[];
  reading: string[];
  jobs: BenchJob[];
}

export interface LabelResult {
  id: string;
  my_score: number | null;
  my_note: string;
}

export const STAGE_LABELS: Record<Stage, string> = {
  emailed: 'Enviada',
  evaluated: 'Avaliada',
  filtered: 'Filtrada',
  history: 'Histórico',
  benchmark: 'Benchmark',
};

export const REASON_LABELS: Record<FilterReason, string> = {
  title: 'Título',
  modality: 'Modalidade',
  clt: 'CLT',
  limit: 'Limite diário',
};

export const CONTRACT_LABELS: Record<PjStatus, string> = {
  pj: 'PJ',
  both: 'CLT ou PJ',
  clt: 'CLT',
  uncertain: 'Não informado',
};

export function sourceLabel(row: { source: string; publisher: string | null }): string {
  if (row.source === 'linkedin_alerts') return 'LinkedIn (alerta)';
  if (row.source === 'history') return 'Histórico';
  if (row.source === 'jsearch') return row.publisher || 'JSearch';
  return row.publisher || row.source;
}

export const MODALITY_LABELS: Record<Modality, string> = {
  remote: 'Remoto',
  hybrid: 'Híbrido',
  onsite: 'Presencial',
  unknown: '—',
};


/** "ollama/qwen3:14b" → "qwen3:14b" (o prefixo se repete em todos os modelos). */
export function shortModel(model: string): string {
  return model.replace(/^ollama\//, '');
}

const MONTHS = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun', 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

/** "2026-11-09" → "9 nov" (com o ano só se não for o ano corrente). */
export function formatDate(iso: string | null | undefined, today = new Date()): string {
  if (!iso) return '—';
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number);
  if (!y || !m || !d || m > 12) return iso;
  const text = `${d} ${MONTHS[m - 1]}`;
  return y === today.getFullYear() ? text : `${text} ${y}`;
}

/** "Brasília - Plano Piloto, Brasília - DF" → "Brasília - Plano Piloto". */
export function shortLocation(location: string | null): string | null {
  if (!location) return null;
  return location.split(',')[0].trim() || location;
}
