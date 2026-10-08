import pytest
from tools.ats_review_approval import approve_answer
from tools.ats_verified_answer_bank import load_bank

def test_human_confirmation_required_and_answer_not_returned(tmp_path):
    path=tmp_path/"bank.json";items=[{"id":"q1","status":"human_review","question":"Do you use AI in your role?"}]
    kwargs=dict(review_id="q1",answer="SYNTHETIC_SECRET",scope="employer",employer="Example")
    with pytest.raises(ValueError,match="confirmation"):
        approve_answer(path,items,human_confirmed=False,**kwargs)
    assert not path.exists()
    result=approve_answer(path,items,human_confirmed=True,**kwargs)
    assert result["saved"] and result["submission"]=="not_attempted"
    assert "SYNTHETIC_SECRET" not in str(result)
    records=load_bank(path)
    assert records[0]["answer"]=="SYNTHETIC_SECRET"
    with pytest.raises(ValueError,match="already exists"):
        approve_answer(path,items,human_confirmed=True,**kwargs)

def test_unknown_id_and_scope_rejected(tmp_path):
    path=tmp_path/"bank.json";items=[{"id":"q1","status":"human_review","question":"Q"}]
    with pytest.raises(ValueError,match="uniquely"):
        approve_answer(path,items,review_id="bad",answer="A",scope="global",employer="",human_confirmed=True)
    with pytest.raises(ValueError,match="scope"):
        approve_answer(path,items,review_id="q1",answer="A",scope="automatic",employer="",human_confirmed=True)
    assert not path.exists()

def test_employer_scope_isolated(tmp_path):
    path=tmp_path/"bank.json";items=[{"id":"q1","status":"human_review","question":"Q"}]
    approve_answer(path,items,review_id="q1",answer="A",scope="employer",employer="Employer One",human_confirmed=True)
    approve_answer(path,items,review_id="q1",answer="B",scope="employer",employer="Employer Two",human_confirmed=True)
    assert len(load_bank(path))==2
