from __future__ import annotations

from jobpipe_queue import _priority


def test_priority_bands() -> None:
    assert _priority(90) == "High"
    assert _priority(85) == "High"
    assert _priority(84) == "Medium"
    assert _priority(75) == "Medium"
    assert _priority(74) == "Low"
