import { ChangeDetectionStrategy, Component, input, linkedSignal, output } from '@angular/core';

import { CONTRACT_LABELS, JobRow, MODALITY_LABELS, PartialScores } from '../core/models';
import { SaveState, parseScore } from '../shared/label-input';
import { ScoreBadge } from '../shared/score-badge';

const CRITERIA: { key: keyof PartialScores; label: string; weight: number }[] = [
  { key: 'technical', label: 'Técnico', weight: 45 },
  { key: 'seniority', label: 'Senioridade', weight: 20 },
  { key: 'domain', label: 'Domínio', weight: 15 },
  { key: 'modality_contract', label: 'Modalidade/contrato', weight: 10 },
  { key: 'language', label: 'Idioma', weight: 10 },
];

export interface DetailSave {
  score: number | null;
  note: string;
}

/** Painel lateral: descrição, avaliação do LLM e minha nota + comentário. */
@Component({
  selector: 'app-job-detail',
  imports: [ScoreBadge],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @let job = row();
    <aside aria-label="Detalhe da vaga">
      <header>
        <div>
          <h2>{{ job.title }}</h2>
          <p class="muted">
            {{ job.company }} · {{ job.location || 'local não informado' }} · {{ modality[job.modality] }}
          </p>
        </div>
        <button type="button" class="close" (click)="close.emit()" aria-label="Fechar">✕</button>
      </header>

      <div class="meta">
        <app-score-badge [total]="job.total" [estimate]="job.is_estimate" />
        <span>Contrato: <strong>{{ contract[job.pj_status] }}</strong></span>
        @if (job.url) {
          <a [href]="job.url" target="_blank" rel="noopener">Abrir vaga ↗</a>
        }
      </div>
      <p class="muted small">
        {{ job.publisher || job.source }} · capturada em {{ job.run_date }}
        @if (job.posted_at) {
          · publicada em {{ job.posted_at.slice(0, 10) }}
        }
        @if (job.llm_model) {
          · {{ job.llm_model }}
        }
      </p>

      <section class="mine">
        <h3>Minha avaliação</h3>
        <div class="mine-row">
          <label>
            Nota (0–100)
            <input type="text" inputmode="numeric" maxlength="3" [value]="score()" (input)="score.set($any($event.target).value)" />
          </label>
          <button type="button" (click)="submit()" [disabled]="invalid() || state() === 'saving'">
            {{ state() === 'saving' ? 'Salvando…' : 'Salvar' }}
          </button>
          @if (state() === 'saved') {
            <span class="ok">Salvo ✓</span>
          }
        </div>
        <textarea rows="2" placeholder="Comentário (opcional)" [value]="note()" (input)="note.set($any($event.target).value)"></textarea>
        @if (invalid()) {
          <p class="error">Use um inteiro de 0 a 100 (vazio apaga a nota).</p>
        }
        @if (state() === 'error') {
          <p class="error">{{ error() }}</p>
        }
      </section>

      @if (job.scores) {
        <section>
          <h3>Notas do LLM</h3>
          @for (c of criteria; track c.key) {
            <div class="bar">
              <span>{{ c.label }} <small class="muted">{{ c.weight }}%</small></span>
              <span class="track"><span class="fill" [style.width.%]="job.scores[c.key]"></span></span>
              <span class="num">{{ job.scores[c.key] }}</span>
            </div>
          }
        </section>
      }

      @if (job.summary || job.strengths.length || job.gaps.length) {
        <section>
          @if (job.summary) {
            <p>{{ job.summary }}</p>
          }
          <div class="lists">
            @if (job.strengths.length) {
              <div>
                <h4>Pontos fortes</h4>
                <ul>
                  @for (s of job.strengths; track $index) {
                    <li>{{ s }}</li>
                  }
                </ul>
              </div>
            }
            @if (job.gaps.length) {
              <div>
                <h4>Lacunas</h4>
                <ul>
                  @for (g of job.gaps; track $index) {
                    <li>{{ g }}</li>
                  }
                </ul>
              </div>
            }
          </div>
        </section>
      }

      <section>
        <h3>Descrição</h3>
        @if (job.description) {
          <p class="description">{{ job.description }}</p>
        } @else {
          <p class="muted">Sem descrição (vaga de alerta do LinkedIn: avaliada só pelo título).</p>
        }
      </section>
    </aside>
  `,
  styles: `
    aside {
      position: fixed; top: 0; right: 0; bottom: 0; width: min(560px, 100%); overflow-y: auto; z-index: 20;
      background: var(--surface); border-left: 1px solid var(--border); box-shadow: var(--shadow); padding: 20px 22px 40px;
    }
    header { display: flex; justify-content: space-between; gap: 12px; }
    h2 { margin: 0 0 4px; font-size: 1.2rem; }
    h3 { margin: 0 0 8px; font-size: 0.95rem; }
    h4 { margin: 0 0 4px; font-size: 0.85rem; }
    section { margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--border); }
    .close { all: unset; cursor: pointer; font-size: 1.1rem; padding: 4px 8px; border-radius: 6px; height: fit-content; }
    .close:hover { background: var(--hover); }
    .meta { display: flex; flex-wrap: wrap; align-items: center; gap: 14px; margin-top: 12px; }
    .meta a { color: var(--accent); }
    .muted { color: var(--muted); }
    .small { font-size: 0.82rem; margin: 6px 0 0; }
    .mine-row { display: flex; align-items: end; gap: 10px; margin-bottom: 8px; }
    .mine label { display: flex; flex-direction: column; gap: 4px; font-size: 0.82rem; color: var(--muted); }
    .mine input { width: 4.5em; }
    textarea { width: 100%; box-sizing: border-box; resize: vertical; }
    .ok { color: var(--high); font-size: 0.85rem; }
    .error { color: var(--danger); font-size: 0.85rem; margin: 4px 0 0; }
    .bar { display: grid; grid-template-columns: 170px 1fr 2.5em; align-items: center; gap: 10px; margin: 6px 0; font-size: 0.88rem; }
    .track { height: 8px; border-radius: 4px; background: var(--surface-2); overflow: hidden; }
    .fill { display: block; height: 100%; background: var(--accent); }
    .num { text-align: right; font-variant-numeric: tabular-nums; }
    .lists { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; font-size: 0.88rem; }
    ul { margin: 0; padding-left: 18px; }
    .description { white-space: pre-wrap; font-size: 0.88rem; line-height: 1.5; }
    @media (max-width: 720px) {
      .bar { grid-template-columns: 120px 1fr 2.5em; }
      .lists { grid-template-columns: 1fr; }
    }
  `,
})
export class JobDetail {
  readonly row = input.required<JobRow>();
  readonly state = input<SaveState>('idle');
  readonly error = input<string | null>(null);
  readonly close = output<void>();
  readonly save = output<DetailSave>();

  protected readonly criteria = CRITERIA;
  protected readonly contract = CONTRACT_LABELS;
  protected readonly modality = MODALITY_LABELS;
  protected readonly score = linkedSignal(() => (this.row().my_score === null ? '' : String(this.row().my_score)));
  protected readonly note = linkedSignal(() => this.row().my_note);

  protected invalid(): boolean {
    return parseScore(this.score()) === undefined;
  }

  protected submit(): void {
    const parsed = parseScore(this.score());
    if (parsed === undefined) return;
    this.save.emit({ score: parsed, note: this.note() });
  }
}
