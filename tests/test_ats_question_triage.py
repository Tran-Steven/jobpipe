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


@pytest.mark.parametrize("question,key", [
    ("Full name", "full_name"),
    ("Email", "email"),
    ("Phone", "phone"),
    ("LinkedIn", "linkedin"),
    ("GitHub", "github"),
])
@pytest.mark.parametrize("kind", [
    "hidden", "submit", "button", "reset", "number", "date",
    "datetime-local", "time", "color", "range", "search",
    "checkbox", "radio", "select-one", "select-multiple",
    "textarea", "file", "password", "unknown", "", None,
])
def test_unsupported_contact_controls_require_human_review(question, key, kind):
    result = classify_field(
        {"question": question, "label": question, "type": kind,
         "ambiguous": False},
        {key},
    )
    assert result == {"status": "human_review", "reason": "nontrivial_control"}


@pytest.mark.parametrize("question,kind,key", [
    ("Full name", "text", "full_name"),
    ("Email", "email", "email"),
    ("Phone", "tel", "phone"),
    ("LinkedIn", "url", "linkedin"),
    ("GitHub", "url", "github"),
    ("Email ✱", "email", "email"),
])
def test_supported_verified_contact_controls_remain_candidates(question, kind, key):
    result = classify_field(
        {"question": question, "label": question, "type": kind,
         "ambiguous": False},
        {key},
    )
    assert result == {"status": "verified_candidate", "profile_key": key}


def test_supported_contact_without_verified_fact_requires_review():
    result = classify_field(
        {"question": "Email", "label": "Email", "type": "email",
         "ambiguous": False},
        set(),
    )
    assert result == {"status": "human_review", "reason": "unverified_profile_fact"}


def test_ambiguous_verified_contact_still_requires_review():
    result = classify_field(
        {"question": "Email", "label": "Email", "type": "email",
         "ambiguous": True},
        {"email"},
    )
    assert result == {"status": "human_review", "reason": "ambiguous_question"}


def test_non_contact_text_never_becomes_verified_candidate():
    result = classify_field(
        {"question": "Referee email", "label": "Referee email", "type": "email",
         "ambiguous": False},
        {"email"},
    )
    assert result == {"status": "human_review", "reason": "unknown_question"}
