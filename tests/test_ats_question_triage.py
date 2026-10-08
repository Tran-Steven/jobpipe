import pytest
from tools.ats_question_triage import classify_field,triage_fields

@pytest.mark.parametrize("question,kind",[
    ("Will you require sponsorship?","radio"),
    ("Do you use AI in your role?","radio"),
    ("Why are you interested in joining Ethena?","textarea"),
    ("I acknowledge that I have read the employer AI policy.","checkbox"),
    ("Which location are you based in?","select-one"),
    ("Resume/CV","file"),
    ("Current company name","text"),
    ("Full name of referee","text"),
])
def test_unknown_or_sensitive_never_autofills(question,kind):
    out=classify_field({"question":question,"label":"","type":kind,"ambiguous":False,"required":True},{"full_name","email","phone"})
    assert out["status"]=="human_review"

def test_only_exact_verified_contact_field_is_candidate():
    fields=[{"question":"Full name ✱","label":"Full name ✱","type":"text","ambiguous":False},
            {"question":"Email ✱","label":"Email ✱","type":"email","ambiguous":False},
            {"question":"Email ✱","label":"Email ✱","type":"email","ambiguous":True},
            {"question":"Phone ✱","label":"Phone ✱","type":"text","ambiguous":False}]
    out=triage_fields(fields,{"full_name","email"})
    assert [x["status"] for x in out]==["verified_candidate","verified_candidate","human_review","human_review"]
    assert out[0]["profile_key"]=="full_name"
    assert out[3]["reason"]=="unverified_profile_fact"

def test_yes_no_label_not_treated_as_question():
    assert classify_field({"label":"Yes","type":"radio","ambiguous":True},{"full_name"})["status"]=="human_review"
