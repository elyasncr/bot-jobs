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
  sourceLabel,
} from '../core/models';
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

@Component({
  selector: 'app-jobs-page',
  imports: [JobsTable, JobDetail],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <section class="counters" aria-label="Resumo">
      <div><strong>{{ counts().total }}</strong><span>vagas</span></div>
      <div><strong>{{ counts().emailed }}</strong><span>enviadas por email</span></div>
      <div><strong>{{ counts().evaluated }}</strong><span>passaram dos filtros</span></div>
      <div>
        <strong>{{ counts().filtered }}</strong><span>filtradas</span>
        @if (counts().filtered) {
          <small>
            @for (r of reasonKeys; track r) {
              @if (counts().byReason[r]) {
                {{ reasonLabels[r] }} {{ counts().byReason[r] }}&nbsp;
              }
            }
          </small>
        }
      </div>
      <div><strong>{{ counts().labeled }}</strong><span>com nota minha</span></div>
    </section>

    <button type="button" class="toggle-filters" (click)="showFilters.set(!showFilters())" [attr.aria-expanded]="showFilters()">
      {{ showFilters() ? 'Esconder filtros' : 'Filtros' }}@if (activeFilters()) { ({{ activeFilters() }} ativos)}
    </button>
    <form class="filters" [class.collapsed]="!showFilters()" (submit)="$event.preventDefault()">
      <input class="search" type="search" placeholder="Buscar título ou empresa" [value]="filters().q"
             (input)="patch({ q: $any($event.target).value })" aria-label="Buscar" />

      <fieldset>
        <legend>Etapa</legend>
        @for (s of stageKeys; track s) {
          <label class="chip" [class.on]="filters().stages.includes(s)">
            <input type="checkbox" [checked]="filters().stages.includes(s)" (change)="toggle('stages', s)" />{{ stageLabels[s] }}
          </label>
        }
      </fieldset>

      <fieldset>
        <legend>Motivo do filtro</legend>
        @for (r of reasonKeys; track r) {
          <label class="chip" [class.on]="filters().reasons.includes(r)">
            <input type="checkbox" [checked]="filters().reasons.includes(r)" (change)="toggle('reasons', r)" />{{ reasonLabels[r] }}
          </label>
        }
      </fieldset>

      <fieldset>
        <legend>Fonte</legend>
        @for (s of sources(); track s) {
          <label class="chip" [class.on]="filters().sources.includes(s)">
            <input type="checkbox" [checked]="filters().sources.includes(s)" (change)="toggle('sources', s)" />{{ sourceLabel(s) }}
          </label>
        }
      </fieldset>

      <fieldset>
        <legend>Contrato</legend>
        @for (c of contractKeys; track c) {
          <label class="chip" [class.on]="filters().contracts.includes(c)">
            <input type="checkbox" [checked]="filters().contracts.includes(c)" (change)="toggle('contracts', c)" />{{ contractLabels[c] }}
          </label>
        }
      </fieldset>

      <fieldset class="inline">
        <legend>Nota do LLM</legend>
        <input type="number" min="0" max="100" placeholder="mín" [value]="filters().minScore ?? ''"
               (change)="patch({ minScore: numberOrNull($any($event.target).value) })" aria-label="Nota mínima" />
        <input type="number" min="0" max="100" placeholder="máx" [value]="filters().maxScore ?? ''"
               (change)="patch({ maxScore: numberOrNull($any($event.target).value) })" aria-label="Nota máxima" />
      </fieldset>

      <fieldset class="inline">
        <legend>Capturada</legend>
        <input type="date" [value]="filters().from" (change)="patch({ from: $any($event.target).value })" aria-label="De" />
        <input type="date" [value]="filters().to" (change)="patch({ to: $any($event.target).value })" aria-label="Até" />
      </fieldset>

      <label class="chip" [class.on]="filters().unlabeled">
        <input type="checkbox" [checked]="filters().unlabeled" (change)="patch({ unlabeled: !filters().unlabeled })" />Sem nota minha
      </label>
      <button type="button" class="link" (click)="clear()">Limpar filtros</button>
    </form>

    @if (loading()) {
      <p class="muted">Carregando vagas…</p>
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
    .counters { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 10px; margin-bottom: 14px; }
    .counters > div { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 10px 14px; }
    .counters strong { display: block; font-size: 1.5rem; font-variant-numeric: tabular-nums; }
    .counters span, .counters small { color: var(--muted); font-size: 0.85rem; }
    .counters small { display: block; }
    .filters { display: flex; flex-wrap: wrap; gap: 10px 16px; align-items: end; margin-bottom: 14px; }
    .search { flex: 1 1 260px; }
    fieldset { border: 0; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 4px; align-items: center; }
    legend { font-size: 0.75rem; color: var(--muted); margin-bottom: 3px; padding: 0; }
    .inline input { width: 6.5em; }
    .inline input[type='date'] { width: auto; }
    .chip { display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px; border: 1px solid var(--border);
            border-radius: 999px; font-size: 0.82rem; cursor: pointer; background: var(--surface); user-select: none; }
    .chip input { position: absolute; opacity: 0; pointer-events: none; }
    .chip.on { background: var(--accent-bg); border-color: var(--accent); color: var(--accent); }
    .chip:has(input:focus-visible) { outline: 2px solid var(--accent); }
    .link { all: unset; cursor: pointer; color: var(--accent); font-size: 0.85rem; }
    .muted { color: var(--muted); }
    .toggle-filters { display: none; }
    @media (max-width: 720px) {
      .counters { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
      .counters > div { padding: 8px 10px; }
      .counters strong { font-size: 1.25rem; }
      .toggle-filters { display: block; width: 100%; margin-bottom: 10px; padding: 8px; border: 1px solid var(--border);
                        border-radius: 8px; background: var(--surface); color: var(--text); cursor: pointer; }
      .filters.collapsed { display: none; }
      .search { flex-basis: 100%; }
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

  protected readonly rows = signal<JobRow[]>([]);
  protected readonly loading = signal(true);
  protected readonly showFilters = signal(false); // só tem efeito no celular (no desktop os filtros ficam sempre visíveis)
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
  protected readonly counts = computed(() => countsBy(this.filtered()));
  protected readonly activeFilters = computed(() => Object.keys(filtersToParams(this.filters())).length);
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

  protected sourceLabel(source: string): string {
    return sourceLabel({ source, publisher: null });
  }

  protected numberOrNull(value: string): number | null {
    return value === '' ? null : Number(value);
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

  private writeFilters(f: JobFilters): void {
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
