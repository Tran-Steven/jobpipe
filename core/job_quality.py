from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class QualityDisposition(StrEnum):
    PASS = "PASS"
    DEPRIORITIZE = "DEPRIORITIZE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


@dataclass(frozen=True)
class QualityAssessment:
    disposition: QualityDisposition
    signals: tuple[str, ...]

    @property
    def requires_review(self) -> bool:
        return self.disposition is QualityDisposition.REVIEW_REQUIRED


_REVIEW_PATTERNS = (
    (
        "candidate_payment_request",
        re.compile(
            r"\b(?:you|applicants?|candidates?)\s+(?:must|need to|have to|are required to)\s+"
            r"(?:pay|send|transfer|purchase)\b.{0,100}"
            r"\b(?:fee|gift cards?|bitcoin|crypto(?:currency)?|deposit|equipment|training)\b",
            re.I,
        ),
    ),
    (
        "application_fee",
        re.compile(
            r"\b(?:application|registration|training|background.check)\s+"
            r"fee\s*(?:of|:|is)\s*\$\s*\d+",
            re.I,
        ),
    ),
    (
        "off_platform_messaging_interview",
        re.compile(
            r"\b(?:interview|hiring process|recruiter)[\w\s]{0,55}"
            r"\b(?:via|on|through)\s+(?:telegram|whatsapp)\b",
            re.I,
        ),
    ),
    (
        "upfront_sensitive_identity_request",
        re.compile(
            r"\b(?:send|share|provide)\s+(?:your\s+)?"
            r"(?:ssn|social security number|bank account|routing number)"
            r"\b.{0,70}\b(?:before (?:an? )?interview|to schedule|for initial screening)\b",
            re.I,
        ),
    ),
    (
        "training_repayment_terms",
        re.compile(
            r"\b(?:repay(?:ment)?\s+(?:your\s+)?training (?:costs?|fees?)|"
            r"training repayment agreement|training bond)\b",
            re.I,
        ),
    ),
)
_LOW_QUALITY_PATTERNS = (
    (
        "undisclosed_end_client",
        re.compile(
            r"\b(?:end[- ]client|client name)\s*:\s*"
            r"(?:confidential|undisclosed|tbd)\b",
            re.I,
        ),
    ),
    (
        "unusually_high_no_experience_claim",
        re.compile(
            r"\b(?:no experience required|no experience needed)\b.{0,85}"
            r"\$\s*(?:[2-9]\d\d|\d{4,})\s*(?:/|per)\s*(?:hour|hr)\b",
            re.I,
        ),
    ),
)


def assess_job_quality(title: str, description: str) -> QualityAssessment:
    if not isinstance(title, str) or not isinstance(description, str):
        raise TypeError("job title and description must be strings")
    text = f"{title}\n{description}"[:100_000]
    serious = tuple(code for code, pattern in _REVIEW_PATTERNS if pattern.search(text))
    if serious:
        return QualityAssessment(QualityDisposition.REVIEW_REQUIRED, serious)
    low = tuple(code for code, pattern in _LOW_QUALITY_PATTERNS if pattern.search(text))
    if low:
        return QualityAssessment(QualityDisposition.DEPRIORITIZE, low)
    return QualityAssessment(QualityDisposition.PASS, ())


# Evidence codes are deterministic, but pattern matches are not a verdict about
# the employer. Do not output matched posting text, phone/email addresses or a
# categorical accusation in the dashboard. Every label is a review prompt.
_QUALITY_SIGNAL_EXPLANATIONS = {
    "candidate_payment_request": "Review required: posting appears to ask candidates for upfront payment or purchases.",
    "application_fee": "Review required: posting appears to mention an application or registration fee.",
    "off_platform_messaging_interview": "Review required: interview instructions appear to direct applicants to an external messaging app.",
    "upfront_sensitive_identity_request": "Review required: posting appears to request sensitive financial or identity details unusually early.",
    "training_repayment_terms": "Review required: posting appears to include training repayment or bond terms.",
    "undisclosed_end_client": "Lower-priority signal: recruiting intermediary does not identify the end client.",
    "unusually_high_no_experience_claim": "Lower-priority signal: posting advertises unusually high hourly compensation without experience.",
}


def quality_signal_explanations(assessment: QualityAssessment) -> tuple[str, ...]:
    """Stable, sanitized UI explanations for deterministic quality codes.

    Unknown codes fail closed to generic review wording rather than exposing
    raw text or silently discarding a new detection reason.
    """
    if not isinstance(assessment, QualityAssessment):
        raise TypeError("quality assessment required")
    return tuple(
        _QUALITY_SIGNAL_EXPLANATIONS.get(
            code, "Review required: an unrecognized posting quality signal was found."
        )
        for code in assessment.signals
    )
