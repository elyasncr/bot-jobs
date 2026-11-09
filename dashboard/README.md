# dashboard (Angular 22)

Tela local do vagas-pj-bot: vagas capturadas e benchmark dos modelos. Ela é servida pelo próprio bot (`uv run python -m vagas_bot dashboard`). Veja a seção "Dashboard" no [README da raiz](../README.md).

```powershell
npm ci             # 1ª vez
npm run build      # gera dist/, que o comando dashboard serve
npm test           # testes unitários (Vitest)
npm start          # desenvolvimento: ng serve com proxy de /api para 127.0.0.1:8765
```

Estrutura:

- `src/app/core/`: interfaces da API e `ApiService`.
- `src/app/jobs/`: tela Vagas, com filtros puros em `job-filters.ts`.
- `src/app/benchmark/`: tela Benchmark (resumo, gráfico SVG e notas lado a lado).
- `src/app/shared/`: campo de nota e selo de faixa.

O contrato da API está em `../docs/superpowers/specs/2026-11-09-dashboard-design.md`.
