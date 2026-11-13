import { ChangeDetectionStrategy, Component, DestroyRef, ElementRef, computed, inject, output, signal, viewChild } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { EMPTY, Subscription, catchError, exhaustMap, takeWhile, timer } from 'rxjs';

import { ApiService } from '../core/api.service';
import { BenchmarkModelOption, BenchmarkStatus } from '../core/models';
import { defaultSelection, jobsSummary, progressPercent, progressText } from './run-progress';

const POLL_MS = 3000;

/**
 * Botão "Rodar benchmark": painel com os modelos do Ollama, faixa de progresso enquanto roda
 * e `finished` com o arquivo do resultado novo. `display: contents`: o botão e a faixa viram
 * itens do cabeçalho da página (a faixa ocupa uma linha inteira embaixo).
 */
@Component({
  selector: 'app-run-benchmark',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: {
    '(document:click)': 'onDocumentClick($event)',
    '(document:keydown.escape)': 'close()',
  },
  template: `
    <div class="wrap">
      <button #trigger type="button" class="trigger" [disabled]="running()" [attr.aria-expanded]="open()" (click)="toggle()">
        {{ running() ? 'Rodando…' : 'Rodar benchmark' }}
      </button>
      @if (open()) {
        <div class="backdrop" (click)="open.set(false)"></div>
        <div class="panel" role="dialog" aria-label="Rodar benchmark">
          <strong class="title">Rodar benchmark</strong>
          @if (loadingOptions()) {
            <p class="muted">Consultando o Ollama…</p>
          }
          @if (panelError(); as e) {
            <p class="error">{{ e }}</p>
          }
          @if (!loadingOptions() && !panelError() && !options().length) {
            <p class="muted">Nenhum modelo de LLM instalado no Ollama.</p>
          }
          @if (options().length) {
            <fieldset>
              <legend>Modelos</legend>
              @for (o of options(); track o.name; let i = $index) {
                <label class="opt">
                  <input type="checkbox" [attr.aria-describedby]="o.warning ? 'warn-' + i : null" [checked]="selected().includes(o.name)"
                         (change)="toggleModel(o.name, $any($event.target).checked)" />
                  <span>{{ o.name }}</span>
                </label>
                @if (o.warning) {
                  <span class="warn" [id]="'warn-' + i">{{ o.warning }}</span>
                }
              }
            </fieldset>
            <p class="muted">{{ jobsText() }}</p>
          }
          <div class="actions">
            <button type="button" class="ghost" (click)="close()">Cancelar</button>
            <button type="button" [disabled]="!selected().length || starting()" (click)="start()">Rodar</button>
          </div>
        </div>
      }
    </div>
    @if (status(); as s) {
      @if (s.state === 'running') {
        <div class="strip">
          <span>{{ progressText(s) }}</span>
          <div class="bar" role="progressbar" aria-valuemin="0" aria-valuemax="100"
               [attr.aria-valuenow]="progressPercent(s)" [attr.aria-label]="progressText(s)"><div class="fill" [style.width.%]="progressPercent(s)"></div></div>
        </div>
      } @else if (s.state === 'error') {
        <div class="strip error" role="alert">
          <span>O benchmark falhou: {{ s.error }}</span>
          <button type="button" class="close" (click)="status.set(null)" aria-label="Fechar aviso">✕</button>
        </div>
      }
    }
  `,
  styles: `
    :host { display: contents; }
    .wrap { position: relative; margin-left: auto; }
    .trigger {
      all: unset; box-sizing: border-box; cursor: pointer; display: inline-flex; align-items: center; height: 36px; padding: 0 14px;
      border-radius: 8px; background: var(--accent); color: var(--on-accent); font-size: 0.88rem; font-weight: 600; white-space: nowrap;
    }
    .trigger:hover:not(:disabled) { background: var(--accent-strong); }
    .trigger:disabled { opacity: 0.6; cursor: default; }
    .trigger:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
    .panel {
      position: absolute; top: calc(100% + 6px); right: 0; z-index: 30; width: 300px; padding: 14px; display: grid; gap: 10px;
      background: var(--surface); border: 1px solid var(--border); border-radius: var(--radius); box-shadow: var(--shadow-pop);
    }
    .title { font-size: 0.95rem; }
    fieldset { border: 0; margin: 0; padding: 0; display: grid; gap: 2px; }
    legend { padding: 0; margin-bottom: 4px; font-size: 0.72rem; font-weight: 600; color: var(--faint);
             text-transform: uppercase; letter-spacing: 0.04em; }
    .opt { display: flex; align-items: center; gap: 8px; padding: 4px 2px; cursor: pointer; }
    .warn { margin: -2px 0 4px 26px; font-size: 0.78rem; color: var(--maybe); }
    .muted { margin: 0; color: var(--muted); font-size: 0.85rem; }
    .error { margin: 0; color: var(--danger); font-size: 0.85rem; }
    .actions { display: flex; justify-content: flex-end; gap: 8px; }
    .ghost { all: unset; cursor: pointer; padding: 7px 12px; border-radius: 8px; color: var(--muted); font-weight: 500; }
    .ghost:hover { background: var(--hover); color: var(--text); }
    .backdrop { display: none; }
    .strip {
      flex: 1 0 100%; order: 10; display: grid; grid-template-columns: auto 1fr; align-items: center; gap: 8px 16px;
      padding: 10px 14px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); font-size: 0.88rem;
    }
    .bar { height: 6px; border-radius: 999px; background: var(--surface-2); overflow: hidden; }
    .fill { height: 100%; background: var(--accent); transition: width 0.4s ease; }
    .strip.error { grid-template-columns: 1fr auto; background: var(--danger-bg); color: var(--danger); border-color: var(--danger); }
    .close { all: unset; cursor: pointer; }
    .ghost:focus-visible, .close:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
    @media (max-width: 720px) {
      .backdrop { display: block; position: fixed; inset: 0; z-index: 29; background: var(--backdrop); }
      .panel { position: fixed; top: auto; left: 0; right: 0; bottom: 0; width: auto; border-radius: 16px 16px 0 0;
               padding: 16px 16px calc(16px + env(safe-area-inset-bottom)); max-height: 85vh; overflow-y: auto; }
      .strip { grid-template-columns: 1fr; }
    }
  `,
})
export class RunBenchmark {
  private readonly api = inject(ApiService);
  private readonly destroyRef = inject(DestroyRef);
  private readonly host = inject<ElementRef<HTMLElement>>(ElementRef);
  private readonly trigger = viewChild<ElementRef<HTMLButtonElement>>('trigger');
  private polling?: Subscription;

