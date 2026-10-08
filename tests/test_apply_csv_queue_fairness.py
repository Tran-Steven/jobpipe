"""Real apply-csv loop must process subsequent jobs after blocked materials."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch,MagicMock
import pytest
import jobctl

class DummyPlaywright:
    async def __aenter__(self): return object()
    async def __aexit__(self,*args): return False

@pytest.mark.asyncio
@pytest.mark.parametrize("continue_on_user,expected_count",[(True,2),(False,1)])
async def test_apply_csv_material_block_does_not_starve_queue(
    tmp_path, capsys, continue_on_user, expected_count
):
    args=jobctl.build_parser().parse_args(
        ["--home",str(tmp_path),"apply-csv","--csv",str(tmp_path/"queue.csv")]
        +(["--continue-on-user"] if continue_on_user else [])
    )
    rows=[SimpleNamespace(row={"status":"Pending"}) for _ in range(2)]
    paths=SimpleNamespace(job_queue=tmp_path/"queue.csv",master_documents=tmp_path)
    vault=SimpleNamespace(paths=paths,application_profile=lambda: {},policy={})
    engine=MagicMock()
    outcome=SimpleNamespace(
        status=jobctl.OutcomeStatus.NEEDS_USER,
        exit_code=jobctl.ExitCode.NEEDS_USER,
        to_json=lambda:'{"status":"NEEDS_USER"}',
    )
    job=SimpleNamespace(job_id="1",company="Fixture",title="Engineer",
                        tier=SimpleNamespace(value="low"))
    with patch.object(jobctl.CandidateVault,"load",return_value=vault), \
         patch.object(jobctl,"load_csv_queue",return_value=rows), \
         patch.object(jobctl,"MacOSSecurityCredentialStore",return_value=object()), \
         patch.object(jobctl.JobApplicationEngine,"from_private_home",return_value=engine), \
         patch.object(jobctl,"_mailbox_verifier",return_value=None), \
         patch.object(jobctl,"_build_application_bundle",side_effect=FileNotFoundError("missing fixture resume")) as build, \
         patch.object(jobctl,"_materials_required_outcome",return_value=(outcome,job)), \
         patch.object(jobctl,"_project_csv_outcome") as project, \
         patch.object(jobctl,"async_playwright",return_value=DummyPlaywright()):
        rc=await jobctl.cmd_apply_csv(args)
    assert rc==int(jobctl.ExitCode.NEEDS_USER)
    assert build.call_count==expected_count
    assert project.call_count==expected_count
    assert engine.record_outcome.call_count==expected_count
    assert capsys.readouterr().out.count('"status":"NEEDS_USER"')==expected_count

@pytest.mark.asyncio
async def test_blocked_material_followed_by_review_ready_is_not_starved(tmp_path,capsys):
    from unittest.mock import AsyncMock
    args=jobctl.build_parser().parse_args([
        "--home",str(tmp_path),"apply-csv","--csv",str(tmp_path/"jobs.csv"),"--continue-on-user"
    ])
    rows=[SimpleNamespace(row={"status":"Pending","source":"greenhouse"}),
          SimpleNamespace(row={"status":"Pending","source":"greenhouse"})]
    paths=SimpleNamespace(job_queue=tmp_path/"jobs.csv",master_documents=tmp_path)
    vault=SimpleNamespace(paths=paths,application_profile=lambda: {},policy={})
    blocked=SimpleNamespace(status=jobctl.OutcomeStatus.NEEDS_USER,
       exit_code=jobctl.ExitCode.NEEDS_USER,to_json=lambda:'{"status":"NEEDS_USER"}')
    ready=SimpleNamespace(status=jobctl.OutcomeStatus.REVIEW_READY,
       exit_code=jobctl.ExitCode.AWAITING_GATE_B,to_json=lambda:'{"status":"REVIEW_READY"}')
    job=SimpleNamespace(job_id="1",company="Fixture",title="Engineer",
        tier=SimpleNamespace(value="low"))
    bundle=SimpleNamespace(policy=SimpleNamespace(blockers=["approval needed"],
       gate_a_actor=jobctl.ApprovalActor.HUMAN))
    engine=MagicMock()
    engine.submission_preflight.return_value=None
    engine.execute=AsyncMock(return_value=ready)
    def make_bundle(*,application,**kwargs):
        if application is rows[0]: raise FileNotFoundError("fixture missing")
        return bundle,{}
    with patch.object(jobctl.CandidateVault,"load",return_value=vault), \
         patch.object(jobctl,"load_csv_queue",return_value=rows), \
         patch.object(jobctl,"MacOSSecurityCredentialStore",return_value=object()), \
         patch.object(jobctl.JobApplicationEngine,"from_private_home",return_value=engine), \
         patch.object(jobctl,"_mailbox_verifier",return_value=None), \
         patch.object(jobctl,"_build_application_bundle",side_effect=make_bundle), \
         patch.object(jobctl,"_materials_required_outcome",return_value=(blocked,job)), \
         patch.object(jobctl,"_project_csv_outcome") as project, \
         patch.object(jobctl,"async_playwright",return_value=DummyPlaywright()):
        rc=await jobctl.cmd_apply_csv(args)
    assert rc==int(max(blocked.exit_code,ready.exit_code))
    assert engine.execute.await_count==1
    assert engine.execute.await_args.kwargs["request_submit"] is False
    assert project.call_count==2
    output=capsys.readouterr().out
    assert '"status":"NEEDS_USER"' in output and '"status":"REVIEW_READY"' in output
