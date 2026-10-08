import json,os
import pytest
from tools.ats_review_snapshot import sanitized_fields,save_snapshot

def test_allowlist_excludes_candidate_values(tmp_path):
    fields=[{"question":"Sponsorship?","label":"Yes","type":"radio","required":True,
             "value":"SENSITIVE_ANSWER","name":"email","placeholder":"PRIVATE_EMAIL",
             "dom_id":"SECRET","ambiguous":False}]
    out=sanitized_fields(fields)
    assert len(out)==1 and out[0]["question"]=="Sponsorship?"
    assert set(out[0])=={"type","question","label","required","ambiguous"}
    assert "SENSITIVE_ANSWER" not in str(out) and "PRIVATE_EMAIL" not in str(out)
    target=tmp_path/"private"/"fields.json"
    save_snapshot(target,fields)
    assert json.loads(target.read_text())==out
    assert os.stat(target).st_mode & 0o777==0o600

def test_snapshot_cannot_overwrite_symlink(tmp_path):
    secret=tmp_path/"secret";secret.write_text("intact")
    link=tmp_path/"link";link.symlink_to(secret)
    with pytest.raises(ValueError,match="unsafe"):save_snapshot(link,[])
    assert secret.read_text()=="intact"

def test_multiple_control_question_stays_separate_metadata():
    fields=[{"question":"Question?","label":"Yes","type":"radio","required":True},
            {"question":"Question?","label":"No","type":"radio","required":True}]
    assert len(sanitized_fields(fields))==2
