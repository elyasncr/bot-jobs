import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '', pathMatch: 'full', redirectTo: 'vagas' },
  { path: 'vagas', title: 'Vagas · vagas-pj-bot', loadComponent: () => import('./jobs/jobs-page').then((m) => m.JobsPage) },
  {
    path: 'benchmark',
    title: 'Benchmark · vagas-pj-bot',
    loadComponent: () => import('./benchmark/benchmark-page').then((m) => m.BenchmarkPage),
  },
  { path: '**', redirectTo: 'vagas' },
];
