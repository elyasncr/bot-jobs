import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, catchError, throwError } from 'rxjs';

import { BenchmarkModels, BenchmarkPayload, BenchmarkRun, BenchmarkStatus, JobRow, LabelResult } from './models';

/** Chamadas da API local. Erros das telas viram mensagem em `lastError` (aviso no topo); os de formulário/painel voltam para quem chamou. */
@Injectable({ providedIn: 'root' })
export class ApiService {
  private readonly http = inject(HttpClient);
  readonly lastError = signal<string | null>(null);

  jobs(): Observable<JobRow[]> {
    return this.track(this.http.get<JobRow[]>('/api/jobs'));
  }

  benchmarkRuns(): Observable<BenchmarkRun[]> {
    return this.track(this.http.get<BenchmarkRun[]>('/api/benchmark/runs'));
  }

  benchmark(run?: string): Observable<BenchmarkPayload> {
    const params = run ? new HttpParams().set('run', run) : undefined;
    return this.track(this.http.get<BenchmarkPayload>('/api/benchmark', { params }));
  }

  /** Erros (ex.: Ollama fora do ar) voltam para o painel, não para o aviso global. */
  benchmarkModels(): Observable<BenchmarkModels> {
    return this.local(this.http.get<BenchmarkModels>('/api/benchmark/models'));
  }

  startBenchmark(models: string[]): Observable<BenchmarkStatus> {
    return this.local(this.http.post<BenchmarkStatus>('/api/benchmark/run', { models }));
  }

  /** Consulta periódica: uma falha pontual não deve acender o aviso global. */
  benchmarkStatus(): Observable<BenchmarkStatus> {
    return this.local(this.http.get<BenchmarkStatus>('/api/benchmark/status'));
  }

  /** Sem `note`, o comentário atual é mantido. Erros de nota não vão para o aviso global. */
  saveLabel(id: string, score: number | null, note?: string): Observable<LabelResult> {
    const body = note === undefined ? { score } : { score, note };
    return this.local(this.http.put<LabelResult>(`/api/labels/${encodeURIComponent(id)}`, body));
  }

  private local<T>(request: Observable<T>): Observable<T> {
    return request.pipe(catchError((err: HttpErrorResponse) => throwError(() => new Error(errorMessage(err)))));
  }

  private track<T>(request: Observable<T>): Observable<T> {
    return request.pipe(
      catchError((err: HttpErrorResponse) => {
        const message = errorMessage(err);
        this.lastError.set(message);
        return throwError(() => new Error(message));
      }),
    );
  }
}

export function errorMessage(err: HttpErrorResponse): string {
  if (err.status === 0) {
    return 'API fora do ar. Rode: uv run python -m vagas_bot dashboard';
  }
  const body = err.error as { error?: string } | null;
  return body?.error ?? `Erro ${err.status}: ${err.statusText}`;
}
