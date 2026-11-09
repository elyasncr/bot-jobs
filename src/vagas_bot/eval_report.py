"""eval_report.md: model comparison tables + an automatic reading to help choose the default."""

from typing import Any

from vagas_bot.evaluation import JobMeta, ModelRun, ModelSummary, agreement

RELIABLE_MAX_RATE = 0.10  # acima de 10% de falhas ou JSON inválido, o modelo não serve para o diário
MIN_GOLD_FOR_DECISION = 5
PJ_SHORT = {"pj": "PJ", "both": "PJ/CLT", "clt": "CLT", "uncertain": "?"}


def _fmt(value: float | None, pattern: str = "{:.1f}", empty: str = "—") -> str:
    return pattern.format(value) if value is not None else empty


def _pct(value: float | None) -> str:
    return _fmt(None if value is None else 100 * value, "{:.0f}%")


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def is_reliable(s: ModelSummary) -> bool:
    return s.available and s.ok > 0 and s.fail_rate <= RELIABLE_MAX_RATE and s.invalid_rate <= RELIABLE_MAX_RATE


def summary_table(summaries: list[ModelSummary]) -> list[str]:
    ref = summaries[0] if summaries else None
    lines = [
        f"| Modelo | s/vaga (média · mediana) | Carga | VRAM | JSON inválido | Falhas | Nota média "
        f"| Δ entre rodadas (média · máx) | pj_status estável | CLT sem evidência | Spearman (você) "
        f"| Concordância c/ {ref.model if ref else '—'} |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        if not s.available and not s.ok:
            lines.append(f"| {s.model} | indisponível: {_cell(s.error or '')} |" + " |" * 10)
            continue
        gold = f"{_fmt(s.spearman_gold, '{:.2f}')} (n={s.n_gold})" if s.n_gold else "—"
        agree = "—" if ref is None or s is ref else _fmt(agreement(ref, s), "{:.2f}")
        lines.append(
            f"| {s.model} | {_fmt(s.mean_s, '{:.1f}s')} · {_fmt(s.median_s, '{:.1f}s')} | {_fmt(s.load_s, '{:.0f}s')} "
            f"| {_fmt(s.vram_gb, '{:.1f} GB')} | {_pct(s.invalid_rate)} ({s.invalid}/{s.calls}) "
            f"| {s.failed} | {_fmt(s.mean_total, '{:.0f}')} "
            f"| {_fmt(s.mean_abs_diff)} · {_fmt(s.max_diff, '{:.0f}')} | {_pct(s.pj_consistency)} "
            f"| {s.clt_without_evidence}/{s.clt_answers} | {gold} | {agree} |"
        )
    return lines


def side_by_side(runs: list[ModelRun], metas: list[JobMeta], labels: dict[str, int]) -> list[str]:
    header = "| Vaga | Você | " + " | ".join(r.model for r in runs) + " |"
    lines = [header, "|---|---|" + "---|" * len(runs)]
    for meta in metas:
        title = _cell(f"{meta.title} · {meta.company}")[:70]
        cells = [f"[{title}]({meta.url})", str(labels.get(meta.id, "—"))]
        for run in runs:
            trials = sorted((t for t in run.trials if t.job_id == meta.id), key=lambda t: t.run)
            totals = " / ".join(str(t.total) if t.total is not None else "✗" for t in trials) or "—"
            statuses = sorted({t.output.pj_status.value for t in trials if t.output})
            pj = "/".join(PJ_SHORT[s] for s in statuses)
            warn = " ⚠" if "clt" in statuses and not meta.clt_signals else ""
            cells.append(f"{totals}" + (f" · {pj}{warn}" if pj else ""))
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def reading(summaries: list[ModelSummary], n_labels: int) -> list[str]:
    reliable = [s for s in summaries if is_reliable(s)]
    lines: list[str] = []
    unreliable = [s.model for s in summaries if s not in reliable]
    if unreliable:
        lines.append(f"- **Fora da disputa** (indisponível ou > {RELIABLE_MAX_RATE:.0%} de falhas/JSON inválido): "
                     + ", ".join(unreliable) + ".")
    if not reliable:
        return [*lines, "- Nenhum modelo confiável nesta rodada."]

    def best(key: Any, label: str, fmt: str) -> None:
        candidates = [s for s in reliable if key(s) is not None]
        if candidates:
            top = min(candidates, key=key)
            lines.append(f"- **{label}:** {top.model} ({fmt.format(key(top))}).")

    best(lambda s: s.mean_s, "Mais rápido", "{:.1f}s/vaga")
    best(lambda s: s.mean_abs_diff, "Mais consistente entre rodadas", "Δ médio {:.1f} ponto(s)")
    best(lambda s: s.clt_without_evidence, "Menos \"CLT\" sem evidência no texto", "{} resposta(s)")

    with_gold = [s for s in reliable if s.spearman_gold is not None and s.n_gold >= MIN_GOLD_FOR_DECISION]
    if with_gold:
        top = max(with_gold, key=lambda s: s.spearman_gold or -1)
        lines.append(f"- **Mais alinhado às suas notas:** {top.model} (Spearman {top.spearman_gold:.2f}, "
                     f"n={top.n_gold}). **Sugestão de padrão: {top.model}** — é o critério que mais importa.")
    else:
        lines.append(
            f"- Sem notas suas suficientes ({n_labels} em `data/eval/labels.yaml`; mínimo {MIN_GOLD_FOR_DECISION}), "
            "a qualidade não está medida contra você. Preencha as notas e rode `eval-report` "
            "(recalcula sem chamar os modelos de novo)."
        )
    return lines


def render_report(
    runs: list[ModelRun],
    summaries: list[ModelSummary],
    metas: list[JobMeta],
    labels: dict[str, int],
    meta: dict[str, Any],
) -> str:
    lines = [
        "# Comparação de modelos (eval-models)",
        "",
        f"- Data: {meta.get('date', '—')} · vagas: {len(metas)} · rodadas por vaga: {meta.get('runs', '—')}",
        f"- Configuração comum: num_ctx={meta.get('num_ctx')}, temperature={meta.get('temperature')}, "
        f"think={meta.get('think')}",
        f"- Notas suas (labels.yaml): {sum(1 for m in metas if m.id in labels)} de {len(metas)} vagas",
        f"- Resultados brutos: `{meta.get('results_file', '—')}`",
        "",
        "## Resumo",
        "",
        *summary_table(summaries),
        "",
        "**Como ler:** *s/vaga* exclui a 1ª chamada (carga do modelo, coluna *Carga*). *Δ entre rodadas* é a "
        "diferença da nota final na mesma vaga entre as rodadas (0 = totalmente determinístico). "
        "*CLT sem evidência* conta respostas \"clt\" em vagas sem nenhum sinal de CLT no texto "
        "(no diário, a trava as mantém como incertas). *Spearman (você)* mede se o modelo ordena as vagas "
        "como você (1 = igual, 0 = sem relação). *Concordância* é o Spearman entre os modelos.",
        "",
        "## Leitura automática",
        "",
        *reading(summaries, len(labels)),
        "",
        "## Notas lado a lado",
        "",
        "Nota final por rodada (✗ = falha) · pj_status (⚠ = CLT sem evidência no texto).",
        "",
        *side_by_side(runs, metas, labels),
        "",
    ]
    return "\n".join(lines)
