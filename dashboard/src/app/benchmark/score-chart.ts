import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

import { BenchJob } from '../core/models';

export const MODEL_COLORS = ['#0969da', '#bc4c00', '#8250df', '#1a7f37', '#cf222e', '#9a6700'];

const ROW_H = 26;
const LABEL_W = 260;
const PLOT_W = 420;
const PAD_TOP = 26;

/** Uma linha por vaga, eixo 0–100: um ponto por modelo (média das rodadas) e um losango para a minha nota. */
@Component({
  selector: 'app-score-chart',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="legend">
      @for (m of models(); track m; let i = $index) {
        <span><i class="dot" [style.background]="color(i)"></i>{{ m }}</span>
      }
      <span><i class="diamond"></i>Você</span>
    </div>
    <div class="scroll">
      <svg [attr.viewBox]="'0 0 ' + width + ' ' + height()" [attr.width]="width" [attr.height]="height()" role="img"
           aria-label="Notas por vaga e por modelo">
        @for (tick of ticks; track tick) {
          <line class="grid" [attr.x1]="x(tick)" [attr.x2]="x(tick)" [attr.y1]="PAD_TOP - 6" [attr.y2]="height() - 4" />
          <text class="tick" [attr.x]="x(tick)" [attr.y]="PAD_TOP - 10" text-anchor="middle">{{ tick }}</text>
        }
        @for (job of jobs(); track job.id; let r = $index) {
          <g [attr.transform]="'translate(0,' + y(r) + ')'">
            <text class="label" x="0" y="4">
              <title>{{ job.title }} · {{ job.company }}</title>
              {{ short(job.title) }}
            </text>
            <line class="row" [attr.x1]="x(0)" [attr.x2]="x(100)" y1="0" y2="0" />
            @for (m of models(); track m; let i = $index) {
              @let mean = job.models[m]?.mean;
              @if (mean !== null && mean !== undefined) {
                <circle [attr.cx]="x(mean)" cy="0" r="5" [attr.fill]="color(i)">
                  <title>{{ m }}: {{ mean.toFixed(0) }}</title>
                </circle>
              }
            }
            @if (job.my_score !== null) {
              <rect class="mine" [attr.x]="x(job.my_score) - 5" y="-5" width="10" height="10"
                    [attr.transform]="'rotate(45 ' + x(job.my_score) + ' 0)'">
                <title>Você: {{ job.my_score }}</title>
              </rect>
            }
          </g>
        }
      </svg>
    </div>
  `,
  styles: `
    .legend { display: flex; flex-wrap: wrap; gap: 14px; font-size: 0.85rem; margin-bottom: 8px; }
    .legend span { display: inline-flex; align-items: center; gap: 6px; }
    .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; }
    .diamond { width: 9px; height: 9px; background: var(--text); transform: rotate(45deg); display: inline-block; }
    .scroll { overflow-x: auto; }
    svg { display: block; font-size: 12px; }
    .grid { stroke: var(--border); }
    .row { stroke: var(--surface-2); stroke-width: 2; }
    .tick { fill: var(--muted); }
    .label { fill: var(--text); }
    .mine { fill: var(--text); }
    circle { fill-opacity: 0.85; }
  `,
})
export class ScoreChart {
  readonly jobs = input.required<BenchJob[]>();
  readonly models = input.required<string[]>();

  protected readonly PAD_TOP = PAD_TOP;
  protected readonly width = LABEL_W + PLOT_W + 16;
  protected readonly ticks = [0, 25, 50, 75, 100];
  protected readonly height = computed(() => PAD_TOP + this.jobs().length * ROW_H + 8);

  protected x(score: number): number {
    return LABEL_W + (score / 100) * PLOT_W;
  }

  protected y(row: number): number {
    return PAD_TOP + ROW_H / 2 + row * ROW_H;
  }

  protected color(index: number): string {
    return MODEL_COLORS[index % MODEL_COLORS.length];
  }

  protected short(title: string): string {
    return title.length > 38 ? title.slice(0, 37) + '…' : title;
  }
}
