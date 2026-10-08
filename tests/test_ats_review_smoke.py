"""Smoke-gate result must fail closed when Chromium fixture tests are skipped."""
from tools import ats_review_smoke

def test_smoke_success_requires_executed_tests(monkeypatch):
    class FakeProcess:
        def __init__(self, output, code):
            self.output, self.returncode = output, code
        def communicate(self, timeout=None):
            return self.output, None
    def mock_popen(*args, **kwargs):
        return FakeProcess("9 passed in 1.0s", 0)
    monkeypatch.setattr(ats_review_smoke.subprocess, "Popen", mock_popen)
    assert ats_review_smoke.main() == 0

def test_smoke_refuses_green_all_skipped(monkeypatch):
    class FakeProcess:
        returncode = 0
        def communicate(self, timeout=None):
            return "9 skipped in 1.0s", None
    monkeypatch.setattr(ats_review_smoke.subprocess, "Popen",
                        lambda *a, **k: FakeProcess())
    assert ats_review_smoke.main() != 0

def test_smoke_refuses_partial_and_failed_runs(monkeypatch):
    class FakeProcess:
        returncode = 0
        def communicate(self, timeout=None):
            return "4 passed, 5 skipped in 1.0s", None
    monkeypatch.setattr(ats_review_smoke.subprocess, "Popen",
                        lambda *a, **k: FakeProcess())
    assert ats_review_smoke.main() != 0
