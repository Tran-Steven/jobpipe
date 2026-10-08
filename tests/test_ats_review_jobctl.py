"""CLI review dispatcher remains no-submit and redacts cached answers."""
import json
from pathlib import Path
import sys
from unittest.mock import patch
from tools.ats_verified_answer_bank import save_bank
import jobctl

def test_parser_exposes_offline_review_queue():
    args=jobctl.build_parser().parse_args(["ats-review-queue","--fields","fields.json","--bank","bank.json","--employer","Example"])
    assert args.command=="ats-review-queue"
    assert args.employer=="Example"

def test_jobctl_dispatches_readonly_review_without_values(tmp_path:Path,capsys):
    f=tmp_path/"fields.json";b=tmp_path/"bank.json"
    f.write_text(json.dumps([{"question":"Do you use AI?","type":"radio","required":True}]))
    save_bank(b,[{"question":"Do you use AI?","answer":"SYNTHETIC_PRIVATE_ANSWER","scope":"employer","employer":"Example","human_verified":True}])
    argv=["jobctl.py","ats-review-queue","--fields",str(f),"--bank",str(b),"--employer","Example"]
    with patch.object(sys,"argv",argv):
        assert jobctl.main()==0
    output=capsys.readouterr().out
    assert "SYNTHETIC_PRIVATE_ANSWER" not in output
    data=json.loads(output)
    assert data["verified_answer_match_count"]==1
    assert data["human_review"][0]["status"]=="human_review"
    assert data["submission"]=="not_attempted"
