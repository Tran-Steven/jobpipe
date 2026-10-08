import json,sys
from pathlib import Path
from unittest.mock import patch
import jobctl
from tools.ats_review_snapshot import save_snapshot
from tools.ats_verified_answer_bank import save_bank

def test_new_command_registered_and_unsafe_url_rejected(tmp_path):
    args=jobctl.build_parser().parse_args(["ats-capture-review","--url","http://127.0.0.1/","--output",str(tmp_path/"fields.json"),"--bank",str(tmp_path/"bank.json"),"--employer","Example"])
    assert args.command=="ats-capture-review"

def test_capture_review_dispatch_sanitizes_and_never_submits(tmp_path,capsys):
    fields=tmp_path/"fields.json";bank=tmp_path/"bank.json"
    save_bank(bank,[{"question":"Do you use AI?","answer":"SECRET_ANSWER","scope":"employer","employer":"Example","human_verified":True}])
    async def fake_capture(url,path):
        save_snapshot(path,[{"question":"Do you use AI?","type":"radio","label":"Yes","required":True,"value":"NEVER_COPY"},
                            {"question":"Do you use AI?","type":"radio","label":"No","required":True}])
        return {"submission":"not_attempted"}
    argv=["jobctl.py","ats-capture-review","--url","https://jobs.lever.co/example/123/apply","--output",str(fields),"--bank",str(bank),"--employer","Example"]
    with patch.object(sys,"argv",argv),patch("tools.ats_capture_snapshot.capture",side_effect=fake_capture):
        assert jobctl.main()==0
    output=capsys.readouterr().out
    assert "SECRET_ANSWER" not in output and "NEVER_COPY" not in fields.read_text()
    result=json.loads(output)
    assert result["review_item_count"]==1 and result["verified_answer_match_count"]==1
    assert result["human_review"][0]["status"]=="human_review"
    assert result["submission"]=="not_attempted"
