from pathlib import Path
import os
import pytest
from tools.ats_verified_answer_bank import lookup_answer,load_bank,save_bank

def test_only_verified_and_exact_scoped_answers():
    records=[
      {"question":"Do you use AI in your role?","answer":"Yes","scope":"employer","employer":"Ethena","human_verified":True},
      {"question":"Will you require sponsorship?","answer":"No","scope":"global","human_verified":False},
      {"question":"Name pronunciation","answer":"Example","scope":"global","human_verified":True}]
    assert lookup_answer(records,"Do you use AI in your role?","Ethena")["answer"]=="Yes"
    assert lookup_answer(records,"Do you use AI in your role?","Other") is None
    assert lookup_answer(records,"Will you require sponsorship?","Other") is None
    assert lookup_answer(records,"Do you use AI?","Ethena") is None
    assert lookup_answer(records,"Name pronunciation","Other")["scope"]=="global"

def test_private_persistent_file_and_no_values_in_lookup_miss(tmp_path:Path):
    path=tmp_path/"private"/"answers.json"
    records=[{"question":"Consent to AI interview policy?","answer":"Example private answer","scope":"employer","employer":"X","human_verified":True}]
    save_bank(path,records)
    assert os.stat(path).st_mode & 0o777==0o600
    assert load_bank(path)==records
    assert lookup_answer(load_bank(path),"Consent to AI interview policy?","Y") is None

def test_unverified_and_invalid_scope_fail_closed():
    assert lookup_answer([{"question":"Q","answer":"A","scope":"unknown","human_verified":True}],"Q","X") is None
    assert lookup_answer([{"question":"Q","answer":"A","scope":"global","human_verified":False}],"Q","X") is None
