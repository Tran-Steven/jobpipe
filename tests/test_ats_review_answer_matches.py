from tools.ats_review_answer_matches import build_review_with_verified_matches
from tools.ats_verified_answer_bank import normalize_question

def test_normalization_handles_newlines_and_whitespace():
    assert normalize_question(" Do you use  AI\n in your role? ")==normalize_question("Do you use AI in your role?")

def test_exact_scoped_verified_answer_annotation_never_leaks_value():
    fields=[{"question":"Do you use AI in your role?","label":"Yes","type":"radio","required":True},
            {"question":"Do you use AI in your role?","label":"No","type":"radio","required":True},
            {"question":"Background check concerns?","type":"textarea","required":True},
            {"question":"Full name ✱","label":"Full name ✱","type":"text","required":True}]
    bank=[{"question":"Do you use AI in your role?","answer":"PRIVATE_TEST_RESPONSE","scope":"employer","employer":"Ethena","human_verified":True},
          {"question":"Background check concerns?","answer":"PRIVATE_UNVERIFIED","scope":"global","human_verified":False}]
    out=build_review_with_verified_matches(fields,{"full_name"},bank,"Ethena")
    assert out["review_item_count"]==2
    assert out["verified_answer_match_count"]==1
    assert out["human_review"][0]["status"]=="human_review"
    assert any(item["question"]=="Do you use AI in your role?" and item["verified_answer_available"] for item in out["human_review"])
    assert "PRIVATE_TEST_RESPONSE" not in str(out)
    assert "PRIVATE_UNVERIFIED" not in str(out)
    other=build_review_with_verified_matches(fields,{"full_name"},bank,"Other employer")
    assert other["verified_answer_match_count"]==0

def test_global_explicit_only_and_similar_question_not_matched():
    fields=[{"question":"Will you require sponsorship?","type":"radio","required":True}]
    bank=[{"question":"Will you require sponsorship?","answer":"Y","scope":"global","human_verified":True}]
    assert build_review_with_verified_matches(fields,set(),bank,"Any")["verified_answer_match_count"]==1
    fields[0]["question"]="Are you authorized to work?"
    assert build_review_with_verified_matches(fields,set(),bank,"Any")["verified_answer_match_count"]==0
