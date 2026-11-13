import { DOCUMENT, Injectable, computed, inject, signal } from '@angular/core';

export type Theme = 'light' | 'dark';

/** Mesma chave lida pelo script inline do index.html (aplica o tema antes da 1ª pintura, sem piscar). */
export const THEME_STORAGE_KEY = 'theme';

/**
 * Tema claro/escuro. Sem escolha salva, segue o sistema (e acompanha se ele mudar);
 * depois do 1º clique no botão, a escolha fica salva neste navegador.
 * O tema vai em <html data-theme="...">, que o styles.css usa para trocar os tokens.
 */
@Injectable({ providedIn: 'root' })
export class ThemeService {
  private readonly root = inject(DOCUMENT).documentElement;
  private readonly chosen = signal<Theme | null>(readStored());
  private readonly system = signal<Theme>('light');

  readonly theme = computed<Theme>(() => this.chosen() ?? this.system());

  constructor() {
    const media = typeof matchMedia === 'function' ? matchMedia('(prefers-color-scheme: dark)') : null;
    if (media) {
      this.system.set(media.matches ? 'dark' : 'light');
      media.addEventListener?.('change', (e) => {
        this.system.set(e.matches ? 'dark' : 'light');
        this.apply();
      });
    }
    this.apply();
  }

  toggle(): void {
    const next: Theme = this.theme() === 'dark' ? 'light' : 'dark';
    this.chosen.set(next);
    try {
      localStorage.setItem(THEME_STORAGE_KEY, next);
    } catch {
      // armazenamento bloqueado (aba anônima etc.): vale só até recarregar
    }
    this.apply();
  }

  private apply(): void {
    this.root.dataset['theme'] = this.theme();
  }
}

function readStored(): Theme | null {
  try {
    const value = localStorage.getItem(THEME_STORAGE_KEY);
    return value === 'light' || value === 'dark' ? value : null;
  } catch {
    return null;
  }
}
