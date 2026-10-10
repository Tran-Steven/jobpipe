from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.company_filters import CompanyTreatment
from core.company_preferences import (
    CompanyPreferences,
    PrivateCompanyPreferences,
    effective_company_treatment,
)
from core.job_quality import QualityDisposition, assess_job_quality
from core.private_home import PrivateHome


def test_company_blacklist_is_disabled_by_default() -> None:
    disabled = CompanyPreferences()
    assert effective_company_treatment("Jobgether", preferences=disabled) is CompanyTreatment.ALLOW
    assert effective_company_treatment(
        "Example Agency",
        additional_blocked=["Example Agency"],
        preferences=disabled,
    ) is CompanyTreatment.ALLOW


def test_custom_allowlist_overrides_built_in_and_custom_blocklist() -> None:
    prefs = CompanyPreferences(
        enabled=True,
        blocked=("Example Agency",),
        allowed=("Jobgether",),
    )
    assert effective_company_treatment("jobGETHER", preferences=prefs) is CompanyTreatment.ALLOW
    assert effective_company_treatment("Example Agency", preferences=prefs) is CompanyTreatment.BLOCK
    assert effective_company_treatment("TCS", preferences=prefs) is CompanyTreatment.BLOCK
    assert effective_company_treatment(
        "Synthetic Inc",
        additional_blocked=["Synthetic Inc"],
        preferences=prefs,
    ) is CompanyTreatment.BLOCK
    assert effective_company_treatment(
        "Example Company",
        preferences=CompanyPreferences(enabled=True, builtin_enabled=False),
    ) is CompanyTreatment.ALLOW
    assert effective_company_treatment(
        "TCS",
        preferences=CompanyPreferences(enabled=True, builtin_enabled=False),
    ) is CompanyTreatment.ALLOW


def test_private_company_preferences_can_toggle_edit_and_reload(tmp_path: Path) -> None:
    home = PrivateHome(tmp_path / "private")
    store = PrivateCompanyPreferences(home)
    assert not store.read().enabled
    store.set_enabled(True)
    store.edit("block", "Example Agency")
    store.edit("allow", "Jobgether")
    loaded = PrivateCompanyPreferences(home).read()
    assert loaded.enabled
    assert loaded.blocked == ("Example Agency",)
    assert loaded.allowed == ("Jobgether",)
    assert store.path.stat().st_mode & 0o077 == 0
    assert json.loads(store.path.read_text(encoding="utf-8"))["schema_version"] == 1
    store.edit("clear", "Example Agency")
    assert store.read().blocked == ()
    assert store.read().allowed == ("Jobgether",)
    store.set_builtin_enabled(False)
    assert not store.read().builtin_enabled
    store.set_enabled(False)
    assert not store.read().enabled


def test_private_store_rejects_ambiguous_settings(tmp_path: Path) -> None:
    home = PrivateHome(tmp_path / "private")
    with pytest.raises(ValueError, match="both blocked and allowed"):
        CompanyPreferences(
            enabled=True, blocked=("Example, Inc.",), allowed=("example inc",)
        )
    with pytest.raises(ValueError, match="booleans"):
        CompanyPreferences(enabled="yes")
    store = PrivateCompanyPreferences(home)
    with pytest.raises(ValueError, match="empty"):
        store.edit("block", " ")
    home.ensure()
    store.path.write_text('{"enabled":true}', encoding="utf-8")
    with pytest.raises(ValueError, match="schema"):
        store.read()


def test_company_filter_cli_subcommands_are_explicit() -> None:
    import jobctl

    for action in ("enable", "disable", "builtin-on", "builtin-off", "list", "block", "allow", "clear"):
        args = jobctl.build_parser().parse_args(
            ["company-filters", action, "Example Agency"]
        )
        assert args.action == action


def test_quality_signals_require_manual_review_for_specific_patterns() -> None:
    for text, signal in (
        ("Candidates must pay a $250 application fee to get hired.", "candidate_payment_request"),
        ("Application fee: $150 is due on registration.", "application_fee"),
        ("Your interview will be conducted via Telegram.", "off_platform_messaging_interview"),
        ("Provide your social security number before interview.", "upfront_sensitive_identity_request"),
        ("You will sign a training repayment agreement.", "training_repayment_terms"),
    ):
        result = assess_job_quality("Software Engineer", text)
        assert result.disposition is QualityDisposition.REVIEW_REQUIRED
        assert signal in result.signals


def test_vague_or_suspicious_listing_is_lower_priority_without_fraud_verdict() -> None:
    result = assess_job_quality(
        "Backend Engineer", "End-client: Confidential. Working with distributed systems."
    )
    assert result.disposition is QualityDisposition.DEPRIORITIZE
    assert result.signals == ("undisclosed_end_client",)
    assert assess_job_quality(
        "Software Engineer",
        "We never require payment for applications. Interview conducted by our hiring team.",
    ).disposition is QualityDisposition.PASS
    assert assess_job_quality("Backend Engineer", "").disposition is QualityDisposition.PASS
