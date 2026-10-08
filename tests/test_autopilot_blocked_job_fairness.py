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

import argparse
from unittest.mock import AsyncMock, patch
import pytest
import jobctl

@pytest.mark.asyncio
async def test_autopilot_forwards_fair_queue_policy_and_disables_submit_by_default():
    args=jobctl.build_parser().parse_args(["autopilot"])
    with patch.object(jobctl,"jobpipe_run_pipeline",new_callable=AsyncMock) as pipeline, \
         patch.object(jobctl,"jobpipe_application_readiness",return_value={"ready":True}), \
         patch.object(jobctl,"cmd_apply_csv",new_callable=AsyncMock) as apply:
        apply.return_value=0
        assert await jobctl.cmd_autopilot(args)==0
        assert apply.await_count==1
        forwarded=apply.await_args.args[0]
        assert forwarded.continue_on_user is True
        assert forwarded.submit is False
        assert forwarded.approve_gate_a is False

@pytest.mark.asyncio
async def test_autopilot_stop_on_user_is_forwarded():
    args=jobctl.build_parser().parse_args(["autopilot","--stop-on-user"])
    with patch.object(jobctl,"jobpipe_run_pipeline",new_callable=AsyncMock), \
         patch.object(jobctl,"jobpipe_application_readiness",return_value={"ready":True}), \
         patch.object(jobctl,"cmd_apply_csv",new_callable=AsyncMock) as apply:
        apply.return_value=0
        assert await jobctl.cmd_autopilot(args)==0
        assert apply.await_args.args[0].continue_on_user is False

@pytest.mark.asyncio
async def test_autopilot_not_ready_never_launches_apply():
    args=jobctl.build_parser().parse_args(["autopilot"])
    with patch.object(jobctl,"jobpipe_run_pipeline",new_callable=AsyncMock), \
         patch.object(jobctl,"jobpipe_application_readiness",return_value={"ready":False}), \
         patch.object(jobctl,"cmd_apply_csv",new_callable=AsyncMock) as apply:
        assert await jobctl.cmd_autopilot(args)==int(jobctl.ExitCode.NEEDS_USER)
        apply.assert_not_awaited()
