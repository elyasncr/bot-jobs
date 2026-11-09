import { ChangeDetectionStrategy, Component, ElementRef, inject, input, signal } from '@angular/core';

/**
 * Botão de filtro com um painel suspenso (o conteúdo vem projetado).
 * Desktop: painel abaixo do botão. Celular: folha que sobe da parte de baixo da tela.
 * Fecha com clique fora, Esc ou "Pronto".
 */
@Component({
  selector: 'app-filter-menu',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    '(document:click)': 'onDocumentClick($event)',
    '(document:keydown.escape)': 'open.set(false)',
  },
  template: `
    <button type="button" class="trigger" [class.active]="count() > 0" [attr.aria-expanded]="open()"
            (click)="open.set(!open())">
      {{ label() }}
      @if (count() > 0) {
        <span class="count">{{ count() }}</span>
      }
      <svg class="chev" viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
        <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
    </button>
    <div class="backdrop" [hidden]="!open()" (click)="open.set(false)"></div>
    <div class="panel" role="dialog" [attr.aria-label]="label()" [hidden]="!open()" [class.end]="align() === 'end'">
      <div class="sheet-head">
        <strong>{{ label() }}</strong>
        <button type="button" class="done" (click)="open.set(false)">Pronto</button>
      </div>
      <ng-content />
    </div>
  `,
  styles: `
    :host { position: relative; display: inline-block; }
    .trigger {
      all: unset; box-sizing: border-box; cursor: pointer; display: inline-flex; align-items: center; gap: 6px; white-space: nowrap;
      height: 36px; padding: 0 12px; border: 1px solid var(--border-strong); border-radius: 8px; background: var(--surface);
      font-size: 0.88rem; font-weight: 500; color: var(--text);
    }
    .trigger:hover { background: var(--hover); }
    .trigger:focus-visible { outline: 2px solid var(--accent); outline-offset: 1px; }
    .trigger[aria-expanded='true'] { border-color: var(--accent); }
    .trigger.active { border-color: var(--accent); background: var(--accent-bg); color: var(--accent); }
    .count { display: inline-grid; place-items: center; min-width: 18px; height: 18px; padding: 0 5px; border-radius: 999px;
             background: var(--accent); color: var(--on-accent); font-size: 0.72rem; font-weight: 700; }
    .chev { color: var(--muted); }
    .active .chev { color: var(--accent); }
    .panel {
      position: absolute; top: calc(100% + 6px); left: 0; z-index: 30; min-width: 240px; max-width: 320px; padding: 8px;
      background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow-pop);
    }
    .panel.end { left: auto; right: 0; }
    .panel[hidden], .backdrop[hidden] { display: none; }
    .backdrop { display: none; }
    .sheet-head { display: none; }

    @media (max-width: 720px) {
      .backdrop { display: block; position: fixed; inset: 0; z-index: 29; background: var(--backdrop); }
      .panel, .panel.end {
        position: fixed; top: auto; left: 0; right: 0; bottom: 0; max-width: none; max-height: 75vh; overflow-y: auto;
        border-radius: 16px 16px 0 0; padding: 6px 12px calc(16px + env(safe-area-inset-bottom));
      }
      .sheet-head { display: flex; align-items: center; justify-content: space-between; padding: 10px 4px 8px; }
      .done { all: unset; cursor: pointer; color: var(--accent); font-weight: 600; padding: 4px 6px; }
    }
  `,
})
export class FilterMenu {
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);

  readonly label = input.required<string>();
  readonly count = input(0);
  readonly align = input<'start' | 'end'>('start');

  protected readonly open = signal(false);

  protected onDocumentClick(event: MouseEvent): void {
    if (this.open() && !this.host.nativeElement.contains(event.target as Node)) this.open.set(false);
  }
}
