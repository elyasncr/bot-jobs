import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import {
  CONTRACT_LABELS,
  JobRow,
  MODALITY_LABELS,
  REASON_LABELS,
  STAGE_LABELS,
  formatDate,
  shortLocation,
  sourceLabel,
} from '../core/models';
import { LabelInput, SaveState } from '../shared/label-input';
import { ScoreBadge } from '../shared/score-badge';
import { SortDir, SortKey } from './job-filters';

export interface LabelChange {
  row: JobRow;
  score: number | null;
}

@Component({
  selector: 'app-jobs-table',
  imports: [ScoreBadge, LabelInput],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <div class="frame">
      <table>
        <thead>
          <tr>
            <th>Vaga</th>
            <th>Etapa</th>
            <th>Contrato</th>
            <th class="num" [attr.aria-sort]="ariaSort('total')">
              <button type="button" (click)="toggle('total')">Nota <span class="arrow">{{ arrow('total') }}</span></button>
            </th>
            <th class="num" [attr.aria-sort]="ariaSort('cosine')">
              <button type="button" (click)="toggle('cosine')" title="Similaridade currículo × vaga (embeddings)">
                Cos <span class="arrow">{{ arrow('cosine') }}</span>
              </button>
            </th>
            <th class="num" [attr.aria-sort]="ariaSort('mine')">
              <button type="button" (click)="toggle('mine')">Sua nota <span class="arrow">{{ arrow('mine') }}</span></button>
            </th>
            <th class="num" [attr.aria-sort]="ariaSort('date')">
              <button type="button" (click)="toggle('date')">Capturada <span class="arrow">{{ arrow('date') }}</span></button>
            </th>
          </tr>
        </thead>
        <tbody>
          @for (row of rows(); track row.id) {
            <tr [class.selected]="row.id === selectedId()" (click)="select.emit(row.id)">
              <td class="job">
                @if (row.url) {
                  <a class="title" [href]="row.url" target="_blank" rel="noopener" (click)="$event.stopPropagation()">{{ row.title }}</a>
                } @else {
                  <span class="title">{{ row.title }}</span>
                }
                <div class="sub">
                  <span class="company">{{ row.company }}</span>
                  @if (location(row); as loc) {
                    <span class="tag loc" [title]="row.location">{{ loc }}</span>
                  }
                  @if (row.modality !== 'unknown') {
                    <span class="tag">{{ modality[row.modality] }}</span>
                  }
                  @if (row.source !== 'history') {
                    <span class="tag">{{ source(row) }}</span>
                  }
                  @if (row.low_fidelity) {
                    <span class="tag warn" title="Sem descrição: avaliada só pelo título">baixa fidelidade</span>
                  }
                </div>
                <div class="m-meta">
                  <i class="stage-dot" [attr.data-stage]="row.stage"></i>{{ stage[row.stage] }}
                  @if (row.pj_status !== 'uncertain') {
                    · <span class="contract" [attr.data-pj]="row.pj_status">{{ contract[row.pj_status] }}</span>
                  }
                  · {{ date(row.run_date) }}
                  @if (row.embedding_score !== null) {
                    · cos {{ row.embedding_score.toFixed(2) }}
                  }
                </div>
              </td>
              <td class="stage-cell">
                <span class="stage"><i class="stage-dot" [attr.data-stage]="row.stage"></i>{{ stage[row.stage] }}</span>
                @if (row.filter_reason) {
                  <span class="reason">{{ reason[row.filter_reason] }}</span>
                }
              </td>
              <td class="contract-cell"><span class="contract" [attr.data-pj]="row.pj_status">{{ contract[row.pj_status] }}</span></td>
              <td class="num total"><app-score-badge [total]="row.total" [estimate]="row.is_estimate" /></td>
              <td class="num cos">{{ row.embedding_score === null ? '—' : row.embedding_score.toFixed(3) }}</td>
              <td class="num mine">
                <app-label-input
                  [value]="row.my_score"
                  [state]="saveStates()[row.id] ?? 'idle'"
                  [error]="saveErrors()[row.id] ?? null"
                  (save)="labelChange.emit({ row, score: $event })"
                />
              </td>
              <td class="num date">{{ date(row.run_date) }}</td>
            </tr>
          } @empty {
            <tr class="empty-row">
              <td colspan="7" class="empty">
                <strong>Nenhuma vaga com esses filtros.</strong>
                <span>Tente remover algum filtro ativo.</span>
              </td>
            </tr>
          }
        </tbody>
      </table>
    </div>
  `,
  styles: `
    :host { display: block; min-width: 0; }
    .frame { overflow-x: auto; border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); box-shadow: var(--shadow-sm); }
    table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
    th {
      background: var(--surface); text-align: left; white-space: nowrap; padding: 10px 14px;
      font-size: 0.72rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: var(--faint);
      border-bottom: 1px solid var(--border);
    }
    th button { all: unset; cursor: pointer; display: inline-flex; align-items: center; gap: 2px; }
    th button:hover { color: var(--text); }
    th button:focus-visible { outline: 2px solid var(--accent); }
    th[aria-sort='ascending'], th[aria-sort='descending'] { color: var(--accent); }
    .arrow { display: inline-block; width: 0.8em; }
    td { padding: 12px 14px; border-bottom: 1px solid var(--border); vertical-align: middle; }
    tbody tr:last-child td { border-bottom: 0; }
    tbody tr { cursor: pointer; transition: background-color 0.1s; }
    tbody tr:hover { background: var(--hover); }
    tbody tr.selected { background: var(--selected); box-shadow: inset 3px 0 0 var(--accent); }
    .num { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }

    .job { min-width: 300px; }
    .title { color: var(--text); font-weight: 600; text-decoration: none; line-height: 1.35; }
    a.title:hover { color: var(--accent); text-decoration: underline; text-underline-offset: 2px; }
    .sub { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 6px; margin-top: 4px; }
    .company { color: var(--muted); font-size: 0.85rem; margin-right: 2px; }
    .loc { max-width: 220px; overflow: hidden; text-overflow: ellipsis; display: inline-block; }
    .m-meta { display: none; }

    .stage { display: inline-flex; align-items: center; gap: 7px; white-space: nowrap; }
    .reason { display: block; margin: 2px 0 0 15px; font-size: 0.78rem; color: var(--faint); }
    .cos, .date { color: var(--muted); font-size: 0.85rem; }

    .empty { text-align: center; padding: 48px 16px; color: var(--muted); }
    .empty strong { display: block; color: var(--text); margin-bottom: 2px; }
    .empty-row { cursor: default; }
    .empty-row:hover { background: none; }

    /* Celular: cada vaga vira um cartão. */
    @media (max-width: 720px) {
      .frame { overflow: visible; border: 0; background: none; box-shadow: none; }
      table, tbody { display: block; }
      thead { display: none; }
      tbody tr {
        display: grid; grid-template-columns: minmax(0, 1fr) auto; grid-template-areas: 'job total' 'job mine';
        gap: 8px 12px; margin-bottom: 10px; padding: 14px;
        border: 1px solid var(--border); border-radius: var(--radius); background: var(--surface); box-shadow: var(--shadow-sm);
      }
      tbody tr.selected { box-shadow: inset 3px 0 0 var(--accent), var(--shadow-sm); }
      td { padding: 0; border: 0; }
      .job { grid-area: job; min-width: 0; }
      .title { pointer-events: none; font-size: 0.95rem; } /* no celular, tocar abre o detalhe (que tem o link) */
      .loc { max-width: 160px; }
      .m-meta { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; margin-top: 8px; font-size: 0.78rem; color: var(--muted); }
      .m-meta .stage-dot { margin-right: 2px; }
      .total { grid-area: total; text-align: right; }
      .mine { grid-area: mine; align-self: end; text-align: right; }
      .stage-cell, .contract-cell, .cos, .date { display: none; }
      .empty-row { display: block; padding: 0; }
      .empty { display: block; }
    }
  `,
})
export class JobsTable {
  readonly rows = input.required<JobRow[]>();
  readonly sortKey = input.required<SortKey>();
  readonly sortDir = input.required<SortDir>();
  readonly selectedId = input<string | null>(null);
  readonly saveStates = input<Record<string, SaveState>>({});
  readonly saveErrors = input<Record<string, string>>({});

  readonly sortChange = output<{ key: SortKey; dir: SortDir }>();
  readonly select = output<string>();
  readonly labelChange = output<LabelChange>();

  protected readonly stage = STAGE_LABELS;
  protected readonly reason = REASON_LABELS;
  protected readonly contract = CONTRACT_LABELS;
  protected readonly modality = MODALITY_LABELS;
  protected readonly source = sourceLabel;
  protected readonly date = (iso: string) => formatDate(iso);

  protected location(row: JobRow): string | null {
    return shortLocation(row.location);
  }

  protected toggle(key: SortKey): void {
    const dir: SortDir = this.sortKey() === key && this.sortDir() === 'desc' ? 'asc' : 'desc';
    this.sortChange.emit({ key, dir });
  }

  protected arrow(key: SortKey): string {
    return this.sortKey() !== key ? '' : this.sortDir() === 'desc' ? '↓' : '↑';
  }

  protected ariaSort(key: SortKey): string | null {
    return this.sortKey() !== key ? null : this.sortDir() === 'desc' ? 'descending' : 'ascending';
  }
}
