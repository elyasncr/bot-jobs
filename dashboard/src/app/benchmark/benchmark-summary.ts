import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { DecimalPipe, PercentPipe } from '@angular/common';

import { ModelSummary, shortModel } from '../core/models';
import { modelColor } from './score-chart';

type Better = 'min' | 'max';

/** Which model has the best value in a column (only reliable models compete). */
export function bestModel(rows: ModelSummary[], value: (s: ModelSummary) => number | null, better: Better): string | null {
  let best: ModelSummary | null = null;
  for (const row of rows) {
    const v = value(row);
    if (!row.reliable || v === null) continue;
    const current = best === null ? null : value(best);
    if (current === null || (better === 'min' ? v < current : v > current)) best = row;
  }
  return best?.model ?? null;
}

/** All reliable models tied at the best value (empty when nobody qualifies). */
export function bestModels(rows: ModelSummary[], value: (s: ModelSummary) => number | null, better: Better): string[] {
  const winner = bestModel(rows, value, better);
  if (winner === null) return [];
  const target = value(rows.find((r) => r.model === winner)!);
  return rows.filter((r) => r.reliable && value(r) === target).map((r) => r.model);
}

@Component({
  selector: 'app-benchmark-summary',
  imports: [DecimalPipe, PercentPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="frame">
      <table>
        <thead>
          <tr class="groups">
            <th rowspan="2" class="model-col">Modelo</th>
            <th colspan="3">Desempenho</th>
            <th colspan="2">Confiabilidade</th>
            <th colspan="2">Estabilidade</th>
            <th colspan="4">Qualidade</th>
          </tr>
          <tr>
            <th class="num start" title="Média por vaga, sem a 1ª chamada">s/vaga</th>
            <th class="num" title="1ª chamada: carga do modelo na GPU">Carga</th>
            <th class="num">VRAM</th>
            <th class="num start">JSON inválido</th>
            <th class="num">Falhas</th>
            <th class="num start" title="Diferença da nota na mesma vaga entre rodadas">Δ rodadas</th>
            <th class="num" title="Mesmo contrato nas duas rodadas">Contrato estável</th>
            <th class="num start" title="Média das notas finais">Nota média</th>
            <th class="num" title='Respostas "CLT" em vagas sem sinal de CLT no texto'>CLT s/ evidência</th>
            <th class="num" title="Spearman entre o modelo e as suas notas">Spearman (você)</th>
            <th class="num" [title]="'Spearman vs. ' + short(rows()[0]?.model ?? '')">Concordância</th>
          </tr>
        </thead>
        <tbody>
          @for (s of rows(); track s.model; let i = $index) {
            <tr [class.unreliable]="!s.reliable">
              <th scope="row" class="model-col">
                <span class="model"><i class="dot" [style.background]="color(i)"></i>{{ short(s.model) }}</span>
                @if (!s.reliable && s.available) {
                  <small class="flag">não confiável</small>
                }
              </th>
              @if (!s.available && !s.ok) {
                <td colspan="11" class="muted">indisponível: {{ s.error }}</td>
              } @else {
                <td class="num start" [class.best]="best().speed.includes(s.model)">{{ s.mean_s | number: '1.1-1' }}s</td>
                <td class="num">{{ s.load_s === null ? '—' : (s.load_s | number: '1.0-0') + 's' }}</td>
                <td class="num" [class.best]="best().vram.includes(s.model)">{{ s.vram_gb === null ? '—' : (s.vram_gb | number: '1.1-1') + ' GB' }}</td>
                <td class="num start" [class.bad]="s.invalid_rate > 0.1">{{ s.invalid_rate | percent: '1.0-0' }} <small>{{ s.invalid }}/{{ s.calls }}</small></td>
                <td class="num" [class.bad]="s.fail_rate > 0.1">{{ s.failed }}</td>
                <td class="num start" [class.best]="best().consistency.includes(s.model)">
                  {{ s.mean_abs_diff === null ? '—' : (s.mean_abs_diff | number: '1.1-1') }} <small>máx {{ s.max_diff ?? '—' }}</small>
                </td>
                <td class="num">{{ s.pj_consistency === null ? '—' : (s.pj_consistency | percent: '1.0-0') }}</td>
                <td class="num start">{{ s.mean_total | number: '1.0-0' }}</td>
                <td class="num" [class.best]="best().clt.includes(s.model)" [class.bad]="s.clt_without_evidence > 0">
                  {{ s.clt_without_evidence }}<small>/{{ s.clt_answers }}</small>
                </td>
                <td class="num" [class.best]="best().gold.includes(s.model)">
                  {{ s.spearman_gold === null ? '—' : (s.spearman_gold | number: '1.2-2') }} <small>n={{ s.n_gold }}</small>
                </td>
                <td class="num">{{ s.agreement_with_ref === null ? '—' : (s.agreement_with_ref | number: '1.2-2') }}</td>
              }
            </tr>
          }
        </tbody>
      </table>
    </div>
    <p class="legend"><span class="swatch"></span>melhor valor entre os modelos confiáveis</p>
  `,
  styles: `
    :host { display: block; min-width: 0; }
    .frame { overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); box-shadow: var(--shadow-sm); }
    table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
    th, td { padding: 10px 12px; border-bottom: 1px solid var(--border); white-space: nowrap; }
    tbody tr:last-child > * { border-bottom: 0; }
    thead th { font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: var(--faint); text-align: left; }
    .groups th { padding-bottom: 2px; border-bottom: 0; color: var(--muted); border-left: 1px solid var(--border); }
    .groups th.model-col { border-left: 0; vertical-align: bottom; padding-bottom: 10px; border-bottom: 1px solid var(--border); }
    .start { border-left: 1px solid var(--border); }
    tbody th { text-align: left; font-weight: 600; }
    .model { display: inline-flex; align-items: center; gap: 8px; }
    .dot { width: 10px; height: 10px; border-radius: 50%; flex: none; }
    .flag { display: block; margin-left: 18px; font-weight: 500; color: var(--danger); }
    .num { text-align: right; font-variant-numeric: tabular-nums; }
    small { color: var(--faint); font-size: 0.78em; }
    .best { position: relative; color: var(--high); font-weight: 700; }
    .best::before { content: ''; position: absolute; inset: 5px 4px; border-radius: 6px; background: var(--high-bg); z-index: -1; }
    td { position: relative; z-index: 0; }
    .bad { color: var(--danger); }
    .unreliable td { opacity: 0.55; }
    .muted { color: var(--muted); }
    .legend { display: flex; align-items: center; gap: 6px; margin: 8px 2px 0; font-size: 0.78rem; color: var(--faint); }
    .swatch { width: 12px; height: 12px; border-radius: 3px; background: var(--high-bg); box-shadow: inset 0 0 0 1px var(--high); }
  `,
})
export class BenchmarkSummary {
  readonly rows = input.required<ModelSummary[]>();

  protected readonly best = computed(() => {
    const rows = this.rows();
    return {
      speed: bestModels(rows, (s) => s.mean_s, 'min'),
      vram: bestModels(rows, (s) => s.vram_gb, 'min'),
      consistency: bestModels(rows, (s) => s.mean_abs_diff, 'min'),
      clt: bestModels(rows, (s) => s.clt_without_evidence, 'min'),
      gold: bestModels(rows, (s) => s.spearman_gold, 'max'),
    };
  });

  protected short(model: string): string {
    return shortModel(model);
  }

  protected color(index: number): string {
    return modelColor(index);
  }
}
