import { ChangeDetectionStrategy, Component, computed, input, linkedSignal, output } from '@angular/core';

export type SaveState = 'idle' | 'saving' | 'saved' | 'error';

/** '' → null (apagar); inteiro 0–100 → número; qualquer outra coisa → undefined (inválido). */
export function parseScore(text: string): number | null | undefined {
  const value = text.trim();
  if (value === '') return null;
  if (!/^\d{1,3}$/.test(value)) return undefined;
  const n = Number(value);
  return n <= 100 ? n : undefined;
}

/** Campo da minha nota (0–100). Emite `save` ao sair do campo (ou Enter) só se o valor mudou. */
@Component({
  selector: 'app-label-input',
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <span class="wrap" [attr.data-state]="invalid() ? 'error' : state()" [title]="title()">
      <input
        type="text"
        inputmode="numeric"
        maxlength="3"
        placeholder="+ nota"
        aria-label="Minha nota de 0 a 100"
        [value]="draft()"
        (input)="draft.set($any($event.target).value)"
        (keydown.enter)="$any($event.target).blur()"
        (keydown.escape)="cancel($any($event.target))"
        (blur)="commit()"
        (click)="$event.stopPropagation()"
      />
      <span class="icon" aria-hidden="true">{{ icon() }}</span>
    </span>
  `,
  styles: `
    .wrap { display: inline-flex; align-items: center; gap: 4px; position: relative; }
    input {
      width: 3.4em; height: 28px; padding: 0 6px; text-align: center; font: inherit; font-size: 0.88rem; font-weight: 600;
      font-variant-numeric: tabular-nums; cursor: pointer; transition: width 0.12s, background-color 0.12s, border-color 0.12s;
      border: 1px solid transparent; border-radius: 999px; background: var(--accent-bg); color: var(--accent);
    }
    input:placeholder-shown { width: 5.2em; border: 1px dashed var(--border-strong); background: transparent; }
    input::placeholder { color: var(--muted); font-weight: 500; opacity: 1; }
    input:hover { border-color: var(--accent); }
    input:focus {
      width: 3.4em; cursor: text; outline: none; border: 1px solid var(--accent); background: var(--surface); color: var(--text);
      box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 22%, transparent);
    }
    input:focus::placeholder { color: transparent; }
    [data-state='error'] input { border: 1px solid var(--danger); color: var(--danger); background: var(--danger-bg); }
    .icon { width: 1em; font-size: 0.85em; color: var(--muted); }
    [data-state='saved'] .icon { color: var(--high); }
    [data-state='error'] .icon { color: var(--danger); }
  `,
})
export class LabelInput {
  readonly value = input<number | null>(null);
  readonly state = input<SaveState>('idle');
  readonly error = input<string | null>(null);
  readonly save = output<number | null>();

  protected readonly draft = linkedSignal(() => (this.value() === null ? '' : String(this.value())));
  protected readonly invalid = computed(() => parseScore(this.draft()) === undefined);
  protected readonly icon = computed(() => {
    if (this.invalid()) return '!';
    return { idle: '', saving: '…', saved: '✓', error: '!' }[this.state()];
  });
  protected readonly title = computed(() =>
    this.invalid() ? 'Use um inteiro de 0 a 100 (vazio apaga)' : this.state() === 'error' ? (this.error() ?? 'Erro ao salvar') : '',
  );

  commit(): void {
    const parsed = parseScore(this.draft());
    if (parsed === undefined || parsed === this.value()) return;
    this.save.emit(parsed);
  }

  cancel(el: HTMLInputElement): void {
    this.draft.set(this.value() === null ? '' : String(this.value()));
    el.blur();
  }
}
