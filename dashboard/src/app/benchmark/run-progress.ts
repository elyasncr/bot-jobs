import { BenchmarkModelOption, BenchmarkStatus } from '../core/models';

/** Funções puras do botão "Rodar benchmark" (testadas sem montar o componente). */

export function defaultSelection(options: BenchmarkModelOption[]): string[] {
  return options.filter((o) => o.default).map((o) => o.name);
}

/** "Incluindo vagas novas…" → "Carregando <1º modelo>…" → "gemma4:12b (2/3) · 34/46". */
export function progressText(s: BenchmarkStatus): string {
  if (s.phase === 'adding') return 'Incluindo vagas novas…';
  if (!s.current_model) return `Carregando ${s.models[0] ?? 'modelo'}…`;
  return `${s.current_model} (${s.model_index}/${s.model_count}) · ${s.done}/${s.total}`;
}

/** 0–100, contando os modelos já concluídos. */
export function progressPercent(s: BenchmarkStatus): number {
  if (!s.model_count || !s.total || s.model_index < 1) return 0;
  const perModel = 100 / s.model_count;
  return Math.round((s.model_index - 1) * perModel + (s.done / s.total) * perModel);
}

export function jobsSummary(pending: number, total: number): string {
  const novas =
    pending === 0 ? 'Nenhuma vaga nova' : pending === 1 ? '1 vaga nova será incluída' : `${pending} vagas novas serão incluídas`;
  return `${novas} · ${total + pending} no total`;
}
