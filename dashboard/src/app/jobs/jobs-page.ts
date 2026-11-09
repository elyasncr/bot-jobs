import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { toSignal } from '@angular/core/rxjs-interop';
import { ActivatedRoute, Params, Router } from '@angular/router';
import { map } from 'rxjs';

import { ApiService } from '../core/api.service';
import {
  CONTRACT_LABELS,
  FilterReason,
  JobRow,
  PjStatus,
  REASON_LABELS,
  STAGE_LABELS,
  Stage,
  formatDate,
  sourceLabel,
} from '../core/models';
import { FilterMenu } from '../shared/filter-menu';
import { SaveState } from '../shared/label-input';
import { DetailSave, JobDetail } from './job-detail';
import {
  EMPTY_FILTERS,
  JobFilters,
  SortDir,
  SortKey,
  applyFilters,
  countsBy,
  filtersFromParams,
  filtersToParams,
  sortRows,
} from './job-filters';
import { JobsTable, LabelChange } from './jobs-table';

const SORT_KEYS: SortKey[] = ['date', 'total', 'cosine', 'mine'];

const SORT_OPTIONS: { value: string; label: string }[] = [
  { value: 'date:desc', label: 'Mais recentes' },
  { value: 'date:asc', label: 'Mais antigas' },
  { value: 'total:desc', label: 'Maior nota do LLM' },
  { value: 'total:asc', label: 'Menor nota do LLM' },
  { value: 'cosine:desc', label: 'Maior cos' },
  { value: 'cosine:asc', label: 'Menor cos' },
  { value: 'mine:desc', label: 'Maior nota sua' },
  { value: 'mine:asc', label: 'Menor nota sua' },
];

const SCORE_PRESETS: { min: number; label: string }[] = [
  { min: 80, label: 'Alta (80+)' },
  { min: 65, label: 'Boa ou melhor (65+)' },
  { min: 50, label: 'Possível ou melhor (50+)' },
];

const FUNNEL_STAGES = {
  all: [] as Stage[],
  passed: ['emailed', 'evaluated'] as Stage[],
  emailed: ['emailed'] as Stage[],
  filtered: ['filtered'] as Stage[],
  older: ['history', 'benchmark'] as Stage[],
};

interface Chip {
  text: string;
  next: JobFilters;
}

