import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { ApiService } from './core/api.service';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="top">
      <span class="brand">vagas-pj-bot</span>
      <nav>
        <a routerLink="/vagas" routerLinkActive="active">Vagas</a>
        <a routerLink="/benchmark" routerLinkActive="active">Benchmark</a>
      </nav>
    </header>
    @if (api.lastError(); as error) {
      <div class="alert" role="alert">
        <span>{{ error }}</span>
        <button type="button" (click)="api.lastError.set(null)" aria-label="Fechar aviso">✕</button>
      </div>
    }
    <main>
      <router-outlet />
    </main>
  `,
  styles: `
    .top { display: flex; align-items: center; gap: 24px; padding: 12px 24px; border-bottom: 1px solid var(--border);
           background: var(--surface); position: sticky; top: 0; z-index: 10; }
    .brand { font-weight: 700; }
    nav { display: flex; gap: 4px; }
    nav a { padding: 6px 12px; border-radius: 8px; color: var(--muted); text-decoration: none; font-weight: 500; }
    nav a:hover { background: var(--hover); color: var(--text); }
    nav a.active { background: var(--accent-bg); color: var(--accent); }
    .alert { display: flex; justify-content: space-between; gap: 12px; margin: 12px 24px 0; padding: 10px 14px;
             border-radius: 8px; background: var(--danger-bg); color: var(--danger); border: 1px solid var(--danger); }
    .alert button { all: unset; cursor: pointer; }
    main { padding: 18px 24px 48px; max-width: 1500px; margin: 0 auto; }
    @media (max-width: 720px) {
      .top { padding: 10px 16px; gap: 12px; }
      main { padding: 14px 16px 40px; }
      .alert { margin: 10px 16px 0; }
    }
  `,
})
export class App {
  protected readonly api = inject(ApiService);
}
