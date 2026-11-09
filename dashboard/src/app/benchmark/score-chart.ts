import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { BenchJob, shortModel } from '../core/models';

/** Paleta categórica validada (styles.css → --series-N); a cor segue o modelo pela ordem do resultado. */
export const MODEL_COLORS = Array.from({ length: 8 }, (_, i) => `var(--series-${i + 1})`);

export function modelColor(index: number): string {
  return MODEL_COLORS[Math.min(index, MODEL_COLORS.length - 1)];
}

interface ChartRow {
  job: BenchJob;
  points: { model: string; mean: number; color: string }[];
  min: number | null;
  max: number | null;
}

/**
 * Uma linha por vaga, eixo 0–100: um ponto por modelo (média das rodadas), a faixa entre o menor e o maior
 * (discordância entre os modelos) e um losango para a sua nota. Feito em HTML para ocupar a largura disponível.
 */
@Component({
  selector: 'app-score-chart',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="legend">
      @for (m of models(); track m; let i = $index) {
        <span><i class="dot" [style.background]="color(i)"></i>{{ short(m) }}</span>
      }
      <span><i class="diamond"></i>Você</span>
      <span class="muted"><i class="band"></i>distância entre os modelos</span>
    </div>
    <div class="chart" role="img" aria-label="Notas por vaga e por modelo (a tabela Lado a lado traz os mesmos números)">
      <div class="row axis" aria-hidden="true">
        <div class="name"></div>
        <div class="ticks">
          @for (t of ticks; track t) {
            <span [style.left.%]="t">{{ t }}</span>
          }
        </div>
      </div>
      @for (r of rows(); track r.job.id) {
        <div class="row">
          <div class="name" [title]="r.job.title + ' · ' + r.job.company">
            <span class="title">{{ r.job.title }}</span>
            <span class="company">{{ r.job.company }}</span>
          </div>
          <div class="plot">
            @if (r.min !== null && r.max !== null && r.max > r.min) {
              <span class="range" [style.left.%]="r.min" [style.width.%]="r.max - r.min"></span>
            }
            @for (p of r.points; track p.model) {
              <span class="mark dot" [style.left.%]="p.mean" [style.background]="p.color"
                    [attr.data-tip]="short(p.model) + ': ' + p.mean.toFixed(0)"></span>
            }
            @if (r.job.my_score !== null) {
              <span class="mark mine" [style.left.%]="r.job.my_score" [attr.data-tip]="'Você: ' + r.job.my_score"><i></i></span>
            }
          </div>
        </div>
      }
    </div>
  `,
  styles: `
    :host { display: block; min-width: 0; }
    .legend { display: flex; flex-wrap: wrap; gap: 6px 16px; font-size: 0.85rem; margin-bottom: 12px; }
    .legend span { display: inline-flex; align-items: center; gap: 6px; }
    .legend .muted { color: var(--muted); }
    .legend .dot { position: static; width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
    .legend .diamond { position: static; display: inline-block; width: 9px; height: 9px; background: var(--text); transform: rotate(45deg); }
    .legend .band { display: inline-block; width: 22px; height: 6px; border-radius: 3px; background: var(--surface-2); box-shadow: inset 0 0 0 1px var(--border-strong); }

    .row { display: grid; grid-template-columns: minmax(180px, 32%) 1fr; gap: 16px; align-items: center; min-height: 40px; }
    .row + .row:not(.axis) { border-top: 1px solid var(--border); }
    .axis { min-height: 22px; }
    .name { min-width: 0; padding: 6px 0; line-height: 1.25; }
    .name .title { display: block; font-size: 0.86rem; font-weight: 500; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .name .company { display: block; font-size: 0.75rem; color: var(--faint); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .ticks { position: relative; height: 18px; margin: 0 8px; }
    .ticks span { position: absolute; transform: translateX(-50%); font-size: 0.72rem; color: var(--faint); font-variant-numeric: tabular-nums; }
    .plot {
      position: relative; height: 28px; margin: 0 8px;
      background: linear-gradient(to right, var(--border) 1px, transparent 1px) 0 0 / 25% 100% no-repeat,
                  linear-gradient(to right, var(--border) 1px, transparent 1px) 25% 0 / 25% 100% no-repeat,
                  linear-gradient(to right, var(--border) 1px, transparent 1px) 50% 0 / 25% 100% no-repeat,
                  linear-gradient(to right, var(--border) 1px, transparent 1px) 75% 0 / 25% 100% no-repeat;
      box-shadow: inset -1px 0 0 var(--border);
    }
    .range { position: absolute; top: 50%; height: 6px; margin-top: -3px; border-radius: 3px; background: var(--surface-2);
             box-shadow: inset 0 0 0 1px var(--border-strong); }
    .mark { position: absolute; top: 50%; cursor: default; }
    .mark.dot { width: 12px; height: 12px; margin: -6px 0 0 -6px; border-radius: 50%; box-shadow: 0 0 0 2px var(--surface); }
    .mark.mine { width: 14px; height: 14px; margin: -7px 0 0 -7px; z-index: 1; }
    .mark.mine i { position: absolute; inset: 2px; background: var(--text); transform: rotate(45deg); box-shadow: 0 0 0 2px var(--surface); }
    .mark::before { content: ''; position: absolute; inset: -6px; } /* área de toque maior que o ponto */
    .mark:hover { z-index: 3; }
    .mark.dot:hover { box-shadow: 0 0 0 2px var(--surface), 0 0 0 4px var(--text); }
    .mark:hover::after {
      content: attr(data-tip); position: absolute; bottom: calc(100% + 8px); left: 50%; transform: translateX(-50%);
      padding: 4px 8px; border-radius: 6px; background: var(--text); color: var(--surface); font-size: 0.78rem; font-weight: 600;
      white-space: nowrap; pointer-events: none;
    }

    @media (max-width: 720px) {
      .row { grid-template-columns: 1fr; gap: 2px; padding: 6px 0; }
      .axis { position: sticky; top: 52px; background: var(--surface); z-index: 4; padding: 4px 0 0; }
      .axis .name { display: none; }
      .name { padding: 0; }
    }
  `,
})
export class ScoreChart {
  readonly jobs = input.required<BenchJob[]>();
  readonly models = input.required<string[]>();

  protected readonly ticks = [0, 25, 50, 75, 100];

  protected readonly rows = computed<ChartRow[]>(() =>
    this.jobs().map((job) => {
      const points = this.models()
        .map((model, i) => ({ model, mean: job.models[model]?.mean ?? null, color: modelColor(i) }))
        .filter((p): p is { model: string; mean: number; color: string } => p.mean !== null);
      const means = points.map((p) => p.mean);
      return {
        job,
        points,
        min: means.length ? Math.min(...means) : null,
        max: means.length ? Math.max(...means) : null,
      };
    }),
  );

  protected color(index: number): string {
    return modelColor(index);
  }

  protected short(model: string): string {
    return shortModel(model);
  }
}
