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
