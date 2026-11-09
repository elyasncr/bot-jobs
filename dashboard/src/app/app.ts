import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { ApiService } from './core/api.service';

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <header class="top">
      <div class="inner">
        <a class="brand" routerLink="/vagas">
          <span class="logo" aria-hidden="true">
            <svg viewBox="0 0 24 24" width="16" height="16"><path fill="currentColor" d="M9 3h6a2 2 0 0 1 2 2v2h3a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h3V5a2 2 0 0 1 2-2Zm0 4h6V5H9v2Z"/></svg>
          </span>
          <span>vagas<span class="dim">-pj-bot</span></span>
        </a>
        <nav>
          <a routerLink="/vagas" routerLinkActive="active">Vagas</a>
          <a routerLink="/benchmark" routerLinkActive="active">Benchmark</a>
        </nav>
      </div>
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
    .top { position: sticky; top: 0; z-index: 10; border-bottom: 1px solid var(--border);
           background: color-mix(in srgb, var(--surface) 88%, transparent); backdrop-filter: saturate(1.4) blur(10px); }
    .inner { display: flex; align-items: center; gap: 28px; max-width: 1400px; margin: 0 auto; padding: 0 24px; height: 56px; }
    .brand { display: inline-flex; align-items: center; gap: 10px; font-weight: 700; color: var(--text); text-decoration: none;
             letter-spacing: -0.01em; }
    .logo { display: grid; place-items: center; width: 28px; height: 28px; border-radius: 8px; color: #fff;
            background: linear-gradient(135deg, #6e6ef0, #4a4ac4); box-shadow: var(--shadow-sm); }
    .dim { color: var(--faint); font-weight: 500; }
    nav { display: flex; gap: 2px; height: 100%; }
    nav a { display: flex; align-items: center; padding: 0 12px; color: var(--muted); text-decoration: none; font-weight: 500;
            border-bottom: 2px solid transparent; margin-bottom: -1px; }
    nav a:hover { color: var(--text); }
    nav a.active { color: var(--text); border-bottom-color: var(--accent); font-weight: 600; }
    .alert { display: flex; justify-content: space-between; gap: 12px; margin: 12px max(24px, calc((100% - 1352px) / 2)) 0; padding: 10px 14px;
             border-radius: 8px; background: var(--danger-bg); color: var(--danger); border: 1px solid var(--danger); }
    .alert button { all: unset; cursor: pointer; }
    main { padding: 24px 24px 56px; max-width: 1400px; margin: 0 auto; }
    @media (max-width: 720px) {
      .inner { padding: 0 16px; gap: 16px; height: 52px; }
      .dim { display: none; }
      main { padding: 16px 16px 40px; }
      .alert { margin: 10px 16px 0; }
    }
  `,
})
export class App {
  protected readonly api = inject(ApiService);
}
