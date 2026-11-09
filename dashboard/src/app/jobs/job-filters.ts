import { FilterReason, JobRow, PjStatus, Stage } from '../core/models';

export interface JobFilters {
  q: string;
  stages: Stage[];
  reasons: FilterReason[];
  sources: string[];
  contracts: PjStatus[];
  minScore: number | null;
  maxScore: number | null;
  from: string; // YYYY-MM-DD ('' = sem limite)
  to: string;
  unlabeled: boolean;
}

export type SortKey = 'date' | 'total' | 'cosine' | 'mine';
export type SortDir = 'asc' | 'desc';

export const EMPTY_FILTERS: JobFilters = {
  q: '',
  stages: [],
  reasons: [],
  sources: [],
  contracts: [],
  minScore: null,
  maxScore: null,
  from: '',
  to: '',
  unlabeled: false,
};

function normalize(text: string): string {
  return text.normalize('NFD').replace(/[̀-ͯ]/g, '').toLowerCase();
}

export function applyFilters(rows: JobRow[], f: JobFilters): JobRow[] {
  const q = normalize(f.q.trim());
  return rows.filter(
    (r) =>
      (!q || normalize(`${r.title} ${r.company}`).includes(q)) &&
      (!f.stages.length || f.stages.includes(r.stage)) &&
      (!f.reasons.length || (r.filter_reason !== null && f.reasons.includes(r.filter_reason))) &&
      (!f.sources.length || f.sources.includes(r.source)) &&
      (!f.contracts.length || f.contracts.includes(r.pj_status)) &&
      (f.minScore === null || (r.total !== null && r.total >= f.minScore)) &&
      (f.maxScore === null || (r.total !== null && r.total <= f.maxScore)) &&
      (!f.from || r.run_date >= f.from) &&
      (!f.to || r.run_date <= f.to) &&
      (!f.unlabeled || r.my_score === null),
  );
}

const SORT_VALUE: Record<SortKey, (r: JobRow) => number | string | null> = {
  date: (r) => r.run_date || null,
  total: (r) => r.total,
  cosine: (r) => r.embedding_score,
  mine: (r) => r.my_score,
};

/** Stable sort; empty values always go last, whatever the direction. */
export function sortRows(rows: JobRow[], key: SortKey, dir: SortDir): JobRow[] {
  const value = SORT_VALUE[key];
  const sign = dir === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    const va = value(a);
    const vb = value(b);
    if (va === null && vb === null) return 0;
    if (va === null) return 1;
    if (vb === null) return -1;
    return va < vb ? -sign : va > vb ? sign : 0;
  });
}

export interface Counts {
  total: number;
  emailed: number;
  evaluated: number;
  filtered: number;
  labeled: number;
  byReason: Partial<Record<FilterReason, number>>;
}

export function countsBy(rows: JobRow[]): Counts {
  const counts: Counts = { total: rows.length, emailed: 0, evaluated: 0, filtered: 0, labeled: 0, byReason: {} };
  for (const r of rows) {
    if (r.stage === 'emailed') counts.emailed++;
    if (r.stage === 'emailed' || r.stage === 'evaluated') counts.evaluated++;
    if (r.stage === 'filtered') counts.filtered++;
    if (r.my_score !== null) counts.labeled++;
    if (r.filter_reason) counts.byReason[r.filter_reason] = (counts.byReason[r.filter_reason] ?? 0) + 1;
  }
  return counts;
}

type Params = Record<string, string>;

function list<T extends string>(value: string | undefined): T[] {
  return value ? (value.split(',').filter(Boolean) as T[]) : [];
}

function num(value: string | undefined): number | null {
  if (value === undefined || value === '') return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function filtersFromParams(params: Params): JobFilters {
  return {
    q: params['q'] ?? '',
    stages: list<Stage>(params['etapa']),
    reasons: list<FilterReason>(params['motivo']),
    sources: list(params['fonte']),
    contracts: list<PjStatus>(params['contrato']),
    minScore: num(params['min']),
    maxScore: num(params['max']),
    from: params['de'] ?? '',
    to: params['ate'] ?? '',
    unlabeled: params['sem_nota'] === '1',
  };
}

/** Only non-default values, so the URL stays short. */
export function filtersToParams(f: JobFilters): Params {
  const p: Params = {};
  if (f.q) p['q'] = f.q;
  if (f.stages.length) p['etapa'] = f.stages.join(',');
  if (f.reasons.length) p['motivo'] = f.reasons.join(',');
  if (f.sources.length) p['fonte'] = f.sources.join(',');
  if (f.contracts.length) p['contrato'] = f.contracts.join(',');
  if (f.minScore !== null) p['min'] = String(f.minScore);
  if (f.maxScore !== null) p['max'] = String(f.maxScore);
  if (f.from) p['de'] = f.from;
  if (f.to) p['ate'] = f.to;
  if (f.unlabeled) p['sem_nota'] = '1';
  return p;
}
