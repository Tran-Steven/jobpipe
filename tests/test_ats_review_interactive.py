from tools.ats_review_interactive import review_interactively
from tools.ats_verified_answer_bank import load_bank
ITEMS=[{"id":"one","status":"human_review","question":"Why us?","required":True},
       {"id":"two","status":"human_review","question":"Pronunciation?","required":False}]
def inputs(*values):
    iterator=iter(values)
    return lambda prompt: next(iterator)

def test_explicit_per_item_and_batch_confirmation(tmp_path):
    path=tmp_path/"answers.json"
    result=review_interactively(path,ITEMS,"Example",
      input_fn=inputs("PRIVATE_TEST_VALUE","employer","VERIFY","","SAVE"),
      print_fn=lambda _:None)
    assert result["saved_count"]==1 and result["submission"]=="not_attempted"
    assert "PRIVATE_TEST_VALUE" not in str(result)
    assert load_bank(path)[0]["scope"]=="employer"

def test_no_batch_save_without_explicit_save(tmp_path):
    path=tmp_path/"answers.json"
    result=review_interactively(path,ITEMS,"Example",
      input_fn=inputs("PRIVATE_TEST_VALUE","global","VERIFY","","NO"),
      print_fn=lambda _:None)
    assert result["saved_count"]==0 and not path.exists()

def test_no_implicit_verification(tmp_path):
    path=tmp_path/"answers.json"
    result=review_interactively(path,ITEMS,"Example",
      input_fn=inputs("SECRET","global","yes",""),print_fn=lambda _:None)
    assert result["saved_count"]==0 and not path.exists()
