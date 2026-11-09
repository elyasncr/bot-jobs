from helpers import make_job

from vagas_bot.filters import dedupe


def test_same_job_in_two_publishers_keeps_linkedin() -> None:
    indeed = make_job(id="a", publisher="Indeed", description="x" * 500)
    linkedin = make_job(id="b", publisher="LinkedIn", description="curta")
    assert [j.id for j in dedupe([indeed, linkedin], seen=[])] == ["b"]


def test_same_job_without_linkedin_keeps_longest_description() -> None:
    short = make_job(id="a", publisher="Indeed", description="curta")
    long = make_job(id="b", publisher="Glassdoor", description="bem mais longa")
    assert [j.id for j in dedupe([short, long], seen=[])] == ["b"]


def test_same_fingerprint_ignores_case_and_accents() -> None:
    a = make_job(id="a", title="Engenheiro de IA", company="Ação", publisher="Indeed")
    b = make_job(id="b", title="engenheiro de ia", company="ACAO", publisher="LinkedIn")
    assert [j.id for j in dedupe([a, b], seen=[])] == ["b"]


def test_already_seen_by_id() -> None:
    job = make_job(id="seen-id")
    assert dedupe([job], seen={"seen-id": "2026-11-01"}) == []


def test_already_seen_by_fingerprint() -> None:
    job = make_job(id="new-id")
    assert dedupe([job], seen={job.fingerprint: "2026-11-01"}) == []


def test_different_jobs_keep_order() -> None:
    jobs = [make_job(title="A"), make_job(title="B"), make_job(title="C")]
    assert [j.title for j in dedupe(jobs, seen=[])] == ["A", "B", "C"]