  /** Nome do arquivo do resultado novo (data/eval/results/eval_*.json). */
  readonly finished = output<string>();

  protected readonly open = signal(false);
  protected readonly options = signal<BenchmarkModelOption[]>([]);
  protected readonly selected = signal<string[]>([]);
  protected readonly counts = signal({ pending: 0, total: 0 });
  protected readonly loadingOptions = signal(false);
  protected readonly starting = signal(false);
  protected readonly panelError = signal<string | null>(null);
  protected readonly status = signal<BenchmarkStatus | null>(null);
  protected readonly running = computed(() => this.status()?.state === 'running');
  protected readonly jobsText = computed(() => jobsSummary(this.counts().pending, this.counts().total));
  protected readonly progressText = progressText;
  protected readonly progressPercent = progressPercent;

  constructor() {
    // Rodada iniciada em outra aba ou no celular: retoma o acompanhamento.
    this.api.benchmarkStatus().subscribe({
      next: (s) => {
        if (s.state === 'running') {
          this.status.set(s);
          this.poll();
        }
      },
      error: () => undefined,
    });
  }

  protected toggle(): void {
    if (this.open()) {
      this.open.set(false);
      return;
    }
    this.open.set(true);
    this.options.set([]);
    this.panelError.set(null);
    this.loadingOptions.set(true);
    this.api.benchmarkModels().subscribe({
      next: (r) => {
        this.options.set(r.models);
        this.selected.set(defaultSelection(r.models));
        this.counts.set({ pending: r.pending_jobs, total: r.total_jobs });
        this.loadingOptions.set(false);
      },
      error: (e: Error) => {
        this.panelError.set(e.message);
        this.loadingOptions.set(false);
      },
    });
  }

  protected close(): void {
    if (!this.open()) return;
    this.open.set(false);
    this.trigger()?.nativeElement.focus();
  }

  protected toggleModel(name: string, checked: boolean): void {
    this.selected.update((list) => (checked ? [...list, name] : list.filter((n) => n !== name)));
  }

  protected start(): void {
    const chosen = this.options()
      .map((o) => o.name)
      .filter((n) => this.selected().includes(n)); // na ordem da lista
    this.starting.set(true);
    this.panelError.set(null);
    this.api.startBenchmark(chosen).subscribe({
      next: (s) => {
        this.starting.set(false);
        this.open.set(false);
        this.status.set(s);
        this.poll();
      },
      error: (e: Error) => {
        this.starting.set(false);
        this.panelError.set(e.message);
      },
    });
  }

  protected onDocumentClick(event: MouseEvent): void {
    if (this.open() && !this.host.nativeElement.contains(event.target as Node)) this.open.set(false);
  }

  private poll(): void {
    this.polling?.unsubscribe();
    this.polling = timer(POLL_MS, POLL_MS)
      .pipe(
        exhaustMap(() => this.api.benchmarkStatus().pipe(catchError(() => EMPTY))), // falha pontual: tenta no próximo ciclo
        takeWhile((s) => s.state === 'running', true),
        takeUntilDestroyed(this.destroyRef),
      )
      .subscribe((s) => {
        if (this.status()?.state === 'running' && s.state === 'idle') {
          this.status.set({ ...s, state: 'error', error: 'A rodada foi interrompida (o dashboard foi reiniciado).' });
          return;
        }
        this.status.set(s);
        if (s.state === 'done' && s.result_file) this.finished.emit(s.result_file);
      });
  }
}
