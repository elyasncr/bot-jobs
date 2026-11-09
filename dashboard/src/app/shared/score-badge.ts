import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';

export type Band = 'high' | 'good' | 'maybe' | 'low' | 'none';

/** Mesmas faixas do email: >= 80 alta, 65–79 boa, 50–64 possível. */
export function bandOf(total: number | null): Band {
  if (total === null) return 'none';
  if (total >= 80) return 'high';
  if (total >= 65) return 'good';
  if (total >= 50) return 'maybe';
  return 'low';
}

@Component({
  selector: 'app-score-badge',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span class="badge" [attr.data-band]="band()" [title]="estimate() ? 'Estimativa por embeddings (sem nota do LLM)' : ''">
      {{ total() === null ? '—' : total() + '%' }}@if (estimate() && total() !== null) {<small>est.</small>}
    </span>
  `,
  styles: `
    .badge {
      display: inline-flex; align-items: baseline; gap: 3px; min-width: 3.2em; justify-content: center;
      padding: 2px 8px; border-radius: 999px; font-weight: 600; font-variant-numeric: tabular-nums;
      background: var(--band-bg); color: var(--band-fg);
    }
    .badge[data-band='high'] { --band-bg: var(--high-bg); --band-fg: var(--high); }
    .badge[data-band='good'] { --band-bg: var(--good-bg); --band-fg: var(--good); }
    .badge[data-band='maybe'] { --band-bg: var(--maybe-bg); --band-fg: var(--maybe); }
    .badge[data-band='low'], .badge[data-band='none'] { --band-bg: var(--surface-2); --band-fg: var(--muted); }
    small { font-weight: 500; font-size: 0.75em; }
  `,
})
export class ScoreBadge {
  readonly total = input<number | null>(null);
  readonly estimate = input(false);
  protected readonly band = computed(() => bandOf(this.total()));
}
