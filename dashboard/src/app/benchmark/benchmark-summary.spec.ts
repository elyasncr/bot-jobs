import { ModelSummary, formatDate, shortLocation, shortModel } from '../core/models';
import { bestModel, bestModels } from './benchmark-summary';

function summary(model: string, clt: number, reliable = true): ModelSummary {
  return { model, reliable, clt_without_evidence: clt } as ModelSummary;
}

describe('bestModel / bestModels', () => {
  const rows = [summary('a', 3), summary('b', 0), summary('c', 0), summary('d', 0, false)];

  it('bestModel devolve o primeiro melhor entre os confiáveis', () => {
    expect(bestModel(rows, (s) => s.clt_without_evidence, 'min')).toBe('b');
  });

  it('bestModels devolve todos os empatados, sem os não confiáveis', () => {
    expect(bestModels(rows, (s) => s.clt_without_evidence, 'min')).toEqual(['b', 'c']);
  });

  it('bestModels vazio quando ninguém tem valor', () => {
    expect(bestModels(rows, () => null, 'max')).toEqual([]);
  });
});

describe('helpers de exibição', () => {
  it('formatDate omite o ano corrente', () => {
    const today = new Date(2026, 10, 9);
    expect(formatDate('2026-11-09', today)).toBe('9 nov');
    expect(formatDate('2025-01-31T10:00:00', today)).toBe('31 jan 2025');
    expect(formatDate(null, today)).toBe('—');
  });

  it('shortLocation fica com o trecho antes da vírgula', () => {
    expect(shortLocation('Brasília - Plano Piloto, Brasília - DF')).toBe('Brasília - Plano Piloto');
    expect(shortLocation(null)).toBeNull();
  });

  it('shortModel tira o prefixo ollama/', () => {
    expect(shortModel('ollama/qwen3:14b')).toBe('qwen3:14b');
  });
});
