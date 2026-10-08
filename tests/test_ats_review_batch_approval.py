import pytest
from tools.ats_review_batch_approval import approve_batch
from tools.ats_verified_answer_bank import load_bank

ITEMS=[{"id":"q1","question":"Do you use AI?","status":"human_review"},{"id":"q2","question":"Why this company?","status":"human_review"}]
def choices():
    return [{"review_id":"q1","answer":"SENSITIVE_A","scope":"global","human_verified":True},
            {"review_id":"q2","answer":"SENSITIVE_B","scope":"employer","employer":"Example","human_verified":True}]

def test_batch_requires_human_confirmations_and_stores_privately(tmp_path):
    path=tmp_path/"answers.json"
    with pytest.raises(ValueError,match="batch confirmation"):
        approve_batch(path,ITEMS,choices(),human_confirmed=False)
    assert not path.exists()
    result=approve_batch(path,ITEMS,choices(),human_confirmed=True)
    assert result["saved_count"]==2 and result["submission"]=="not_attempted"
    assert "SENSITIVE_A" not in str(result) and "SENSITIVE_B" not in str(result)
    assert len(load_bank(path))==2

def test_invalid_later_answer_prevents_entire_batch_write(tmp_path):
    path=tmp_path/"answers.json";data=choices();data[1]["human_verified"]=False
    with pytest.raises(ValueError,match="each answer"):
        approve_batch(path,ITEMS,data,human_confirmed=True)
    assert not path.exists()

def test_duplicate_scope_cannot_overwrite(tmp_path):
    path=tmp_path/"answers.json";approve_batch(path,ITEMS,choices(),human_confirmed=True)
    with pytest.raises(ValueError,match="duplicate scoped"):
        approve_batch(path,ITEMS,choices(),human_confirmed=True)
    assert len(load_bank(path))==2
