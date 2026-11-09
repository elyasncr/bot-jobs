import pytest
from pydantic import ValidationError

from vagas_bot.models import LLMScoreOutput, PJStatus
from vagas_bot.text import make_fingerprint, normalize_text


def _score(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "technical": 80,
        "seniority": 70,
        "domain": 60,
        "modality_contract": 100,
        "language": 90,
        "pj_status": "pj",
        "strengths": ["LLMs"],
        "gaps": [],
        "summary": "Boa vaga.",
    }
    return base | overrides


def test_normalize_text() -> None:
    assert normalize_text("  Engenheiro de   Inteligência  ARTIFICIAL ") == "engenheiro de inteligencia artificial"


def test_fingerprint_ignores_case_accents_and_spacing() -> None:
    assert make_fingerprint("Engenheiro de IA", "Ação Ltda") == make_fingerprint("engenheiro  de ia", "ACAO LTDA")
    assert make_fingerprint("Engenheiro de IA", "Empresa A") != make_fingerprint("Engenheiro de IA", "Empresa B")


def test_llm_output_valid() -> None:
    out = LLMScoreOutput.model_validate(_score())
    assert out.pj_status is PJStatus.PJ


@pytest.mark.parametrize("field,value", [("technical", 101), ("language", -1)])
def test_llm_output_rejects_out_of_range(field: str, value: int) -> None:
    with pytest.raises(ValidationError):
        LLMScoreOutput.model_validate(_score(**{field: value}))


def test_llm_output_max_three_strengths() -> None:
    with pytest.raises(ValidationError):
        LLMScoreOutput.model_validate(_score(strengths=["a", "b", "c", "d"]))


def test_json_schema_has_enum_for_pj_status() -> None:
    schema = LLMScoreOutput.model_json_schema()
    assert schema["$defs"]["PJStatus"]["enum"] == ["pj", "both", "clt", "uncertain"]
