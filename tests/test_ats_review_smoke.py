"""Smoke-gate result must fail closed when Chromium fixture tests are skipped."""
from tools import ats_review_smoke

def test_smoke_success_requires_executed_tests(monkeypatch):
    class FakeProcess:
        def __init__(self, output, code):
            self.output, self.returncode = output, code
        def communicate(self, timeout=None):
            return self.output, None
    def mock_popen(*args, **kwargs):
        return FakeProcess(
            "\n".join(
                f"tests/test_ats_adapter_contract.py::test_adapter_reaches_review_with_required_fields_and_upload[{name}-x] PASSED"
                for name in ("greenhouse","lever","ashby","jobvite")
            ) + "\n".join(
                f"tests/test_ats_adapter_contract.py::test_browser_navigates_local_http_ats_page_to_review_without_submit[{name}-x] PASSED"
                for name in ("greenhouse","lever","ashby","jobvite")
            ) + "\ntests/test_ats_adapter_contract.py::test_submit_requires_gate_b PASSED\n13 passed in 1.0s", 0)
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


def test_smoke_refuses_count_only_without_adapter_coverage(monkeypatch):
    class FakeProcess:
        returncode = 0
        def communicate(self, timeout=None):
            return "9 passed in 1.0s", None
    monkeypatch.setattr(ats_review_smoke.subprocess, "Popen", lambda *a, **k: FakeProcess())
    assert ats_review_smoke.main() != 0


def test_smoke_refuses_review_only_without_navigation_proof(monkeypatch):
    class FakeProcess:
        returncode = 0
        def communicate(self, timeout=None):
            return ("\n".join(
                f"tests/test_ats_adapter_contract.py::test_adapter_reaches_review_with_required_fields_and_upload[{name}-x] PASSED"
                for name in ("greenhouse","lever","ashby","jobvite"))
                + "\ntests/test_ats_adapter_contract.py::test_submit_requires_gate_b PASSED\n13 passed in 1.0s", None)
    monkeypatch.setattr(ats_review_smoke.subprocess, "Popen", lambda *a, **k: FakeProcess())
    assert ats_review_smoke.main()!=0
