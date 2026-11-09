import { ChangeDetectionStrategy, Component, input, linkedSignal, output } from '@angular/core';

import {
  CONTRACT_LABELS,
  JobRow,
  MODALITY_LABELS,
  PartialScores,
  REASON_LABELS,
  STAGE_LABELS,
  formatDate,
  sourceLabel,
} from '../core/models';
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
    <div class="backdrop" (click)="close.emit()"></div>
    <aside aria-label="Detalhe da vaga">
      <header>
        <div class="heading">
          <p class="eyebrow"><i class="stage-dot" [attr.data-stage]="job.stage"></i>{{ stage[job.stage] }}
            @if (job.filter_reason) {
              · {{ reason[job.filter_reason] }}
            }
          </p>
          <h2>{{ job.title }}</h2>
          <p class="company">{{ job.company }}</p>
          <div class="tags">
            @if (job.location) {
              <span class="tag">{{ job.location }}</span>
            }
            @if (job.modality !== 'unknown') {
              <span class="tag">{{ modality[job.modality] }}</span>
            }
            @if (job.source !== 'history') {
              <span class="tag">{{ source(job) }}</span>
            }
            @if (job.low_fidelity) {
              <span class="tag warn">baixa fidelidade</span>
            }
          </div>
        </div>
        <button type="button" class="close" (click)="close.emit()" aria-label="Fechar">
          <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
            <path d="M4 4l8 8M12 4l-8 8" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" />
          </svg>
        </button>
      </header>

      <dl class="stats">
        <div>
          <dt>Nota do LLM</dt>
          <dd><app-score-badge [total]="job.total" [estimate]="job.is_estimate" /></dd>
        </div>
        <div>
          <dt>Contrato</dt>
          <dd><span class="contract" [attr.data-pj]="job.pj_status">{{ contract[job.pj_status] }}</span></dd>
        </div>
        <div>
          <dt>Cos</dt>
          <dd>{{ job.embedding_score === null ? '—' : job.embedding_score.toFixed(3) }}</dd>
        </div>
        <div>
          <dt>Capturada</dt>
          <dd>{{ date(job.run_date) }}</dd>
        </div>
      </dl>
      @if (job.url) {
        <a class="open" [href]="job.url" target="_blank" rel="noopener">
          Abrir vaga
          <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
            <path d="M6 3h7v7M13 3 5 11" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
          </svg>
        </a>
      }
      @if (job.posted_at || job.llm_model) {
        <p class="fine">
          @if (job.posted_at) {
            Publicada em {{ date(job.posted_at) }}
          }
          @if (job.posted_at && job.llm_model) {
            ·
          }
          @if (job.llm_model) {
            avaliada por {{ job.llm_model }}
          }
        </p>
      }

      <section class="mine">
        <h3>Sua avaliação</h3>
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
          <h3>Leitura do LLM</h3>
          @if (job.summary) {
            <p class="summary">{{ job.summary }}</p>
          }
          <div class="lists">
            @if (job.strengths.length) {
              <div class="good">
                <h4>Pontos fortes</h4>
                <ul>
                  @for (s of job.strengths; track $index) {
                    <li>{{ s }}</li>
                  }
                </ul>
              </div>
            }
            @if (job.gaps.length) {
              <div class="gap">
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
  host: { '(document:keydown.escape)': 'close.emit()' },
  styles: `
    .backdrop { position: fixed; inset: 0; z-index: 19; background: var(--backdrop); animation: fade 0.15s ease-out; }
    aside {
      position: fixed; top: 0; right: 0; bottom: 0; width: min(580px, 100%); overflow-y: auto; z-index: 20;
      background: var(--surface); border-left: 1px solid var(--border); box-shadow: var(--shadow); padding: 22px 26px 48px;
      animation: slide 0.18s ease-out;
    }
    @keyframes fade { from { opacity: 0; } }
    @keyframes slide { from { transform: translateX(24px); opacity: 0.6; } }
    header { display: flex; justify-content: space-between; align-items: start; gap: 12px; }
    .eyebrow { display: flex; align-items: center; gap: 6px; margin: 0 0 6px; font-size: 0.78rem; font-weight: 500; color: var(--muted); }
    h2 { margin: 0; font-size: 1.25rem; line-height: 1.3; letter-spacing: -0.01em; }
    .company { margin: 4px 0 0; color: var(--muted); }
    .tags { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
    h3 { margin: 0 0 10px; font-size: 0.78rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: var(--faint); }
    h4 { margin: 0 0 6px; font-size: 0.85rem; }
    section { margin-top: 22px; }
    .close { all: unset; cursor: pointer; display: grid; place-items: center; width: 32px; height: 32px; border-radius: 8px; color: var(--muted); flex: none; }
    .close:hover { background: var(--hover); color: var(--text); }
    .close:focus-visible { outline: 2px solid var(--accent); }
    .stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); margin: 18px 0 0; border: 1px solid var(--border); border-radius: var(--radius); overflow: hidden; }
    .stats div { padding: 10px 12px; border-left: 1px solid var(--border); }
    .stats div:first-child { border-left: 0; }
    dt { font-size: 0.72rem; color: var(--faint); margin-bottom: 4px; }
    dd { margin: 0; font-weight: 600; font-variant-numeric: tabular-nums; }
    .open { display: inline-flex; align-items: center; gap: 6px; margin-top: 14px; padding: 7px 14px; border-radius: 8px;
            background: var(--accent); color: var(--on-accent); font-weight: 600; text-decoration: none; font-size: 0.9rem; }
    .open:hover { background: var(--accent-strong); }
    .fine { margin: 10px 0 0; font-size: 0.8rem; color: var(--faint); }
    .mine { padding: 14px 16px; border-radius: var(--radius); background: var(--accent-bg); }
    .mine h3 { color: var(--accent); }
    .mine-row { display: flex; align-items: end; gap: 10px; margin-bottom: 10px; }
    .mine label { display: flex; flex-direction: column; gap: 4px; font-size: 0.8rem; color: var(--muted); }
    .mine input { width: 5em; }
    textarea { width: 100%; resize: vertical; }
    .ok { color: var(--high); font-size: 0.85rem; font-weight: 500; }
    .error { color: var(--danger); font-size: 0.85rem; margin: 6px 0 0; }
    .bar { display: grid; grid-template-columns: 170px 1fr 2.5em; align-items: center; gap: 12px; margin: 8px 0; font-size: 0.88rem; }
    .track { height: 6px; border-radius: 3px; background: var(--surface-2); overflow: hidden; }
    .fill { display: block; height: 100%; border-radius: 3px; background: var(--accent); }
    .num { text-align: right; font-variant-numeric: tabular-nums; font-weight: 600; }
    .summary { margin: 0 0 12px; line-height: 1.55; }
    .lists { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; font-size: 0.88rem; }
    .lists .good h4 { color: var(--high); }
    .lists .gap h4 { color: var(--maybe); }
    ul { margin: 0; padding-left: 18px; line-height: 1.5; }
    li + li { margin-top: 3px; }
    .description { white-space: pre-wrap; font-size: 0.88rem; line-height: 1.6; color: var(--muted); }
    .muted { color: var(--muted); }
    @media (max-width: 720px) {
      aside { padding: 18px 16px 40px; border-left: 0; }
      .stats { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .stats div:nth-child(3) { border-left: 0; }
      .stats div:nth-child(n + 3) { border-top: 1px solid var(--border); }
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
  protected readonly stage = STAGE_LABELS;
  protected readonly reason = REASON_LABELS;
  protected readonly source = sourceLabel;
  protected readonly date = (iso: string) => formatDate(iso);
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
