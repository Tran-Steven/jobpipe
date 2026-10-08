from tools.ats_review_batch import build_review_batch

def test_yes_no_single_required_review_item_and_required_first():
    fields=[
      {"question":"Do you use AI in your role?","label":"Yes","type":"radio","required":True},
      {"question":"Do you use AI in your role?","label":"No","type":"radio","required":True},
      {"question":"How did you hear about this?","type":"textarea","required":False},
      {"question":"Full name ✱","label":"Full name ✱","type":"text","required":True}]
    result=build_review_batch(fields,{"full_name"})
    assert result["input_field_count"]==4
    assert len(result["verified_candidates"])==1
    assert result["verified_candidates"][0]["profile_key"]=="full_name"
    assert result["review_item_count"]==2
    assert result["human_review"][0]["question"]=="Do you use AI in your role?"
    assert result["human_review"][0]["control_count"]==2
    assert result["human_review"][0]["required"] is True
    assert result["submission"]=="not_attempted"

def test_no_raw_answers_or_values_leak_and_deterministic_ids():
    fields=[{"question":"Will you require sponsorship?","label":"No","type":"radio","required":True,
             "value":"SECRET_VALUE_DO_NOT_COPY","email":"PRIVATE_EMAIL_DO_NOT_COPY"},
            {"question":"Will you require sponsorship?","label":"Yes","type":"radio","required":True}]
    a=build_review_batch(fields,set())
    b=build_review_batch(fields,set())
    assert a==b
    assert "SECRET_VALUE_DO_NOT_COPY" not in str(a)
    assert "PRIVATE_EMAIL_DO_NOT_COPY" not in str(a)
    assert len(a["human_review"])==1

def test_unknown_required_field_stays_review():
    result=build_review_batch([{"question":"Background check concerns?","type":"textarea","required":True}],{"full_name"})
    assert result["human_review"][0]["required"] is True
    assert not result["verified_candidates"]
