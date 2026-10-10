from __future__ import annotations

from core.company_filters import CompanyTreatment, company_treatment, normalize_company_name
from jobpipe_discovery import _score_job
from utils.discovery import Job, filter_company_jobs


def test_company_registry_uses_exact_normalized_names() -> None:
    assert company_treatment("  Synergistic-IT ") is CompanyTreatment.BLOCK
    assert company_treatment("TCS") is CompanyTreatment.BLOCK
    assert company_treatment("Tata Consultancy Services, Limited") is CompanyTreatment.BLOCK
    assert company_treatment("jobGETHER") is CompanyTreatment.BLOCK
    assert company_treatment("TCSystems") is CompanyTreatment.ALLOW
    assert normalize_company_name("  Synergistic-IT ") == "synergistic it"


def test_watchlist_is_not_an_automatic_company_block() -> None:
    assert company_treatment("Wipro") is CompanyTreatment.DEPRIORITIZE
    assert company_treatment("Revature") is CompanyTreatment.DEPRIORITIZE
    assert company_treatment("Insight Global") is CompanyTreatment.REVIEW
    assert company_treatment("Example Good Company") is CompanyTreatment.ALLOW


def test_user_profile_can_add_explicit_blocks_without_substring_collisions() -> None:
    blocked = ["Example, Inc."]
    assert company_treatment("example inc", additional_blocked=blocked) is CompanyTreatment.BLOCK
    assert company_treatment("example incorporated", additional_blocked=blocked) is CompanyTreatment.ALLOW


def test_legacy_discovery_filters_exclusions_before_limit() -> None:
    jobs = [
        Job("1", "Engineer", "TCS", "LA", "https://example.org/1", "https://example.org/1"),
        Job("2", "Engineer", "Apex Systems", "LA", "https://example.org/2", "https://example.org/2"),
        Job("3", "Engineer", "Example Inc", "LA", "https://example.org/3", "https://example.org/3"),
    ]
    profile = {"preferences": {"exclude_companies": ["Example Inc"]}}
    assert [job.company for job in filter_company_jobs(jobs, profile)] == ["Apex Systems"]


def test_triage_excludes_blocked_and_deprioritizes_watchlisted_companies() -> None:
    profile = {"preferences": {"roles": ["Software Engineer"], "keywords": [], "years_experience": 2}}
    def job(company: str) -> dict[str, str]:
        return {
            "title": "Software Engineer",
            "company": company,
            "location": "Los Angeles, CA",
            "description": "Build internal services.",
        }

    blocked, block_reasons = _score_job(job("SynergisticIT"), profile)
    regular, _ = _score_job(job("Synthetic Company"), profile)
    lower, lower_reasons = _score_job(job("Wipro"), profile)
    assert blocked == 0
    assert "company blocked by preference" in block_reasons
    assert lower == regular - 30
    assert "company deprioritized by preference" in lower_reasons
