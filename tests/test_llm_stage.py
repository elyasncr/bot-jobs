from helpers import FakeScorer, llm_output, make_job

from vagas_bot.models import PJStatus, Prefs
from vagas_bot.scoring.llm_stage import llm_stage, merge_pj_status
from vagas_bot.scoring.prompts import SYSTEM_PROMPT, build_user_prompt, estimate_tokens

PREFS = Prefs(modalities=["remote"], hybrid_allowed_cities=["Rio de Janeiro"])
CV = "# Fulano\n## Resumo\nIA"


def test_scores_and_computes_total_in_code() -> None:
    jobs = [make_job(title="A"), make_job(title="B")]
    scored, info = llm_stage(jobs, FakeScorer(), CV, PREFS, max_calls=60)
    assert [j.score.total for j in scored if j.score] == [78, 78]  # 0.45*80+.2*70+.15*60+.1*100+.1*90
    assert all(j.score and j.score.model == "fake/llm" and j.score.latency_s >= 0 for j in scored)
    assert info.scored == 2 and info.failed == 0


def test_invalid_output_falls_back_per_job() -> None:
    jobs = [make_job(title="A"), make_job(title="invalid"), make_job(title="C")]
    scored, info = llm_stage(jobs, FakeScorer(), CV, PREFS, max_calls=60)
    assert [j.score is not None for j in scored] == [True, False, True]
    assert info.failed == 1


def test_unavailable_at_healthcheck_skips_stage() -> None:
    jobs = [make_job(title="A")]
    scorer = FakeScorer(down=True)
    scored, info = llm_stage(jobs, scorer, CV, PREFS, max_calls=60)
    assert scored == jobs and scorer.scored == [] and info.available is False


def test_crash_mid_stage_keeps_rest_unscored() -> None:
    jobs = [make_job(title="A"), make_job(title="crash"), make_job(title="C")]
    scorer = FakeScorer()
    scored, info = llm_stage(jobs, scorer, CV, PREFS, max_calls=60)
    assert [j.title for j in scored] == ["A", "crash", "C"]
    assert [j.score is not None for j in scored] == [True, False, False]
    assert scorer.scored == ["A"] and info.available is False


def test_max_calls_limit() -> None:
    jobs = [make_job(title=t) for t in "ABCD"]
    scorer = FakeScorer()
    scored, _ = llm_stage(jobs, scorer, CV, PREFS, max_calls=2)
    assert scorer.scored == ["A", "B"]
    assert len(scored) == 4 and scored[2].score is None


def test_llm_decides_uncertain_contract_only() -> None:
    with_evidence = make_job(description="Benefícios: vale-refeição, FGTS.", pj_status=PJStatus.UNCERTAIN)
    assert merge_pj_status(with_evidence, PJStatus.CLT) is PJStatus.CLT
    assert merge_pj_status(make_job(pj_status=PJStatus.PJ), PJStatus.CLT) is PJStatus.PJ


def test_llm_clt_without_evidence_stays_uncertain() -> None:
    job = make_job(title="Senior LLM Engineer - Remote", description="LangChain, RAG.", pj_status=PJStatus.UNCERTAIN)
    assert merge_pj_status(job, PJStatus.CLT) is PJStatus.UNCERTAIN
    scored, _ = llm_stage([job], FakeScorer(output=llm_output(pj_status=PJStatus.CLT)), CV, PREFS, 60)
    assert scored[0].pj_status is PJStatus.UNCERTAIN


def test_llm_both_accepted_for_uncertain() -> None:
    job = make_job(title="A", pj_status=PJStatus.UNCERTAIN)
    scored, _ = llm_stage([job], FakeScorer(output=llm_output(pj_status=PJStatus.BOTH)), CV, PREFS, 60)
    assert scored[0].pj_status is PJStatus.BOTH


# --- prompts --------------------------------------------------------------------------


def test_user_prompt_contents() -> None:
    job = make_job(title="AI Engineer", company="ACME", description="LangChain e RAG", is_remote=None)
    prompt = build_user_prompt(job, CV, PREFS)
    assert CV in prompt
    assert "AI Engineer" in prompt and "ACME" in prompt and "LangChain e RAG" in prompt
    assert "Remoto (segundo o site): não informado" in prompt
    assert "Modalidades aceitas: remoto" in prompt and "Contrato desejado: PJ" in prompt


def test_system_prompt_has_rubric_and_pj_definition() -> None:
    for word in ("technical", "seniority", "domain", "modality_contract", "language", "DA VAGA"):
        assert word in SYSTEM_PROMPT


def test_empty_description_hint() -> None:
    assert "avalie só pelo título" in build_user_prompt(make_job(description=""), CV, PREFS)


def test_estimate_tokens() -> None:
    assert estimate_tokens([{"role": "user", "content": "x" * 400}]) == 100
