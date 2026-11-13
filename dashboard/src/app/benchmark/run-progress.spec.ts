import { BenchmarkModelOption, BenchmarkStatus } from '../core/models';
import { defaultSelection, jobsSummary, progressPercent, progressText } from './run-progress';

function status(overrides: Partial<BenchmarkStatus>): BenchmarkStatus {
  return {
    state: 'running', phase: 'running', models: ['a:1b', 'b:2b'], current_model: null, model_index: 0, model_count: 2,
    done: 0, total: 0, added: 0, started_at: null, finished_at: null, result_file: null, error: null, ...overrides,
  };
}

describe('run-progress', () => {
  it('defaultSelection pega só os marcados por padrão, na ordem', () => {
    const opts: BenchmarkModelOption[] = [
      { name: 'a', default: true, warning: null },
      { name: 'b', default: false, warning: 'x' },
      { name: 'c', default: true, warning: null },
    ];
    expect(defaultSelection(opts)).toEqual(['a', 'c']);
  });

  it('progressText cobre inclusão, início e andamento', () => {
    expect(progressText(status({ phase: 'adding' }))).toBe('Incluindo vagas novas…');
    expect(progressText(status({}))).toBe('Carregando a:1b…');
    expect(progressText(status({ current_model: 'b:2b', model_index: 2, done: 34, total: 46 }))).toBe('b:2b (2/2) · 34/46');
  });

  it('progressPercent soma os modelos já concluídos', () => {
    expect(progressPercent(status({}))).toBe(0);
    expect(progressPercent(status({ current_model: 'a:1b', model_index: 1, done: 23, total: 46 }))).toBe(25);
    expect(progressPercent(status({ current_model: 'b:2b', model_index: 2, done: 46, total: 46 }))).toBe(100);
  });

  it('jobsSummary no singular e no plural', () => {
    expect(jobsSummary(1, 15)).toBe('1 vaga nova será incluída · 16 no total');
    expect(jobsSummary(8, 15)).toBe('8 vagas novas serão incluídas · 23 no total');
    expect(jobsSummary(0, 15)).toBe('Nenhuma vaga nova · 15 no total');
  });
});
