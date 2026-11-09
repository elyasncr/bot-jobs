import pytest
from helpers import make_job

from vagas_bot.config import FiltersConfig
from vagas_bot.filters import (
    Modality,
    apply_filters,
    apply_pj_classifier,
    classify_pj,
    detect_modality,
    filter_modality,
    filter_title,
    final_contract_filter,
)
from vagas_bot.models import PJStatus

CFG = FiltersConfig(
    modalities=["remote", "hybrid"],
    hybrid_allowed_cities=["Rio de Janeiro"],
    exclude_title_keywords=["estágio", "estagiário", "intern", "trainee", "júnior", "junior", "jr"],
)


# --- PJ regex -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "description,expected",
    [
        ("Contratação PJ, 100% remoto.", PJStatus.PJ),
        ("Modelo de contratação: Pessoa Jurídica", PJStatus.PJ),
        ("Necessário possuir CNPJ ativo.", PJStatus.PJ),
        ("Contractor position, B2B agreement.", PJStatus.PJ),
        ("Projeto freelancer de 6 meses.", PJStatus.PJ),
        ("Regime CLT com benefícios.", PJStatus.CLT),
        ("Vaga com carteira assinada.", PJStatus.CLT),
        ("Contratação CLT ou PJ, a combinar.", PJStatus.BOTH),
        ("Ótima vaga de IA com Python.", PJStatus.UNCERTAIN),
    ],
)
def test_classify_pj(description: str, expected: PJStatus) -> None:
    assert classify_pj(make_job(description=description)) is expected


def test_pj_inside_another_word_does_not_count() -> None:
    job = make_job(description="Experiência com o projeto PJX e o sistema SPJ. Também Pjotr.")
    assert classify_pj(job) is PJStatus.UNCERTAIN


def test_pj_accents_and_case() -> None:
    assert classify_pj(make_job(description="PESSOA JURÍDICA")) is PJStatus.PJ
    assert classify_pj(make_job(description="pessoa juridica")) is PJStatus.PJ


def test_pj_in_title_counts() -> None:
    assert classify_pj(make_job(title="AI Engineer (PJ)", description="Python")) is PJStatus.PJ


def test_contractor_employment_type_counts_as_positive() -> None:
    job = make_job(description="Python e LLMs.", employment_type="CONTRACTOR,FULLTIME")
    assert classify_pj(job) is PJStatus.PJ
    job = make_job(description="Regime CLT.", employment_type="CONTRACTOR")
    assert classify_pj(job) is PJStatus.BOTH


def test_apply_pj_classifier_drops_clt_and_tags_others() -> None:
    jobs = [
        make_job(title="A", description="CLT"),
        make_job(title="B", description="PJ"),
        make_job(title="C", description="nada"),
    ]
    result = apply_pj_classifier(jobs)
    assert [(j.title, j.pj_status) for j in result] == [("B", PJStatus.PJ), ("C", PJStatus.UNCERTAIN)]


def test_final_contract_filter() -> None:
    jobs = [
        make_job(title="A", pj_status=PJStatus.PJ),
        make_job(title="B", pj_status=PJStatus.UNCERTAIN),
        make_job(title="C", pj_status=PJStatus.CLT),
    ]
    assert [j.title for j in final_contract_filter(jobs, include_uncertain=True)] == ["A", "B"]
    assert [j.title for j in final_contract_filter(jobs, include_uncertain=False)] == ["A"]


# --- title ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title,kept",
    [
        ("AI Engineer", True),
        ("Estágio em Ciência de Dados", False),
        ("Estagiário de IA", False),
        ("Cientista de Dados Júnior", False),
        ("Cientista de Dados Jr.", False),
        ("ML Intern", False),
        ("Trainee IA", False),
        ("Analista Internacional de Dados", True),  # 'intern' só como palavra inteira
        ("Engenheiro de IA Pleno", True),
    ],
)
def test_filter_title(title: str, kept: bool) -> None:
    assert (len(filter_title([make_job(title=title)], CFG.exclude_title_keywords)) == 1) is kept


# --- modality -------------------------------------------------------------------------


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"is_remote": True}, Modality.REMOTE),
        ({"is_remote": False, "title": "ML Engineer - Remote Work"}, Modality.REMOTE),
        ({"is_remote": False, "location": "Qualquer lugar"}, Modality.REMOTE),
        ({"is_remote": False, "location": "São Paulo, SP", "description": "Trabalho 100% remoto."}, Modality.REMOTE),
        ({"is_remote": False, "description": "Modelo de trabalho: Remoto"}, Modality.REMOTE),
        ({"is_remote": False, "description": "This is a fully remote role."}, Modality.REMOTE),
        ({"is_remote": False, "description": "Trabalho remoto 2x por semana, modelo híbrido."}, Modality.HYBRID),
        ({"is_remote": False, "description": "Modelo híbrido, 2x por semana."}, Modality.HYBRID),
        ({"is_remote": False, "description": "Trabalho presencial."}, Modality.ONSITE),
        ({"is_remote": None, "description": "Python."}, Modality.UNKNOWN),
    ],
)
def test_detect_modality(overrides: dict[str, object], expected: Modality) -> None:
    assert detect_modality(make_job(**overrides)) is expected


@pytest.mark.parametrize(
    "overrides,kept",
    [
        ({"is_remote": True, "location": "São Paulo, SP"}, True),
        ({"is_remote": False, "location": "Rio de Janeiro, RJ", "description": "Híbrido"}, True),
        ({"is_remote": False, "location": "São Paulo, SP", "description": "Híbrido"}, False),
        ({"is_remote": False, "location": "Rio de Janeiro, RJ", "description": "Python"}, True),
        ({"is_remote": False, "location": "Rio de Janeiro, RJ", "description": "Presencial"}, False),
        ({"is_remote": False, "location": "Barueri, SP", "description": "Python"}, False),
        ({"is_remote": False, "location": None, "description": "Python"}, False),
    ],
)
def test_filter_modality(overrides: dict[str, object], kept: bool) -> None:
    assert (len(filter_modality([make_job(**overrides)], CFG)) == 1) is kept


def test_remote_dropped_when_not_allowed() -> None:
    cfg = CFG.model_copy(update={"modalities": ["hybrid"]})
    assert filter_modality([make_job(is_remote=True)], cfg) == []


def test_onsite_kept_in_city_when_allowed() -> None:
    cfg = CFG.model_copy(update={"modalities": ["remote", "hybrid", "onsite"]})
    job = make_job(is_remote=False, location="Rio de Janeiro, RJ", description="Presencial")
    assert len(filter_modality([job], cfg)) == 1


def test_apply_filters_chain() -> None:
    jobs = [
        make_job(title="AI Engineer", description="PJ"),
        make_job(title="Estágio IA", description="PJ"),
        make_job(title="ML Engineer", is_remote=False, location="Curitiba, PR"),
        make_job(title="Data Scientist", description="CLT"),
    ]
    assert [j.title for j in apply_filters(jobs, CFG)] == ["AI Engineer"]
