import json
from pathlib import Path
from tools.ats_review_cli import main
from tools.ats_verified_answer_bank import save_bank

def test_cli_outputs_deduplicated_human_review_without_answers(tmp_path:Path,capsys):
    fields=[{"question":"Do you use AI in your role?","label":"Yes","type":"radio","required":True},
            {"question":"Do you use AI in your role?","label":"No","type":"radio","required":True},
            {"question":"Full name ✱","label":"Full name ✱","type":"text","required":True}]
    f=tmp_path/"fields.json"
    f.write_text(json.dumps(fields))
    b=tmp_path/"answers.json"
    save_bank(b,[{"question":"Do you use AI in your role?","answer":"PRIVATE_NEVER_PRINT","scope":"employer","employer":"Ethena","human_verified":True}])
    assert main(["--fields",str(f),"--bank",str(b),"--employer","Ethena","--verified-profile-keys","full_name"])==0
    output=capsys.readouterr().out
    result=json.loads(output)
    assert "PRIVATE_NEVER_PRINT" not in output
    assert result["review_item_count"]==1
    assert result["verified_answer_match_count"]==1
    assert result["human_review"][0]["status"]=="human_review"
    assert result["submission"]=="not_attempted"

def test_cli_wrong_employer_no_scoped_match(tmp_path:Path,capsys):
    f=tmp_path/"fields.json"
    f.write_text(json.dumps([{"question":"Q","type":"textarea","required":True}]))
    b=tmp_path/"answers.json"
    save_bank(b,[{"question":"Q","answer":"secret","scope":"employer","employer":"Ethena","human_verified":True}])
    assert main(["--fields",str(f),"--bank",str(b),"--employer","Other"])==0
    result=json.loads(capsys.readouterr().out)
    assert result["verified_answer_match_count"]==0
    assert result["human_review"][0]["required"]
