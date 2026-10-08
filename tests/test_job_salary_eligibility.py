from core.job_salary_eligibility import SalaryEvidence, SalaryDecision, decide_salary

def test_unknown_salary_is_eligible():
    assert decide_salary(None, 100000) is SalaryDecision.ELIGIBLE_UNKNOWN

def test_known_base_range_below_floor_is_excluded():
    evidence = SalaryEvidence(85000, 95000, 'USD', 'BASE', 'https://example.org/job')
    assert decide_salary(evidence, 100000) is SalaryDecision.EXCLUDED_BELOW_FLOOR

def test_known_base_range_reaching_floor_is_eligible():
    evidence = SalaryEvidence(85000, 105000, 'USD', 'BASE', 'https://example.org/job')
    assert decide_salary(evidence, 100000) is SalaryDecision.ELIGIBLE_KNOWN

def test_total_compensation_is_not_assumed_base():
    evidence = SalaryEvidence(75000, 180000, 'USD', 'TOTAL', 'https://example.org/job')
    assert decide_salary(evidence, 100000) is SalaryDecision.NEEDS_BASE_EVIDENCE

def test_non_usd_not_compared_to_usd_floor():
    evidence = SalaryEvidence(80000, 95000, 'EUR', 'BASE', 'https://example.org/job')
    assert decide_salary(evidence, 100000) is SalaryDecision.NEEDS_BASE_EVIDENCE

def test_unproven_or_invalid_salary_fails_closed():
    import pytest
    with pytest.raises(ValueError):
        SalaryEvidence(120000, 90000, 'USD', 'BASE', 'https://example.org/job')
    with pytest.raises(ValueError):
        SalaryEvidence(50000, 80000, 'USD', 'BASE', '')
