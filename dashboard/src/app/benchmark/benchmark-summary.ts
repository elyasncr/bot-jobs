import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { DecimalPipe, PercentPipe } from '@angular/common';

import { ModelSummary } from '../core/models';

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

@Component({
  selector: 'app-benchmark-summary',
  imports: [DecimalPipe, PercentPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>Modelo</th>
            <th class="num" title="Média por vaga, sem a 1ª chamada">s/vaga</th>
            <th class="num" title="1ª chamada: carga do modelo na GPU">Carga</th>
            <th class="num">VRAM</th>
            <th class="num">JSON inválido</th>
            <th class="num">Falhas</th>
            <th class="num" title="Média das notas finais">Nota média</th>
            <th class="num" title="Diferença da nota na mesma vaga entre rodadas">Δ rodadas</th>
            <th class="num">pj estável</th>
            <th class="num" title='Respostas "CLT" em vagas sem sinal de CLT no texto'>CLT s/ evidência</th>
            <th class="num" title="Spearman entre o modelo e as suas notas">Spearman (você)</th>
            <th class="num" [title]="'Spearman vs. ' + (rows()[0]?.model ?? '')">Concordância</th>
          </tr>
        </thead>
        <tbody>
          @for (s of rows(); track s.model) {
            <tr [class.unreliable]="!s.reliable">
              <th scope="row">{{ s.model }}</th>
              @if (!s.available && !s.ok) {
                <td colspan="11" class="muted">indisponível: {{ s.error }}</td>
              } @else {
                <td class="num" [class.best]="best().speed === s.model">{{ s.mean_s | number: '1.1-1' }}s</td>
                <td class="num">{{ s.load_s === null ? '—' : (s.load_s | number: '1.0-0') + 's' }}</td>
                <td class="num" [class.best]="best().vram === s.model">{{ s.vram_gb === null ? '—' : (s.vram_gb | number: '1.1-1') + ' GB' }}</td>
                <td class="num" [class.bad]="s.invalid_rate > 0.1">{{ s.invalid_rate | percent: '1.0-0' }} <small>({{ s.invalid }}/{{ s.calls }})</small></td>
                <td class="num" [class.bad]="s.fail_rate > 0.1">{{ s.failed }}</td>
                <td class="num">{{ s.mean_total | number: '1.0-0' }}</td>
                <td class="num" [class.best]="best().consistency === s.model">
                  {{ s.mean_abs_diff === null ? '—' : (s.mean_abs_diff | number: '1.1-1') }} <small>máx {{ s.max_diff ?? '—' }}</small>
                </td>
                <td class="num">{{ s.pj_consistency === null ? '—' : (s.pj_consistency | percent: '1.0-0') }}</td>
                <td class="num" [class.best]="best().clt === s.model" [class.bad]="s.clt_without_evidence > 0">
                  {{ s.clt_without_evidence }}/{{ s.clt_answers }}
                </td>
                <td class="num" [class.best]="best().gold === s.model">
                  {{ s.spearman_gold === null ? '—' : (s.spearman_gold | number: '1.2-2') }} <small>n={{ s.n_gold }}</small>
                </td>
                <td class="num">{{ s.agreement_with_ref === null ? '—' : (s.agreement_with_ref | number: '1.2-2') }}</td>
              }
            </tr>
          }
        </tbody>
      </table>
    </div>
  `,
  styles: `
    :host { display: block; min-width: 0; }
    .scroll { overflow-x: auto; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }
    table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
    th, td { padding: 8px 10px; border-bottom: 1px solid var(--border); white-space: nowrap; }
    thead th { background: var(--surface-2); font-weight: 600; text-align: left; }
    tbody th { text-align: left; font-weight: 600; }
    .num { text-align: right; font-variant-numeric: tabular-nums; }
    small { color: var(--muted); }
    .best { background: var(--high-bg); color: var(--high); font-weight: 700; }
    .bad { color: var(--danger); }
    .unreliable { opacity: 0.6; }
    .muted { color: var(--muted); }
  `,
})
export class BenchmarkSummary {
  readonly rows = input.required<ModelSummary[]>();

  protected readonly best = computed(() => {
    const rows = this.rows();
    return {
      speed: bestModel(rows, (s) => s.mean_s, 'min'),
      vram: bestModel(rows, (s) => s.vram_gb, 'min'),
      consistency: bestModel(rows, (s) => s.mean_abs_diff, 'min'),
      clt: bestModel(rows, (s) => s.clt_without_evidence, 'min'),
      gold: bestModel(rows, (s) => s.spearman_gold, 'max'),
    };
  });
}
