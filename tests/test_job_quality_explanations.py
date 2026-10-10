"""Quality evidence is stable and suitable for the authenticated read model."""

from __future__ import annotations

from dataclasses import replace

import pytest

from core.job_quality import (
    QualityAssessment, QualityDisposition, assess_job_quality,
    quality_signal_explanations,
)


@pytest.mark.parametrize("description,code,keyword", [
    (
        "Applicants must pay the $100 equipment deposit before the next call.",
        "candidate_payment_request", "payment",
    ),
    (
        "There is an application fee of $175.",
        "application_fee", "fee",
    ),
    (
        "Your interview will be conducted via Telegram with the recruiter.",
        "off_platform_messaging_interview", "messaging",
    ),
    (
        "Send your SSN to schedule the initial screening.",
        "upfront_sensitive_identity_request", "identity",
    ),
    (
        "All candidates must sign a training repayment agreement.",
        "training_repayment_terms", "repayment",
    ),
])
def test_reviewer_sees_exact_signal_code_and_sanitized_explanation(description, code, keyword):
    quality = assess_job_quality("Software Engineer", description)
    assert quality.requires_review
    assert code in quality.signals
    hints = quality_signal_explanations(quality)
    assert any(keyword in hint.casefold() for hint in hints)
    assert all(description not in hint and "scam" not in hint.casefold() for hint in hints)


def test_deprioritization_is_not_reclassified_as_a_scam():
    quality = assess_job_quality(
        "Software Engineer",
        "End client: confidential. Implement backend components.",
    )
    assert quality.disposition is QualityDisposition.DEPRIORITIZE
    hints = quality_signal_explanations(quality)
    assert any("end client" in hint.casefold() for hint in hints)
    assert not any("scam" in hint.casefold() for hint in hints)


def test_clean_posting_has_no_signal_and_no_claim():
    assessment = assess_job_quality(
        "Software Engineer", "We are building reliable API services."
    )
    assert assessment.disposition is QualityDisposition.PASS
    assert quality_signal_explanations(assessment) == ()


def test_unknown_evidence_code_never_echoes_untrusted_text():
    unknown = "private-email@example.test, $100, bank account"
    assessment = QualityAssessment(
        disposition=QualityDisposition.REVIEW_REQUIRED,
        signals=(unknown,),
    )
    hints = quality_signal_explanations(assessment)
    assert len(hints) == 1
    assert "unrecognized" in hints[0]
    assert unknown not in hints[0]


def test_invalid_type_refused():
    with pytest.raises(TypeError):
        quality_signal_explanations(None)
