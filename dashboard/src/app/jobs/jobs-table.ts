import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';

import { CONTRACT_LABELS, JobRow, MODALITY_LABELS, REASON_LABELS, STAGE_LABELS, sourceLabel } from '../core/models';
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
    <div class="scroll">
      <table>
        <thead>
          <tr>
            <th>
              <button type="button" (click)="toggle('date')">Data {{ arrow('date') }}</button>
            </th>
            <th>Vaga</th>
            <th>Local</th>
            <th>Fonte</th>
            <th>Contrato</th>
            <th class="num">
              <button type="button" (click)="toggle('total')">Nota {{ arrow('total') }}</button>
            </th>
            <th class="num">
              <button type="button" (click)="toggle('cosine')" title="Similaridade CV × vaga (embeddings)">Cos {{ arrow('cosine') }}</button>
            </th>
            <th class="num">
              <button type="button" (click)="toggle('mine')">Minha {{ arrow('mine') }}</button>
            </th>
            <th>Etapa</th>
          </tr>
        </thead>
        <tbody>
          @for (row of rows(); track row.id) {
            <tr [class.selected]="row.id === selectedId()" (click)="select.emit(row.id)">
              <td class="date">{{ row.run_date }}</td>
              <td class="job">
                @if (row.url) {
                  <a [href]="row.url" target="_blank" rel="noopener" (click)="$event.stopPropagation()">{{ row.title }}</a>
                } @else {
                  {{ row.title }}
                }
                <span class="company">{{ row.company }}</span>
                @if (row.low_fidelity) {
                  <span class="tag" title="Sem descrição: avaliada só pelo título">baixa fidelidade</span>
                }
              </td>
              <td class="loc">
                {{ row.location || '—' }}
                <span class="muted">{{ modality[row.modality] }}</span>
              </td>
              <td class="muted">{{ source(row) }}</td>
              <td><span class="contract" [attr.data-pj]="row.pj_status">{{ contract[row.pj_status] }}</span></td>
              <td class="num"><app-score-badge [total]="row.total" [estimate]="row.is_estimate" /></td>
              <td class="num muted">{{ row.embedding_score === null ? '—' : row.embedding_score.toFixed(3) }}</td>
              <td class="num">
                <app-label-input
                  [value]="row.my_score"
                  [state]="saveStates()[row.id] ?? 'idle'"
                  [error]="saveErrors()[row.id] ?? null"
                  (save)="labelChange.emit({ row, score: $event })"
                />
              </td>
              <td>
                <span class="stage" [attr.data-stage]="row.stage">{{ stage[row.stage] }}</span>
                @if (row.filter_reason) {
                  <span class="muted">· {{ reason[row.filter_reason] }}</span>
                }
              </td>
            </tr>
          } @empty {
            <tr>
              <td colspan="9" class="empty">Nenhuma vaga com esses filtros.</td>
            </tr>
          }
        </tbody>
      </table>
    </div>
  `,
  styles: `
    .scroll { overflow-x: auto; border: 1px solid var(--border); border-radius: 10px; background: var(--surface); }
    table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
    th { position: sticky; top: 0; background: var(--surface-2); text-align: left; font-weight: 600; white-space: nowrap; }
    th, td { padding: 8px 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
    th button { all: unset; cursor: pointer; }
    th button:focus-visible { outline: 2px solid var(--accent); }
    tbody tr { cursor: pointer; }
    tbody tr:hover { background: var(--hover); }
    tr.selected { background: var(--selected); }
    .num { text-align: right; white-space: nowrap; }
    .date { white-space: nowrap; font-variant-numeric: tabular-nums; }
    .job { min-width: 260px; }
    .job a { color: var(--text); font-weight: 600; text-decoration: none; }
    .job a:hover { text-decoration: underline; }
    .company { display: block; color: var(--muted); }
    .loc { min-width: 140px; }
    .loc .muted { display: block; }
    .muted { color: var(--muted); }
    .tag { display: inline-block; margin-top: 2px; font-size: 0.75rem; padding: 1px 6px; border-radius: 999px; background: var(--surface-2); color: var(--muted); }
    .contract { white-space: nowrap; }
    .contract[data-pj='pj'], .contract[data-pj='both'] { color: var(--high); font-weight: 600; }
    .contract[data-pj='clt'] { color: var(--danger); }
    .stage { white-space: nowrap; font-weight: 500; }
    .stage[data-stage='emailed'] { color: var(--high); }
    .stage[data-stage='filtered'] { color: var(--muted); }
    .empty { text-align: center; color: var(--muted); padding: 32px; }
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

  protected toggle(key: SortKey): void {
    const dir: SortDir = this.sortKey() === key && this.sortDir() === 'desc' ? 'asc' : 'desc';
    this.sortChange.emit({ key, dir });
  }

  protected arrow(key: SortKey): string {
    return this.sortKey() !== key ? '' : this.sortDir() === 'desc' ? '↓' : '↑';
  }
}
