"""Autopilot fairness: blocked jobs do not starve unrelated jobs by default."""
from jobctl import build_parser

def test_autopilot_continues_past_blocked_jobs_by_default():
    args=build_parser().parse_args(["autopilot"])
    assert args.continue_on_user is True
    assert args.submit is False

def test_autopilot_explicit_stop_on_user():
    args=build_parser().parse_args(["autopilot","--stop-on-user"])
    assert args.continue_on_user is False
    assert args.submit is False

def test_autopilot_explicit_continue():
    args=build_parser().parse_args(["autopilot","--continue-on-user"])
    assert args.continue_on_user is True

def test_standalone_apply_csv_retains_stop_on_user_default():
    args=build_parser().parse_args(["apply-csv"])
    assert args.continue_on_user is False
    assert args.submit is False
