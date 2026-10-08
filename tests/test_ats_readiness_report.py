"""No fixture proof can be interpreted as live application readiness."""
from tools.ats_readiness_report import assess

def test_verified_fixture_never_claims_live_review():
    x=assess(0,"13 passed\nATS_FIXTURE_REVIEW_GATE=PASS; LIVE_REVIEW=NOT_VERIFIED; SUBMISSIONS=NOT_ATTEMPTED")
    assert x["fixture_review"]=="passed"
    assert x["live_review"]=="not_verified"
    assert x["real_submissions"]=="not_attempted"

def test_no_marker_fails_closed():
    assert assess(0,"13 passed")["fixture_review"]=="failed"

def test_nonzero_exit_fails_closed_even_with_marker():
    assert assess(1,"ATS_FIXTURE_REVIEW_GATE=PASS")["fixture_review"]=="failed"

def test_prefix_spoof_is_rejected():
    assert assess(0,"noise ATS_FIXTURE_REVIEW_GATE=PASS")["fixture_review"]=="failed"