function isoDaysAgo(days: number, today = new Date()): string {
  const d = new Date(today.getFullYear(), today.getMonth(), today.getDate() - days);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function sameSet(a: readonly string[], b: readonly string[]): boolean {
  return a.length === b.length && a.every((v) => b.includes(v));
}

@Component({
  selector: 'app-jobs-page',
  imports: [JobsTable, JobDetail, FilterMenu],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="head">
      <h1>Vagas</h1>
      <p>Tudo o que o bot capturou, inclusive o que ficou pelo caminho.</p>
    </header>

    @let c = funnel();
    <nav class="funnel" aria-label="Etapas">
      <button type="button" class="seg" [class.on]="stageIs('all')" (click)="setStages('all')">
        <span class="label">Capturadas</span><strong>{{ c.total }}</strong>
      </button>
      <span class="arrow" aria-hidden="true">›</span>
      <button type="button" class="seg" [class.on]="stageIs('passed')" (click)="setStages('passed')">
        <span class="label"><i class="stage-dot" data-stage="evaluated"></i>Passaram nos filtros</span><strong>{{ c.evaluated }}</strong>
      </button>
      <span class="arrow" aria-hidden="true">›</span>
      <button type="button" class="seg" [class.on]="stageIs('emailed')" (click)="setStages('emailed')">
        <span class="label"><i class="stage-dot" data-stage="emailed"></i>Enviadas por email</span><strong>{{ c.emailed }}</strong>
      </button>
      <span class="divider" aria-hidden="true"></span>
      <button type="button" class="seg" [class.on]="stageIs('filtered')" (click)="setStages('filtered')">
        <span class="label"><i class="stage-dot" data-stage="filtered"></i>Filtradas</span><strong>{{ c.filtered }}</strong>
        @if (c.filtered) {
          <small>{{ reasonSummary() }}</small>
        }
      </button>
      <button type="button" class="seg" [class.on]="stageIs('older')" (click)="setStages('older')"
              title="Vagas do histórico e do benchmark, de antes do arquivo completo">
        <span class="label"><i class="stage-dot" data-stage="history"></i>Histórico e benchmark</span><strong>{{ c.older }}</strong>
      </button>
      <span class="divider" aria-hidden="true"></span>
      <button type="button" class="seg todo" [class.on]="filters().unlabeled" (click)="patch({ unlabeled: !filters().unlabeled })"
              [attr.aria-pressed]="filters().unlabeled">
        <span class="label">Sem nota sua</span><strong>{{ c.unlabeled }}</strong>
      </button>
    </nav>

    <div class="toolbar">
      <label class="search">
        <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
          <circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.6" />
          <path d="M10.5 10.5 14 14" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" />
        </svg>
        <span class="visually-hidden">Buscar</span>
        <input type="search" placeholder="Buscar por título ou empresa" [value]="filters().q"
               (input)="patch({ q: $any($event.target).value })" />
      </label>

      <div class="menus">
        <app-filter-menu label="Etapa" [count]="filters().stages.length + filters().reasons.length">
          <p class="group-title">Etapa</p>
          @for (s of stageKeys; track s) {
            <label class="opt">
              <input type="checkbox" [checked]="filters().stages.includes(s)" (change)="toggle('stages', s)" />
              <i class="stage-dot" [attr.data-stage]="s"></i>{{ stageLabels[s] }}
              <span class="n">{{ optionCounts().stages[s] ?? 0 }}</span>
            </label>
          }
          <p class="group-title">Motivo do filtro</p>
          @for (r of reasonKeys; track r) {
            <label class="opt">
              <input type="checkbox" [checked]="filters().reasons.includes(r)" (change)="toggle('reasons', r)" />{{ reasonLabels[r] }}
              <span class="n">{{ optionCounts().reasons[r] ?? 0 }}</span>
            </label>
          }
        </app-filter-menu>

        <app-filter-menu label="Fonte" [count]="filters().sources.length">
          @for (s of sources(); track s) {
            <label class="opt">
              <input type="checkbox" [checked]="filters().sources.includes(s)" (change)="toggle('sources', s)" />{{ sourceName(s) }}
              <span class="n">{{ optionCounts().sources[s] ?? 0 }}</span>
            </label>
          }
        </app-filter-menu>

        <app-filter-menu label="Contrato" [count]="filters().contracts.length">
          @for (k of contractKeys; track k) {
            <label class="opt">
              <input type="checkbox" [checked]="filters().contracts.includes(k)" (change)="toggle('contracts', k)" />{{ contractLabels[k] }}
              <span class="n">{{ optionCounts().contracts[k] ?? 0 }}</span>
            </label>
          }
        </app-filter-menu>

        <app-filter-menu label="Nota do LLM" [count]="filters().minScore !== null || filters().maxScore !== null ? 1 : 0">
          @for (p of scorePresets; track p.min) {
            <label class="opt">
              <input type="radio" name="score-preset" [checked]="filters().minScore === p.min && filters().maxScore === null"
                     (change)="patch({ minScore: p.min, maxScore: null })" />{{ p.label }}
            </label>
          }
          <p class="group-title">Faixa</p>
          <div class="range">
            <input type="number" min="0" max="100" placeholder="mín" [value]="filters().minScore ?? ''"
                   (change)="patch({ minScore: numberOrNull($any($event.target).value) })" aria-label="Nota mínima" />
            <span>até</span>
            <input type="number" min="0" max="100" placeholder="máx" [value]="filters().maxScore ?? ''"
                   (change)="patch({ maxScore: numberOrNull($any($event.target).value) })" aria-label="Nota máxima" />
          </div>
        </app-filter-menu>

        <app-filter-menu label="Data" align="end" [count]="filters().from || filters().to ? 1 : 0">
          @for (d of datePresets; track d.days) {
            <label class="opt">
              <input type="radio" name="date-preset" [checked]="filters().from === since(d.days) && !filters().to"
                     (change)="patch({ from: since(d.days), to: '' })" />{{ d.label }}
            </label>
          }
          <p class="group-title">Capturada entre</p>
          <div class="range dates">
            <input type="date" [value]="filters().from" (change)="patch({ from: $any($event.target).value })" aria-label="De" />
            <input type="date" [value]="filters().to" (change)="patch({ to: $any($event.target).value })" aria-label="Até" />
          </div>
        </app-filter-menu>
      </div>
    </div>

    @if (chips().length) {
      <div class="chips" aria-label="Filtros ativos">
        @for (chip of chips(); track chip.text) {
          <button type="button" class="chip" (click)="writeFilters(chip.next)" [attr.aria-label]="'Remover filtro ' + chip.text">
            {{ chip.text }}<span aria-hidden="true">×</span>
          </button>
        }
        <button type="button" class="clear" (click)="clear()">Limpar tudo</button>
      </div>
    }

    <div class="results">
      <span><strong>{{ visible().length }}</strong> {{ visible().length === 1 ? 'vaga' : 'vagas' }}</span>
      <label class="sort">
        Ordenar
        <select [value]="sort().key + ':' + sort().dir" (change)="setParams({ ordem: $any($event.target).value })">
          @for (o of sortOptions; track o.value) {
            <option [value]="o.value">{{ o.label }}</option>
          }
        </select>
      </label>
    </div>

    @if (loading()) {
      <div class="skeleton" aria-busy="true">
        @for (i of [1, 2, 3, 4, 5]; track i) {
          <div></div>
        }
      </div>
    } @else {
      <app-jobs-table
        [rows]="visible()"
        [sortKey]="sort().key"
        [sortDir]="sort().dir"
        [selectedId]="selectedId()"
        [saveStates]="saveStates()"
        [saveErrors]="saveErrors()"
        (sortChange)="setParams({ ordem: $event.key + ':' + $event.dir })"
        (select)="setParams({ vaga: $event })"
        (labelChange)="saveFromTable($event)"
      />
    }

    @if (selected(); as job) {
      <app-job-detail
        [row]="job"
        [state]="saveStates()[job.id] ?? 'idle'"
        [error]="saveErrors()[job.id] ?? null"
        (close)="setParams({ vaga: null })"
        (save)="saveFromDetail(job, $event)"
      />
    }
  `,
  styles: `
    :host { display: block; }
    .head { margin-bottom: 16px; }
    h1 { margin: 0; font-size: 1.5rem; letter-spacing: -0.02em; }
    .head p { margin: 2px 0 0; color: var(--muted); }

    .funnel {
      display: flex; align-items: stretch; margin-bottom: 16px; overflow-x: auto; scrollbar-width: none;
      background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow-sm);
    }
    .funnel::-webkit-scrollbar { display: none; }
    .seg {
      all: unset; box-sizing: border-box; cursor: pointer; flex: 1 0 auto; display: flex; flex-direction: column; gap: 2px;
      padding: 12px 18px; min-width: 120px; position: relative;
    }
    .seg:hover { background: var(--hover); }
    .seg:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
    .seg .label { display: inline-flex; align-items: center; gap: 6px; font-size: 0.78rem; font-weight: 500; color: var(--muted); white-space: nowrap; }
    .seg strong { font-size: 1.5rem; font-weight: 700; line-height: 1.2; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
    .seg small { font-size: 0.74rem; color: var(--faint); white-space: nowrap; }
    .seg.on { background: var(--accent-bg); box-shadow: inset 0 -2px 0 var(--accent); }
    .seg.on .label { color: var(--accent); }
    .seg.todo strong { color: var(--accent); }
    .arrow { align-self: center; color: var(--faint); font-size: 1.2rem; padding: 0 2px; }
    .divider { width: 1px; margin: 12px 0; background: var(--border); flex: none; }

    .toolbar { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; margin-bottom: 10px; }
    .search { position: relative; flex: 1 1 280px; display: flex; align-items: center; }
    .search svg { position: absolute; left: 11px; color: var(--faint); pointer-events: none; }
    .search input { width: 100%; height: 36px; padding-left: 34px; }
    .menus { display: flex; gap: 8px; flex-wrap: wrap; }

    .group-title { margin: 10px 8px 4px; font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: var(--faint); }
    .group-title:first-child { margin-top: 4px; }
    .opt { display: flex; align-items: center; gap: 8px; padding: 7px 8px; border-radius: 8px; cursor: pointer; font-size: 0.9rem; }
    .opt:hover { background: var(--hover); }
    .opt input { margin: 0; accent-color: var(--accent); width: 16px; height: 16px; }
    .opt .n { margin-left: auto; padding-left: 12px; color: var(--faint); font-size: 0.8rem; font-variant-numeric: tabular-nums; }
    .range { display: flex; align-items: center; gap: 8px; padding: 4px 8px 6px; color: var(--muted); font-size: 0.85rem; }
    .range input { width: 5.5em; }
    .range.dates { flex-direction: column; align-items: stretch; }
    .range.dates input { width: 100%; }

    .chips { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; margin-bottom: 10px; }
    .chip {
      all: unset; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; padding: 3px 6px 3px 10px;
      border-radius: 999px; background: var(--accent-bg); color: var(--accent); font-size: 0.82rem; font-weight: 500;
    }
    .chip span { display: inline-grid; place-items: center; width: 16px; height: 16px; border-radius: 50%; font-size: 0.9rem; }
    .chip:hover span { background: var(--accent); color: var(--on-accent); }
    .chip:focus-visible, .clear:focus-visible { outline: 2px solid var(--accent); }
    .clear { all: unset; cursor: pointer; color: var(--muted); font-size: 0.82rem; padding: 3px 6px; }
    .clear:hover { color: var(--text); text-decoration: underline; }

    .results { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 14px 2px 8px; color: var(--muted); font-size: 0.88rem; }
    .results strong { color: var(--text); }
    .sort { display: inline-flex; align-items: center; gap: 8px; }
    .sort select { padding: 4px 8px; font-size: 0.85rem; }

    .skeleton { display: grid; gap: 1px; border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; background: var(--border); }
    .skeleton div { height: 64px; background: linear-gradient(90deg, var(--surface) 0%, var(--surface-2) 50%, var(--surface) 100%);
                    background-size: 200% 100%; animation: shimmer 1.2s infinite linear; }
    @keyframes shimmer { to { background-position: -200% 0; } }

    @media (max-width: 720px) {
      .head { margin-bottom: 12px; }
      h1 { font-size: 1.3rem; }
      .head p { font-size: 0.88rem; }
      .funnel { margin: 0 -16px 12px; border-radius: 0; border-left: 0; border-right: 0; }
      .seg { flex: none; min-width: 0; padding: 10px 14px; }
      .seg strong { font-size: 1.25rem; }
      .search { flex-basis: 100%; }
      .menus { flex-wrap: nowrap; overflow-x: auto; margin: 0 -16px; padding: 0 16px 2px; scrollbar-width: none; }
      .menus::-webkit-scrollbar { display: none; }
      .opt { padding: 11px 8px; font-size: 1rem; }
    }
  `,
})
export class JobsPage {
  private readonly api = inject(ApiService);
  private readonly router = inject(Router);
  private readonly route = inject(ActivatedRoute);

  protected readonly stageKeys = Object.keys(STAGE_LABELS) as Stage[];
  protected readonly reasonKeys = Object.keys(REASON_LABELS) as FilterReason[];
  protected readonly contractKeys = Object.keys(CONTRACT_LABELS) as PjStatus[];
  protected readonly stageLabels = STAGE_LABELS;
  protected readonly reasonLabels = REASON_LABELS;
  protected readonly contractLabels = CONTRACT_LABELS;
  protected readonly sortOptions = SORT_OPTIONS;
  protected readonly scorePresets = SCORE_PRESETS;
  protected readonly datePresets = [
    { days: 0, label: 'Hoje' },
    { days: 6, label: 'Últimos 7 dias' },
    { days: 29, label: 'Últimos 30 dias' },
  ];

  protected readonly rows = signal<JobRow[]>([]);
  protected readonly loading = signal(true);
  protected readonly saveStates = signal<Record<string, SaveState>>({});
  protected readonly saveErrors = signal<Record<string, string>>({});

  private readonly params = toSignal(this.route.queryParams.pipe(map((p) => p as Record<string, string>)), {
    initialValue: {} as Record<string, string>,
  });
  protected readonly filters = computed(() => filtersFromParams(this.params()));
  protected readonly sort = computed(() => {
    const [key, dir] = (this.params()['ordem'] ?? 'date:desc').split(':');
    return {
      key: (SORT_KEYS.includes(key as SortKey) ? key : 'date') as SortKey,
      dir: (dir === 'asc' ? 'asc' : 'desc') as SortDir,
    };
  });
  protected readonly selectedId = computed(() => this.params()['vaga'] ?? null);

  protected readonly filtered = computed(() => applyFilters(this.rows(), this.filters()));
  protected readonly visible = computed(() =>
    this.sort().key === 'date' && this.sort().dir === 'desc'
      ? this.filtered() // a API já manda por data e nota
      : sortRows(this.filtered(), this.sort().key, this.sort().dir),
  );

  /** O funil ignora a etapa escolhida (ele é o seletor de etapa), mas respeita os outros filtros. */
  protected readonly funnel = computed(() => {
    const f = this.filters();
    const base = applyFilters(this.rows(), { ...f, stages: [], reasons: [], unlabeled: false });
    const counts = countsBy(base);
    const older = base.filter((r) => r.stage === 'history' || r.stage === 'benchmark').length;
    const unlabeled = applyFilters(this.rows(), { ...f, unlabeled: false }).filter((r) => r.my_score === null).length;
    return { ...counts, older, unlabeled };
  });

  protected readonly reasonSummary = computed(() => {
    const byReason = this.funnel().byReason;
    return this.reasonKeys
      .filter((r) => byReason[r])
      .map((r) => `${REASON_LABELS[r].toLowerCase()} ${byReason[r]}`)
      .join(' · ');
  });

  protected readonly optionCounts = computed(() => {
    const out = {
      stages: {} as Record<string, number>,
      reasons: {} as Record<string, number>,
      sources: {} as Record<string, number>,
      contracts: {} as Record<string, number>,
    };
    for (const r of this.rows()) {
      out.stages[r.stage] = (out.stages[r.stage] ?? 0) + 1;
      if (r.filter_reason) out.reasons[r.filter_reason] = (out.reasons[r.filter_reason] ?? 0) + 1;
      out.sources[r.source] = (out.sources[r.source] ?? 0) + 1;
      out.contracts[r.pj_status] = (out.contracts[r.pj_status] ?? 0) + 1;
    }
    return out;
  });

  protected readonly chips = computed<Chip[]>(() => {
    const f = this.filters();
    const out: Chip[] = [];
    for (const s of f.stages) out.push({ text: STAGE_LABELS[s], next: { ...f, stages: f.stages.filter((v) => v !== s) } });
    for (const r of f.reasons) {
      out.push({ text: `Motivo: ${REASON_LABELS[r]}`, next: { ...f, reasons: f.reasons.filter((v) => v !== r) } });
    }
    for (const s of f.sources) out.push({ text: this.sourceName(s), next: { ...f, sources: f.sources.filter((v) => v !== s) } });
    for (const k of f.contracts) {
      out.push({ text: CONTRACT_LABELS[k], next: { ...f, contracts: f.contracts.filter((v) => v !== k) } });
    }
    if (f.minScore !== null || f.maxScore !== null) {
      const text =
        f.maxScore === null ? `Nota ≥ ${f.minScore}` : f.minScore === null ? `Nota ≤ ${f.maxScore}` : `Nota ${f.minScore}–${f.maxScore}`;
      out.push({ text, next: { ...f, minScore: null, maxScore: null } });
    }
    if (f.from || f.to) {
      const text = !f.to ? `Desde ${formatDate(f.from)}` : !f.from ? `Até ${formatDate(f.to)}` : `${formatDate(f.from)} – ${formatDate(f.to)}`;
      out.push({ text, next: { ...f, from: '', to: '' } });
    }
    if (f.unlabeled) out.push({ text: 'Sem nota sua', next: { ...f, unlabeled: false } });
    return out;
  });

  protected readonly sources = computed(() => [...new Set(this.rows().map((r) => r.source))].sort());
  protected readonly selected = computed(() => this.rows().find((r) => r.id === this.selectedId()) ?? null);

  constructor() {
    this.api.jobs().subscribe({
      next: (rows) => {
        this.rows.set(rows);
        this.loading.set(false);
      },
      error: () => this.loading.set(false),
    });
  }

  protected sourceName(source: string): string {
    return sourceLabel({ source, publisher: null });
  }

  protected since(days: number): string {
    return isoDaysAgo(days);
  }

  protected numberOrNull(value: string): number | null {
    return value === '' ? null : Number(value);
  }

  protected stageIs(key: keyof typeof FUNNEL_STAGES): boolean {
    return sameSet(this.filters().stages, FUNNEL_STAGES[key]) && (key === 'all' || !this.filters().reasons.length);
  }

  protected setStages(key: keyof typeof FUNNEL_STAGES): void {
    this.patch({ stages: [...FUNNEL_STAGES[key]], reasons: [] });
  }

  protected patch(change: Partial<JobFilters>): void {
    this.writeFilters({ ...this.filters(), ...change });
  }

  protected toggle<K extends 'stages' | 'reasons' | 'sources' | 'contracts'>(key: K, value: JobFilters[K][number]): void {
    const current = this.filters()[key] as string[];
    const next = current.includes(value) ? current.filter((v) => v !== value) : [...current, value];
    this.patch({ [key]: next } as Partial<JobFilters>);
  }

  protected clear(): void {
    this.writeFilters(EMPTY_FILTERS);
  }

  protected writeFilters(f: JobFilters): void {
    const keep: Params = {};
    for (const k of ['ordem', 'vaga']) {
      if (this.params()[k]) keep[k] = this.params()[k];
    }
    void this.router.navigate([], { queryParams: { ...filtersToParams(f), ...keep }, replaceUrl: true });
  }

  protected setParams(change: Params): void {
    void this.router.navigate([], { queryParams: change, queryParamsHandling: 'merge', replaceUrl: true });
  }

  protected saveFromTable(change: LabelChange): void {
    this.saveLabel(change.row, change.score, change.row.my_note);
  }

  protected saveFromDetail(row: JobRow, change: DetailSave): void {
    this.saveLabel(row, change.score, change.note);
  }

  private saveLabel(row: JobRow, score: number | null, note: string): void {
    this.setState(row.id, 'saving');
    this.api.saveLabel(row.id, score, note).subscribe({
      next: (result) => {
        this.rows.update((rows) =>
          rows.map((r) => (r.id === row.id ? { ...r, my_score: result.my_score, my_note: result.my_note } : r)),
        );
        this.setState(row.id, 'saved');
      },
      error: (err: Error) => {
        this.saveErrors.update((e) => ({ ...e, [row.id]: err.message }));
        this.setState(row.id, 'error');
      },
    });
  }

  private setState(id: string, state: SaveState): void {
    this.saveStates.update((s) => ({ ...s, [id]: state }));
  }
}
