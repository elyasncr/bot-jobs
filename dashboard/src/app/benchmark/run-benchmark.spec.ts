import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';

import { BenchmarkStatus } from '../core/models';
import { RunBenchmark } from './run-benchmark';

const URL = '/api/benchmark/status';

function status(over: Partial<BenchmarkStatus> = {}): BenchmarkStatus {
  return {
    state: 'running', phase: 'running', models: ['m'], current_model: 'm', model_index: 1, model_count: 1,
    done: 1, total: 4, added: 0, started_at: null, finished_at: null, result_file: null, error: null, ...over,
  };
}

describe('RunBenchmark', () => {
  let http: HttpTestingController;
  let fixture: ComponentFixture<RunBenchmark>;
  let finished: string[];

  /** Cria o componente com a consulta inicial já respondida. */
  function create(initial: BenchmarkStatus): void {
    fixture = TestBed.createComponent(RunBenchmark);
    finished = [];
    fixture.componentRef.instance.finished.subscribe((f) => finished.push(f));
    http.expectOne(URL).flush(initial);
    fixture.detectChanges();
  }

  beforeEach(() => {
    vi.useFakeTimers();
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('retoma a rodada, emite finished uma vez com o arquivo e para de consultar', () => {
    create(status());
    vi.advanceTimersByTime(3000);
    http.expectOne(URL).flush(status({ state: 'done', result_file: 'eval_1.json' }));
    expect(finished).toEqual(['eval_1.json']);
    vi.advanceTimersByTime(3000);
    http.expectNone(URL);
    expect(finished).toEqual(['eval_1.json']);
  });

  it('não consulta mais depois de destruído', () => {
    create(status());
    fixture.destroy();
    vi.advanceTimersByTime(6000);
    http.expectNone(URL);
  });

  it('uma consulta que falha não interrompe o acompanhamento', () => {
    create(status());
    vi.advanceTimersByTime(3000);
    http.expectOne(URL).flush({ error: 'x' }, { status: 500, statusText: 'Server Error' });
    vi.advanceTimersByTime(3000);
    http.expectOne(URL).flush(status({ done: 2 }));
    vi.advanceTimersByTime(3000);
    http.expectOne(URL).flush(status({ state: 'done', result_file: 'eval_2.json' }));
    expect(finished).toEqual(['eval_2.json']);
  });

  it('rodando que volta a idle mostra que a rodada foi interrompida', () => {
    create(status());
    vi.advanceTimersByTime(3000);
    http.expectOne(URL).flush(status({ state: 'idle', phase: null }));
    fixture.detectChanges();
    expect(finished).toEqual([]);
    expect((fixture.nativeElement as HTMLElement).querySelector('[role="alert"]')?.textContent).toContain(
      'A rodada foi interrompida (o dashboard foi reiniciado).',
    );
    vi.advanceTimersByTime(3000);
    http.expectNone(URL);
  });
});
