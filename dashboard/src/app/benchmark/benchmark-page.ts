import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';

import { ApiService } from '../core/api.service';
import { BenchJob, BenchmarkPayload, BenchmarkRun, PjStatus } from '../core/models';
import { LabelInput, SaveState } from '../shared/label-input';
import { BenchmarkSummary } from './benchmark-summary';
import { MODEL_COLORS, ScoreChart } from './score-chart';

const PJ_SHORT: Record<PjStatus, string> = { pj: 'PJ', both: 'PJ/CLT', clt: 'CLT', uncertain: '?' };

@Component({
  selector: 'app-benchmark-page',
  imports: [BenchmarkSummary, ScoreChart, LabelInput],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (!runs().length && !loading()) {
      <div class="empty">
        <p>Nenhum benchmark salvo ainda.</p>
        <p class="muted">Rode <code>uv run python -m vagas_bot eval-models qwen3.5:9b gemma4:12b</code> e recarregue.</p>
      </div>
    } @else {
      <div class="toolbar">
        <label>
          Resultado
          <select [value]="run()" (change)="selectRun($any($event.target).value)">
            @for (r of runs(); track r.file) {
              <option [value]="r.file">{{ r.date?.replace('T', ' ') }} · {{ r.models.length }} modelos · {{ r.jobs }} vagas</option>
            }
          </select>
        </label>
        @if (payload(); as p) {
          <span class="muted">
            {{ p.meta.runs }} rodadas por vaga · num_ctx {{ p.meta.num_ctx }} · temperature {{ p.meta.temperature }} ·
            think {{ p.meta.think }} · suas notas: {{ labeled() }} de {{ p.jobs.length }}
          </span>
        }
      </div>

      @if (payload(); as p) {
        <app-benchmark-summary [rows]="p.summaries" />

        <section class="reading">
          <h2>Leitura automática</h2>
          <ul>
            @for (line of p.reading; track $index) {
              <li>{{ line }}</li>
            }
          </ul>
        </section>

        <section>
          <h2>Notas por vaga</h2>
          <app-score-chart [jobs]="p.jobs" [models]="models()" />
        </section>

        <section>
          <h2>Lado a lado</h2>
          <p class="muted small">Nota final por rodada (✗ = falha) · contrato (⚠ = "CLT" sem evidência no texto). Sua nota recalcula o Spearman.</p>
          <div class="scroll">
            <table>
              <thead>
                <tr>
                  <th>Vaga</th>
                  <th class="num">Você</th>
                  @for (m of models(); track m; let i = $index) {
                    <th class="num"><i class="dot" [style.background]="color(i)"></i>{{ m }}</th>
                  }
                </tr>
              </thead>
              <tbody>
                @for (job of p.jobs; track job.id) {
                  <tr>
                    <td class="job">
                      <a [href]="job.url" target="_blank" rel="noopener">{{ job.title }}</a>
                      <span class="muted">{{ job.company }}</span>
                    </td>
                    <td class="num">
                      <app-label-input [value]="job.my_score" [state]="saveStates()[job.id] ?? 'idle'"
                                       [error]="saveErrors()[job.id] ?? null" (save)="saveLabel(job, $event)" />
                    </td>
                    @for (m of models(); track m) {
                      <td class="num">{{ cell(job, m) }}</td>
                    }
                  </tr>
                }
              </tbody>
            </table>
          </div>
        </section>
      } @else if (loading()) {
        <p class="muted">Carregando benchmark…</p>
      }
    }
  `,
  styles: `
    :host { display: block; }
    section { margin-top: 22px; }
    h2 { font-size: 1rem; margin: 0 0 8px; }
    .toolbar { display: flex; flex-wrap: wrap; align-items: end; gap: 10px 18px; margin-bottom: 14px; }
    .toolbar label { display: flex; flex-direction: column; gap: 3px; font-size: 0.75rem; color: var(--muted); }
    .reading ul { margin: 0; padding-left: 20px; line-height: 1.6; }
    .scroll { overflow-x: auto; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }
    table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
    th, td { padding: 7px 10px; border-bottom: 1px solid var(--border); }
    thead th { background: var(--surface-2); text-align: left; white-space: nowrap; }
    .num { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
    .job { min-width: 260px; }
    .job a { color: var(--text); font-weight: 600; text-decoration: none; }
    .job a:hover { text-decoration: underline; }
    .job .muted { display: block; }
    .dot { width: 9px; height: 9px; border-radius: 50%; display: inline-block; margin-right: 6px; }
    .muted { color: var(--muted); }
    .small { font-size: 0.82rem; }
    .empty { text-align: center; padding: 48px 16px; }
    code { background: var(--surface-2); padding: 2px 6px; border-radius: 4px; }
  `,
})
export class BenchmarkPage {
  private readonly api = inject(ApiService);

  protected readonly runs = signal<BenchmarkRun[]>([]);
  protected readonly run = signal<string>('');
  protected readonly payload = signal<BenchmarkPayload | null>(null);
  protected readonly loading = signal(true);
  protected readonly saveStates = signal<Record<string, SaveState>>({});
  protected readonly saveErrors = signal<Record<string, string>>({});

  protected readonly models = computed(() => this.payload()?.summaries.map((s) => s.model) ?? []);
  protected readonly labeled = computed(() => this.payload()?.jobs.filter((j) => j.my_score !== null).length ?? 0);

  constructor() {
    this.api.benchmarkRuns().subscribe({
      next: (runs) => {
        this.runs.set(runs);
        if (runs.length) {
          this.selectRun(runs[0].file);
        } else {
          this.loading.set(false);
        }
      },
      error: () => this.loading.set(false),
    });
  }

  protected selectRun(file: string): void {
    this.run.set(file);
    this.load();
  }

  private load(): void {
    this.loading.set(true);
    this.api.benchmark(this.run()).subscribe({
      next: (p) => {
        this.payload.set(p);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  protected color(index: number): string {
    return MODEL_COLORS[index % MODEL_COLORS.length];
  }

  protected cell(job: BenchJob, model: string): string {
    const result = job.models[model];
    if (!result || !result.totals.length) return '—';
    const totals = result.totals.map((t) => (t === null ? '✗' : String(t))).join(' / ');
    const statuses = [...new Set(result.pj_status.filter((s): s is PjStatus => s !== null))].sort();
    const pj = statuses.map((s) => PJ_SHORT[s]).join('/');
    const warn = statuses.includes('clt') && !job.clt_signals ? ' ⚠' : '';
    return pj ? `${totals} · ${pj}${warn}` : totals;
  }

  protected saveLabel(job: BenchJob, score: number | null): void {
    this.saveStates.update((s) => ({ ...s, [job.id]: 'saving' }));
    this.api.saveLabel(job.id, score).subscribe({
      next: () => {
        this.saveStates.update((s) => ({ ...s, [job.id]: 'saved' }));
        this.api.benchmark(this.run()).subscribe((p) => this.payload.set(p)); // Spearman recalculado
      },
      error: (err: Error) => {
        this.saveErrors.update((e) => ({ ...e, [job.id]: err.message }));
        this.saveStates.update((s) => ({ ...s, [job.id]: 'error' }));
      },
    });
  }
}
