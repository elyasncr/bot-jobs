import { JobRow } from '../core/models';
import { EMPTY_FILTERS, JobFilters, applyFilters, countsBy, filtersFromParams, filtersToParams, sortRows } from './job-filters';

function row(overrides: Partial<JobRow>): JobRow {
  return {
    id: 'id',
    run_date: '2026-11-09',
    stage: 'evaluated',
    filter_reason: null,
    source: 'jsearch',
    publisher: 'LinkedIn',
    title: 'AI Engineer',
    company: 'ACME',
    location: null,
    modality: 'remote',
    url: '',
    posted_at: null,
    low_fidelity: false,
    pj_status: 'uncertain',
    description: '',
    embedding_score: null,
    total: null,
    is_estimate: false,
    scores: null,
    strengths: [],
    gaps: [],
    summary: null,
    llm_model: null,
    my_score: null,
    my_note: '',
    ...overrides,
  };
}

const ROWS: JobRow[] = [
  row({ id: 'a', title: 'Engenheiro de Inteligência Artificial', total: 82, stage: 'emailed', pj_status: 'pj', my_score: 70, embedding_score: 0.6 }),
  row({ id: 'b', title: 'Data Scientist', company: 'Itaú', total: 55, run_date: '2026-11-08', embedding_score: 0.4 }),
  row({ id: 'c', title: 'Analista Júnior', stage: 'filtered', filter_reason: 'title', source: 'linkedin_alerts' }),
];

function ids(rows: JobRow[]): string[] {
  return rows.map((r) => r.id);
}

function filters(overrides: Partial<JobFilters>): JobFilters {
  return { ...EMPTY_FILTERS, ...overrides };
}

describe('applyFilters', () => {
  it('sem filtros devolve tudo', () => {
    expect(ids(applyFilters(ROWS, EMPTY_FILTERS))).toEqual(['a', 'b', 'c']);
  });

  it('busca ignora acento e caixa, em título e empresa', () => {
    expect(ids(applyFilters(ROWS, filters({ q: 'inteligencia' })))).toEqual(['a']);
    expect(ids(applyFilters(ROWS, filters({ q: 'ITAU' })))).toEqual(['b']);
  });

  it('filtra por etapa, motivo, fonte e contrato', () => {
    expect(ids(applyFilters(ROWS, filters({ stages: ['emailed', 'filtered'] })))).toEqual(['a', 'c']);
    expect(ids(applyFilters(ROWS, filters({ reasons: ['title'] })))).toEqual(['c']);
    expect(ids(applyFilters(ROWS, filters({ sources: ['linkedin_alerts'] })))).toEqual(['c']);
    expect(ids(applyFilters(ROWS, filters({ contracts: ['pj'] })))).toEqual(['a']);
  });

  it('faixa de nota exclui vagas sem nota', () => {
    expect(ids(applyFilters(ROWS, filters({ minScore: 60 })))).toEqual(['a']);
    expect(ids(applyFilters(ROWS, filters({ maxScore: 60 })))).toEqual(['b']);
  });

  it('período e "sem nota minha"', () => {
    expect(ids(applyFilters(ROWS, filters({ from: '2026-11-09' })))).toEqual(['a', 'c']);
    expect(ids(applyFilters(ROWS, filters({ to: '2026-11-08' })))).toEqual(['b']);
    expect(ids(applyFilters(ROWS, filters({ unlabeled: true })))).toEqual(['b', 'c']);
  });

  it('combina filtros', () => {
    expect(ids(applyFilters(ROWS, filters({ stages: ['evaluated', 'emailed'], minScore: 50, unlabeled: true })))).toEqual(['b']);
  });
});

describe('sortRows', () => {
  it('ordena nos dois sentidos com nulos sempre por último', () => {
    expect(ids(sortRows(ROWS, 'total', 'desc'))).toEqual(['a', 'b', 'c']);
    expect(ids(sortRows(ROWS, 'total', 'asc'))).toEqual(['b', 'a', 'c']);
    expect(ids(sortRows(ROWS, 'mine', 'asc'))).toEqual(['a', 'b', 'c']);
    expect(ids(sortRows(ROWS, 'date', 'asc'))[0]).toBe('b');
  });

  it('não altera o array original', () => {
    const copy = [...ROWS];
    sortRows(ROWS, 'cosine', 'asc');
    expect(ROWS).toEqual(copy);
  });
});

describe('countsBy', () => {
  it('conta etapas, motivos e notas', () => {
    expect(countsBy(ROWS)).toEqual({ total: 3, emailed: 1, evaluated: 2, filtered: 1, labeled: 1, byReason: { title: 1 } });
  });
});

describe('params', () => {
  it('ida e volta preserva os filtros', () => {
    const f = filters({ q: 'ai', stages: ['emailed'], contracts: ['pj', 'both'], minScore: 50, from: '2026-11-01', unlabeled: true });
    expect(filtersFromParams(filtersToParams(f))).toEqual(f);
  });

  it('filtros vazios não geram params e params inválidos são ignorados', () => {
    expect(filtersToParams(EMPTY_FILTERS)).toEqual({});
    expect(filtersFromParams({ min: 'abc' }).minScore).toBeNull();
  });
});
