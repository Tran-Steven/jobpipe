"""Deterministic salary evidence decision. Not yet wired to job admission.

Never infer base pay from total compensation or missing listings.
"""
from dataclasses import dataclass
from enum import Enum
from math import isfinite


class SalaryDecision(str, Enum):
    ELIGIBLE_UNKNOWN = 'ELIGIBLE_UNKNOWN'
    ELIGIBLE_KNOWN = 'ELIGIBLE_KNOWN'
    EXCLUDED_BELOW_FLOOR = 'EXCLUDED_BELOW_FLOOR'
    NEEDS_BASE_EVIDENCE = 'NEEDS_BASE_EVIDENCE'


@dataclass(frozen=True, slots=True)
class SalaryEvidence:
    minimum: float
    maximum: float
    currency: str
    pay_kind: str
    source_url: str
    pay_period: str = 'ANNUAL'

    def __post_init__(self):
        if (isinstance(self.minimum, bool) or isinstance(self.maximum, bool)
                or not all(isinstance(v, (int, float)) and isfinite(v) and v >= 0
                           for v in (self.minimum, self.maximum))
                or self.maximum < self.minimum):
            raise ValueError('invalid salary range')
        if self.currency not in ('USD', 'EUR', 'GBP', 'CAD', 'OTHER'):
            raise ValueError('unknown currency')
        if self.pay_kind not in ('BASE', 'TOTAL', 'BONUS', 'EQUITY', 'UNKNOWN'):
            raise ValueError('unknown pay kind')
        if self.pay_period not in ('ANNUAL', 'HOURLY', 'MONTHLY', 'WEEKLY', 'UNKNOWN'):
            raise ValueError('unknown pay period')
        if not isinstance(self.source_url, str) or not self.source_url.startswith(('https://', 'http://')):
            raise ValueError('salary provenance URL required')


def decide_salary(evidence: SalaryEvidence | None, usd_annual_base_floor: float) -> SalaryDecision:
    if isinstance(usd_annual_base_floor, bool) or not isinstance(usd_annual_base_floor, (int, float)) or not isfinite(usd_annual_base_floor) or usd_annual_base_floor < 0:
        raise ValueError('invalid annual USD base floor')
    if evidence is None:
        return SalaryDecision.ELIGIBLE_UNKNOWN
    if evidence.currency != 'USD' or evidence.pay_kind != 'BASE' or evidence.pay_period != 'ANNUAL':
        return SalaryDecision.NEEDS_BASE_EVIDENCE
    if evidence.maximum < usd_annual_base_floor:
        return SalaryDecision.EXCLUDED_BELOW_FLOOR
    return SalaryDecision.ELIGIBLE_KNOWN
