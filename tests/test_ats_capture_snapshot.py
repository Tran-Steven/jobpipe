import json,os
from pathlib import Path
import pytest
from tools.ats_capture_snapshot import capture
from tools.ats_review_snapshot import sanitized_fields

@pytest.mark.asyncio
async def test_capture_rejects_unsafe_url_without_browser(tmp_path):
    with pytest.raises(ValueError,match="not allowed"):
        await capture("http://127.0.0.1/private",tmp_path/"out.json")
    assert not (tmp_path/"out.json").exists()

def test_snapshot_metadata_only_and_compatible_with_review(tmp_path):
    from tools.ats_review_batch import build_review_batch
    items=sanitized_fields([{"question":"Do you use AI?","label":"Yes","type":"radio","required":True,"value":"NEVER_COPY"},
                            {"question":"Do you use AI?","label":"No","type":"radio","required":True}])
    assert len(items)==2
    assert "NEVER_COPY" not in json.dumps(items)
    result=build_review_batch(items,set())
    assert result["review_item_count"]==1
    assert result["submission"]=="not_attempted"
