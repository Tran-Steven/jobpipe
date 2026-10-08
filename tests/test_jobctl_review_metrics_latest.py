"""Review arrival excludes superseded/invalidated run states."""
from types import SimpleNamespace
from jobctl import _event_metrics

def event(run_id,status,adapter="greenhouse"):
    return SimpleNamespace(event_type="RUN_STATE_CHANGED",payload={
        "outcome":{"run_id":run_id,"adapter":adapter,"status":status}
    })

def test_invalidated_review_not_counted():
    result=_event_metrics([
        event("a","REVIEW_READY"),event("a","NEEDS_USER"),
        event("b","REVIEW_READY"),event("c","FAILED"),
    ])["supported_ats_review_arrival"]
    assert result=={"reached":1,"runs":3,"rate":1/3}

def test_latest_review_and_verified_submission_counted_once():
    result=_event_metrics([
        event("a","REVIEW_READY"),event("a","SUBMITTED_VERIFIED"),
        event("b","REVIEW_READY"),event("b","REVIEW_READY"),
    ])["supported_ats_review_arrival"]
    assert result=={"reached":2,"runs":2,"rate":1.0}

def test_no_supported_runs():
    result=_event_metrics([event("x","REVIEW_READY","unknown")])["supported_ats_review_arrival"]
    assert result=={"reached":0,"runs":0,"rate":None}
