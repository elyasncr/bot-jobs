import { TestBed } from '@angular/core/testing';

import { LabelInput, parseScore } from './label-input';
import { bandOf } from './score-badge';

describe('parseScore', () => {
  it('aceita inteiros de 0 a 100 e vazio', () => {
    expect(parseScore('0')).toBe(0);
    expect(parseScore(' 100 ')).toBe(100);
    expect(parseScore('')).toBeNull();
  });

  it('rejeita fora da faixa, decimais e texto', () => {
    for (const bad of ['101', '-1', '7.5', 'abc', '1e2']) {
      expect(parseScore(bad)).toBeUndefined();
    }
  });
});

describe('bandOf', () => {
  it('usa as faixas do email', () => {
    expect([bandOf(80), bandOf(79), bandOf(65), bandOf(64), bandOf(50), bandOf(49), bandOf(null)]).toEqual([
      'high', 'good', 'good', 'maybe', 'maybe', 'low', 'none',
    ]);
  });
});

describe('LabelInput', () => {
  function setup(value: number | null) {
    const fixture = TestBed.createComponent(LabelInput);
    fixture.componentRef.setInput('value', value);
    fixture.detectChanges();
    const emitted: (number | null)[] = [];
    fixture.componentInstance.save.subscribe((v) => emitted.push(v));
    const input: HTMLInputElement = fixture.nativeElement.querySelector('input');
    const type = (text: string) => {
      input.value = text;
      input.dispatchEvent(new Event('input'));
      input.dispatchEvent(new Event('blur'));
      fixture.detectChanges();
    };
    return { fixture, emitted, input, type };
  }

  it('mostra o valor atual', () => {
    expect(setup(70).input.value).toBe('70');
  });

  it('emite a nova nota ao sair do campo', () => {
    const { emitted, type } = setup(70);
    type('85');
    expect(emitted).toEqual([85]);
  });

  it('vazio emite null (apagar) e valor igual não emite', () => {
    const { emitted, type } = setup(70);
    type('70');
    type('');
    expect(emitted).toEqual([null]);
  });

  it('valor inválido não emite e marca erro', () => {
    const { emitted, type, fixture } = setup(null);
    type('150');
    expect(emitted).toEqual([]);
    expect(fixture.nativeElement.querySelector('.wrap').dataset.state).toBe('error');
  });
});
