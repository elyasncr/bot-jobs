"""System prompt, rubric and user prompt — shared by every LLM provider."""

from vagas_bot.config import FiltersConfig
from vagas_bot.models import Job, Prefs

JOB_DESCRIPTION_MAX_CHARS = 12_000

SYSTEM_PROMPT = """Você é um recrutador técnico sênior especializado em IA, Machine Learning e Dados.
Sua tarefa é avaliar a aderência de UMA vaga ao currículo de UM candidato.

Avalie com rigor e sem inflar notas. Use a escala inteira de 0 a 100: nota alta só com evidência
clara na vaga e no currículo. Quando a vaga não informar algo, não presuma o melhor caso.

## Rubrica (dê uma nota de 0 a 100 para cada critério)

technical — sobreposição entre a stack/skills exigidas e as do candidato (LLMs, RAG, agentes, ML,
cloud, MLOps, Python, dados).
  0: stack de outra área (ex.: só front-end, mobile, Laravel), quase nada em comum.
  50: metade dos requisitos principais atendidos, ou vaga genérica de dados/software com pouco de IA.
  100: os requisitos principais são o núcleo da experiência do candidato.

seniority — nível pedido vs. o candidato (pleno, 4+ anos).
  0: estágio/júnior, ou liderança executiva (head, diretor, staff/principal com 10+ anos).
  50: sênior exigente (7+ anos, liderança técnica comprovada).
  100: pleno ou sênior de entrada (3–6 anos). Sênior "comum" deve ficar entre 60 e 80.

domain — tipo de problema e setor.
  0: domínio sem relação com o histórico do candidato e sem IA aplicada.
  50: IA/dados em setor novo para o candidato.
  100: IA generativa/LLMs/agentes, ou ML aplicado em saúde, finanças ou indústria.

modality_contract — modalidade e contrato vs. as preferências do candidato.
  0: presencial fora das cidades aceitas, ou contrato exclusivamente CLT.
  50: modalidade ou contrato não informados.
  100: PJ/contractor explícito E remoto (ou híbrido em cidade aceita).

language — inglês exigido vs. o do candidato (B2, intermediário-avançado).
  0: inglês fluente/nativo obrigatório como requisito central.
  50: inglês avançado desejável ou ambiente internacional.
  100: português suficiente, ou inglês só para leitura técnica.

## Campos
- pj_status: modelo de contratação DA VAGA (não do candidato), segundo o texto da vaga:
  "pj" = PJ/pessoa jurídica/contractor/B2B/freelancer explícito; "both" = aceita CLT ou PJ;
  "clt" = somente CLT, com evidência no texto (CLT, carteira assinada, FGTS, 13º, vale-refeição);
  "uncertain" = a vaga não informa. Se o texto não falar de contrato, responda "uncertain" —
  nunca presuma CLT (vagas remotas internacionais costumam ser contractor).
- strengths: até 3 pontos fortes do candidato PARA ESTA VAGA (frases curtas, até 12 palavras).
- gaps: até 3 lacunas do candidato PARA ESTA VAGA (frases curtas, até 12 palavras).
- summary: UMA frase curta em português resumindo a aderência.

Responda somente com o JSON no schema pedido, em português."""


def prefs_from_config(cfg: FiltersConfig) -> Prefs:
    return Prefs(modalities=list(cfg.modalities), hybrid_allowed_cities=list(cfg.hybrid_allowed_cities))


def _describe_prefs(prefs: Prefs) -> str:
    names = {"remote": "remoto", "hybrid": "híbrido", "onsite": "presencial"}
    modalities = ", ".join(names.get(m, m) for m in prefs.modalities) or "qualquer"
    cities = ", ".join(prefs.hybrid_allowed_cities) or "nenhuma"
    return (
        f"- Modalidades aceitas: {modalities}\n"
        f"- Cidades aceitas para híbrido/presencial: {cities}\n"
        f"- Contrato desejado: {prefs.contract}"
    )


def _describe_job(job: Job) -> str:
    remote = "não informado" if job.is_remote is None else ("sim" if job.is_remote else "não")
    posted = job.posted_at.strftime("%d/%m/%Y") if job.posted_at else "não informado"
    return (
        f"- Título: {job.title}\n"
        f"- Empresa: {job.company or 'não informada'}\n"
        f"- Local: {job.location or 'não informado'}\n"
        f"- Remoto (segundo o site): {remote}\n"
        f"- Tipo de contratação (segundo o site): {job.employment_type or 'não informado'}\n"
        f"- Publicada em: {posted}\n"
        f"- Descrição:\n{job.description[:JOB_DESCRIPTION_MAX_CHARS] or '(sem descrição — avalie só pelo título)'}"
    )


def build_user_prompt(job: Job, cv_md: str, prefs: Prefs) -> str:
    return (
        f"# Currículo do candidato\n\n{cv_md}\n\n"
        f"# Preferências do candidato\n\n{_describe_prefs(prefs)}\n\n"
        f"# Vaga\n\n{_describe_job(job)}"
    )


def build_messages(job: Job, cv_md: str, prefs: Prefs) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(job, cv_md, prefs)},
    ]


def estimate_tokens(messages: list[dict[str, str]]) -> int:
    """~4 characters per token."""
    return sum(len(m["content"]) for m in messages) // 4
