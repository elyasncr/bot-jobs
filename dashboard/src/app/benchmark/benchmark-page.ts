import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';

import { ApiService } from '../core/api.service';
import { BenchJob, BenchmarkPayload, BenchmarkRun, ModelSummary, PjStatus, shortModel } from '../core/models';
import { LabelInput, SaveState } from '../shared/label-input';
import { BenchmarkSummary, bestModels } from './benchmark-summary';
import { RunBenchmark } from './run-benchmark';
import { ScoreChart, modelColor } from './score-chart';

const PJ_SHORT: Record<PjStatus, string> = { pj: 'PJ', both: 'PJ/CLT', clt: 'CLT', uncertain: '?' };

/** Mesmo mínimo do eval_report (MIN_GOLD_FOR_DECISION). */
const MIN_GOLD = 5;

interface Winner {
  title: string;
  models: string[];
  value: string;
  hint: string;
}

interface Cell {
  totals: string;
  pj: string;
  warn: boolean;
}

@Component({
  selector: 'app-benchmark-page',
  imports: [BenchmarkSummary, ScoreChart, LabelInput, RunBenchmark],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="head">
      <div>
        <h1>Benchmark de modelos</h1>
        <p>Os modelos locais avaliando as mesmas vagas, lado a lado.</p>
      </div>
      @if (runs().length) {
        <label class="run">
          <span>Resultado</span>
          <select [value]="run()" (change)="selectRun($any($event.target).value)">
            @for (r of runs(); track r.file) {
              <option [value]="r.file">{{ r.date?.replace('T', ' ')?.slice(0, 16) }} · {{ r.models.length }} modelos · {{ r.jobs }} vagas</option>
            }
          </select>
        </label>
      }
      <app-run-benchmark (finished)="onBenchmarkFinished($event)" />
    </header>

    @if (!runs().length && !loading()) {
      <div class="empty">
        <strong>Nenhum benchmark salvo ainda.</strong>
        <p>Clique em <strong>Rodar benchmark</strong> (ou rode <code>uv run python -m vagas_bot eval-models qwen3.5:9b gemma4:12b</code>) e recarregue.</p>
      </div>
    } @else if (payload(); as p) {
      <div class="meta">
        <span class="tag">{{ p.meta.runs }} rodadas por vaga</span>
        <span class="tag">num_ctx {{ p.meta.num_ctx }}</span>
        <span class="tag">temperature {{ p.meta.temperature }}</span>
        <span class="tag">think {{ p.meta.think ? 'on' : 'off' }}</span>
      </div>

      <section class="winners" aria-label="Destaques">
        @for (w of winners(); track w.title) {
          <article class="card" [class.pending]="!w.models.length">
            <h2>{{ w.title }}@if (w.models.length > 1) { <span class="tie">empate</span>}</h2>
            @for (m of w.models; track m) {
              <p class="model"><i class="dot" [style.background]="colorOf(m)"></i>{{ short(m) }}</p>
            }
            <p class="value">{{ w.value }}</p>
            <p class="hint">{{ w.hint }}</p>
          </article>
        }
      </section>

      <section class="progress" [class.done]="labeled() >= minGold">
        <div class="progress-text">
          <strong>Suas notas: {{ labeled() }} de {{ p.jobs.length }}</strong>
          @if (labeled() < minGold) {
            <span>Dê nota a pelo menos {{ minGold }} vagas para medir qual modelo concorda mais com você.</span>
          } @else {
            <span>O Spearman contra as suas notas já aparece na tabela.</span>
          }
        </div>
        <div class="bar"><span [style.width.%]="(labeled() / (p.jobs.length || 1)) * 100"></span></div>
        <a href="#lado-a-lado" (click)="scrollTo($event, 'lado-a-lado')">Dar notas ↓</a>
      </section>

      <section>
        <h2 class="section-title">Métricas</h2>
        <app-benchmark-summary [rows]="p.summaries" />
        @if (p.reading.length) {
          <details>
            <summary>Leitura automática completa</summary>
            <ul>
              @for (line of p.reading; track $index) {
                <li>{{ line }}</li>
              }
            </ul>
          </details>
        }
      </section>

      <section class="panel">
        <h2 class="section-title">Notas por vaga</h2>
        <app-score-chart [jobs]="p.jobs" [models]="models()" />
      </section>

      <section id="lado-a-lado">
        <h2 class="section-title">Lado a lado</h2>
        <p class="note">Nota final em cada rodada (✗ = falha) e contrato respondido (⚠ = "CLT" sem evidência no texto). Sua nota recalcula o Spearman.</p>
        <div class="frame">
          <table>
            <thead>
              <tr>
                <th>Vaga</th>
                <th class="num">Sua nota</th>
                @for (m of models(); track m; let i = $index) {
                  <th class="num"><span class="mh"><i class="dot" [style.background]="color(i)"></i>{{ short(m) }}</span></th>
                }
              </tr>
            </thead>
            <tbody>
              @for (job of p.jobs; track job.id) {
                <tr>
                  <td class="job">
                    <a [href]="job.url" target="_blank" rel="noopener">{{ job.title }}</a>
                    <span class="company">{{ job.company }}</span>
                  </td>
                  <td class="num">
                    <app-label-input [value]="job.my_score" [state]="saveStates()[job.id] ?? 'idle'"
                                     [error]="saveErrors()[job.id] ?? null" (save)="saveLabel(job, $event)" />
                  </td>
                  @for (m of models(); track m) {
                    @let c = cell(job, m);
                    <td class="num">
                      <span class="totals">{{ c.totals }}</span>
                      @if (c.pj) {
                        <span class="pj" [class.warn]="c.warn">{{ c.pj }}@if (c.warn) { ⚠}</span>
                      }
                    </td>
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
  `,
  styles: `
    :host { display: block; }
    .head { display: flex; flex-wrap: wrap; align-items: end; gap: 12px; margin-bottom: 12px; }
    .head > div:first-child { margin-right: auto; }
    h1 { margin: 0; font-size: 1.5rem; letter-spacing: -0.02em; }
    .head p { margin: 2px 0 0; color: var(--muted); }
    .run { display: flex; flex-direction: column; gap: 4px; font-size: 0.72rem; font-weight: 600; color: var(--faint);
           text-transform: uppercase; letter-spacing: 0.04em; }
    .run select { font-size: 0.88rem; text-transform: none; letter-spacing: 0; font-weight: 400; color: var(--text); }
    .meta { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 18px; }
    section { margin-top: 28px; }
    .section-title { margin: 0 0 10px; font-size: 1rem; letter-spacing: -0.01em; }

    .winners { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 12px; margin-top: 0; }
    .card { padding: 14px 16px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); box-shadow: var(--shadow-sm); }
    .card h2 { margin: 0 0 8px; font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: var(--faint); }
    .card .model { display: flex; align-items: center; gap: 8px; margin: 0; font-weight: 700; font-size: 1.05rem; }
    .tie { margin-left: 6px; padding: 1px 6px; border-radius: 999px; background: var(--surface-2); color: var(--muted); text-transform: none; letter-spacing: 0; }
    .card .value { margin: 2px 0 0; font-size: 0.9rem; font-variant-numeric: tabular-nums; }
    .card .hint { margin: 6px 0 0; font-size: 0.78rem; color: var(--faint); }
    .card.pending { border-style: dashed; background: transparent; box-shadow: none; }
    .card.pending .value { font-weight: 600; color: var(--muted); font-size: 0.95rem; }
    .dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; flex: none; }

    .progress { display: grid; grid-template-columns: 1fr minmax(120px, 220px) auto; align-items: center; gap: 8px 20px;
                margin-top: 12px; padding: 12px 16px; border-radius: var(--radius); background: var(--accent-bg); }
    .progress-text { display: flex; flex-direction: column; gap: 2px; font-size: 0.88rem; }
    .progress-text strong { color: var(--accent); }
    .progress-text span { color: var(--muted); }
    .bar { height: 6px; border-radius: 3px; background: color-mix(in srgb, var(--accent) 18%, transparent); overflow: hidden; }
    .bar span { display: block; height: 100%; border-radius: 3px; background: var(--accent); }
    .progress a { color: var(--accent); font-weight: 600; font-size: 0.88rem; text-decoration: none; white-space: nowrap; }
    .progress a:hover { text-decoration: underline; }
    .progress.done { background: var(--high-bg); }
    .progress.done strong, .progress.done a { color: var(--high); }
    .progress.done .bar span { background: var(--high); }

    details { margin-top: 12px; font-size: 0.88rem; color: var(--muted); }
    summary { cursor: pointer; font-weight: 500; color: var(--text); width: fit-content; }
    details ul { margin: 8px 0 0; padding-left: 20px; line-height: 1.6; }

    .panel { padding: 16px 18px; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); box-shadow: var(--shadow-sm); }
    .note { margin: -4px 0 10px; font-size: 0.82rem; color: var(--muted); }
    .frame { overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); box-shadow: var(--shadow-sm); }
    table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
    th, td { padding: 10px 12px; border-bottom: 1px solid var(--border); vertical-align: middle; }
    tbody tr:last-child td { border-bottom: 0; }
    tbody tr:hover { background: var(--hover); }
    thead th { font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: var(--faint); text-align: left; white-space: nowrap; }
    .mh { display: inline-flex; align-items: center; gap: 6px; text-transform: none; letter-spacing: 0; font-size: 0.82rem; color: var(--text); }
    .num { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
    .job { min-width: 260px; }
    .job a { color: var(--text); font-weight: 600; text-decoration: none; }
    .job a:hover { color: var(--accent); text-decoration: underline; text-underline-offset: 2px; }
    .company { display: block; color: var(--muted); font-size: 0.82rem; }
    .totals { font-weight: 600; }
    .pj { display: block; font-size: 0.75rem; color: var(--faint); }
    .pj.warn { color: var(--danger); font-weight: 600; }
    .muted { color: var(--muted); }
    .empty { text-align: center; padding: 56px 16px; border: 1px dashed var(--border-strong); border-radius: var(--radius); }
    .empty p { color: var(--muted); }
    code { background: var(--surface-2); padding: 2px 6px; border-radius: 4px; font-size: 0.85em; }

    @media (max-width: 720px) {
      h1 { font-size: 1.3rem; }
      .head p { font-size: 0.88rem; }
      .run { width: 100%; }
      .run select { width: 100%; }
      .winners { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
      .card { padding: 12px; }
      .card .model { font-size: 0.95rem; }
      .progress { grid-template-columns: 1fr; }
      .panel { padding: 12px; }
    }
  `,
})
export class BenchmarkPage {
  private readonly api = inject(ApiService);

  protected readonly minGold = MIN_GOLD;
  protected readonly runs = signal<BenchmarkRun[]>([]);
  protected readonly run = signal<string>('');
  protected readonly payload = signal<BenchmarkPayload | null>(null);
  protected readonly loading = signal(true);
  protected readonly saveStates = signal<Record<string, SaveState>>({});
  protected readonly saveErrors = signal<Record<string, string>>({});

  protected readonly models = computed(() => this.payload()?.summaries.map((s) => s.model) ?? []);
  protected readonly labeled = computed(() => this.payload()?.jobs.filter((j) => j.my_score !== null).length ?? 0);

  protected readonly winners = computed<Winner[]>(() => {
    const rows = this.payload()?.summaries ?? [];
    const fmt = (n: number | null | undefined, digits = 1) => (n === null || n === undefined ? '—' : n.toFixed(digits).replace('.', ','));
    const pick = (value: (s: ModelSummary) => number | null, better: 'min' | 'max') => {
      const models = bestModels(rows, value, better);
      return { models, first: rows.find((r) => r.model === models[0]) };
    };

    const speed = pick((s) => s.mean_s, 'min');
    const stable = pick((s) => s.mean_abs_diff, 'min');
    const clt = pick((s) => s.clt_without_evidence, 'min');
    const enoughGold = rows.some((s) => s.n_gold >= MIN_GOLD);
    const gold = enoughGold ? pick((s) => s.spearman_gold, 'max') : null;
    const missing = Math.max(0, MIN_GOLD - this.labeled());

    return [
      {
        title: 'Mais rápido',
        models: speed.models,
        value: `${fmt(speed.first?.mean_s)} s por vaga`,
        hint: speed.first?.vram_gb ? `${fmt(speed.first.vram_gb)} GB de VRAM` : '',
      },
      {
        title: 'Mais estável',
        models: stable.models,
        value: `Δ ${fmt(stable.first?.mean_abs_diff)} ponto entre rodadas`,
        hint: 'mesma vaga, mesma nota',
      },
      {
        title: 'Menos "CLT" inventado',
        models: clt.models,
        value: `${clt.first?.clt_without_evidence ?? '—'} resposta(s) "CLT" sem evidência`,
        hint: 'sem sinal de CLT no texto da vaga',
      },
      gold?.first
        ? {
            title: 'Mais parecido com você',
            models: gold.models,
            value: `Spearman ${fmt(gold.first.spearman_gold, 2)}`,
            hint: `${gold.first.n_gold} vagas com nota sua`,
          }
        : {
            title: 'Mais parecido com você',
            models: [],
            value: missing ? `Faltam ${missing} ${missing === 1 ? 'nota sua' : 'notas suas'}` : 'Recalculando…',
            hint: `com ${MIN_GOLD} notas dá para comparar`,
          },
    ];
  });

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

  /** Rodada nova terminou: recarrega a lista e mostra o resultado novo. */
  protected onBenchmarkFinished(file: string): void {
    this.api.benchmarkRuns().subscribe({
      next: (runs) => {
        this.runs.set(runs);
        if (runs.length) this.selectRun(runs.some((r) => r.file === file) ? file : runs[0].file);
      },
      error: () => undefined,
    });
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
    return modelColor(index);
  }

  protected colorOf(model: string): string {
    return modelColor(Math.max(0, this.models().indexOf(model)));
  }

  protected short(model: string): string {
    return shortModel(model);
  }

  protected scrollTo(event: Event, id: string): void {
    event.preventDefault(); // o href com # mudaria a rota
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  protected cell(job: BenchJob, model: string): Cell {
    const result = job.models[model];
    if (!result || !result.totals.length) return { totals: '—', pj: '', warn: false };
    const totals = result.totals.map((t) => (t === null ? '✗' : String(t))).join(' / ');
    const statuses = [...new Set(result.pj_status.filter((s): s is PjStatus => s !== null))].sort();
    return {
      totals,
      pj: statuses.map((s) => PJ_SHORT[s]).join(' · '),
      warn: statuses.includes('clt') && !job.clt_signals,
    };
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
