import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { TestBed } from '@angular/core/testing';

import { ApiService } from './api.service';

describe('ApiService', () => {
  let api: ApiService;
  let http: HttpTestingController;

  beforeEach(() => {
    TestBed.configureTestingModule({ providers: [provideHttpClient(), provideHttpClientTesting()] });
    api = TestBed.inject(ApiService);
    http = TestBed.inject(HttpTestingController);
  });

  afterEach(() => http.verify());

  it('busca as vagas', () => {
    let rows: unknown;
    api.jobs().subscribe((r) => (rows = r));
    http.expectOne({ method: 'GET', url: '/api/jobs' }).flush([{ id: 'a' }]);
    expect(rows).toEqual([{ id: 'a' }]);
  });

  it('passa o run do benchmark como query param', () => {
    api.benchmark('eval_1.json').subscribe();
    const req = http.expectOne((r) => r.url === '/api/benchmark');
    expect(req.request.params.get('run')).toBe('eval_1.json');
    req.flush({});
    api.benchmark().subscribe();
    expect(http.expectOne('/api/benchmark').request.params.has('run')).toBe(false);
  });

  it('codifica o id e envia score e note no PUT', () => {
    api.saveLabel('linkedin:1/2=', 80, 'boa').subscribe();
    const req = http.expectOne('/api/labels/linkedin%3A1%2F2%3D');
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual({ score: 80, note: 'boa' });
    req.flush({ id: 'linkedin:1/2=', my_score: 80, my_note: 'boa' });
  });

  it('sem comentário não envia note (o servidor mantém o atual)', () => {
    api.saveLabel('x', 60).subscribe();
    const req = http.expectOne('/api/labels/x');
    expect(req.request.body).toEqual({ score: 60 });
    req.flush({ id: 'x', my_score: 60, my_note: 'antigo' });
  });

  it('erro de leitura vira aviso global com a mensagem da API', () => {
    let error: Error | undefined;
    api.benchmarkRuns().subscribe({ error: (e: Error) => (error = e) });
    http.expectOne('/api/benchmark/runs').flush({ error: 'Nenhum resultado' }, { status: 404, statusText: 'Not Found' });
    expect(error?.message).toBe('Nenhum resultado');
    expect(api.lastError()).toBe('Nenhum resultado');
  });

  it('erro ao salvar nota não suja o aviso global', () => {
    let error: Error | undefined;
    api.saveLabel('x', 101).subscribe({ error: (e: Error) => (error = e) });
    http.expectOne('/api/labels/x').flush({ error: 'A nota deve ser...' }, { status: 400, statusText: 'Bad Request' });
    expect(error?.message).toBe('A nota deve ser...');
    expect(api.lastError()).toBeNull();
  });
});
