import { TestBed } from '@angular/core/testing';

import { THEME_STORAGE_KEY, ThemeService } from './theme.service';

/** matchMedia falso: o jsdom não implementa, e o teste precisa simular a troca do tema do sistema. */
function fakeSystemTheme(dark: boolean) {
  const listeners: ((e: { matches: boolean }) => void)[] = [];
  const media = {
    matches: dark,
    addEventListener: (_: string, fn: (e: { matches: boolean }) => void) => listeners.push(fn),
  };
  Object.defineProperty(window, 'matchMedia', { configurable: true, value: () => media });
  return {
    change(nowDark: boolean) {
      media.matches = nowDark;
      listeners.forEach((fn) => fn({ matches: nowDark }));
    },
  };
}

describe('ThemeService', () => {
  const root = document.documentElement;

  beforeEach(() => {
    localStorage.clear();
    root.removeAttribute('data-theme');
  });

  it('segue o tema do sistema quando não há escolha salva', () => {
    fakeSystemTheme(true);
    const theme = TestBed.inject(ThemeService);
    expect(theme.theme()).toBe('dark');
    expect(root.dataset['theme']).toBe('dark');
  });

  it('a escolha salva vence o tema do sistema', () => {
    fakeSystemTheme(true);
    localStorage.setItem(THEME_STORAGE_KEY, 'light');
    const theme = TestBed.inject(ThemeService);
    expect(theme.theme()).toBe('light');
    expect(root.dataset['theme']).toBe('light');
  });

  it('toggle alterna, aplica no documento e salva a escolha', () => {
    fakeSystemTheme(true);
    const theme = TestBed.inject(ThemeService);
    theme.toggle();
    expect(theme.theme()).toBe('light');
    expect(root.dataset['theme']).toBe('light');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('light');
    theme.toggle();
    expect(theme.theme()).toBe('dark');
    expect(localStorage.getItem(THEME_STORAGE_KEY)).toBe('dark');
  });

  it('acompanha a troca do tema do sistema só enquanto não há escolha salva', () => {
    const system = fakeSystemTheme(false);
    const theme = TestBed.inject(ThemeService);
    system.change(true);
    expect(theme.theme()).toBe('dark');
    expect(root.dataset['theme']).toBe('dark');
    theme.toggle(); // escolhe claro
    system.change(false);
    system.change(true);
    expect(theme.theme()).toBe('light');
    expect(root.dataset['theme']).toBe('light');
  });

  it('ignora valor inválido salvo', () => {
    fakeSystemTheme(false);
    localStorage.setItem(THEME_STORAGE_KEY, 'roxo');
    expect(TestBed.inject(ThemeService).theme()).toBe('light');
  });
});
