import { HttpClient, HttpErrorResponse, HttpParams } from '@angular/common/http';
import { Injectable, inject, signal } from '@angular/core';
import { Observable, catchError, throwError } from 'rxjs';

import { BenchmarkPayload, BenchmarkRun, JobRow, LabelResult } from './models';

/** As 4 chamadas da API local. Erros viram mensagem em `lastError` (aviso no topo da tela). */
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

  /** Sem `note`, o comentário atual é mantido. Erros de nota não vão para o aviso global. */
  saveLabel(id: string, score: number | null, note?: string): Observable<LabelResult> {
    const body = note === undefined ? { score } : { score, note };
    return this.http
      .put<LabelResult>(`/api/labels/${encodeURIComponent(id)}`, body)
      .pipe(catchError((err: HttpErrorResponse) => throwError(() => new Error(errorMessage(err)))));
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
