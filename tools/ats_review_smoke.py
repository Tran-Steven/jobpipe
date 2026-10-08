"""No-submit ATS fixture Review gate. Does not prove live ATS readiness."""
from __future__ import annotations
import os
from pathlib import Path
import signal
import subprocess
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
TEST = "tests/test_ats_adapter_contract.py"
PATTERNS = (
    "adapter_reaches_review_with_required_fields_and_upload",
    "submit_requires_gate_b",
    "review_requires_a_final_submit_control",
    "browser_navigates_local_http_ats_page_to_review_without_submit",
)

def main() -> int:
    command = [sys.executable, "-m", "pytest", "-vv", "--tb=short", TEST,
               "-k", " or ".join(PATTERNS)]
    proc = subprocess.Popen(command, cwd=ROOT, start_new_session=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        output, _ = proc.communicate(timeout=300)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.communicate(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.communicate()
        print("ATS_FIXTURE_REVIEW_GATE=TIMEOUT; LIVE_REVIEW=NOT_VERIFIED; SUBMISSIONS=NOT_ATTEMPTED", flush=True)
        return 124
    print(output, end="" if output.endswith("\n") else "\n", flush=True)
    match = re.search(r"(?<!\d)(\d+) passed", output)
    count = int(match.group(1)) if match else 0
    # At least four distinct adapter Review fixtures + five safety assertions;
    # skips are disallowed because Chromium may be missing.
    required = (
        "test_adapter_reaches_review_with_required_fields_and_upload[greenhouse-",
        "test_adapter_reaches_review_with_required_fields_and_upload[lever-",
        "test_adapter_reaches_review_with_required_fields_and_upload[ashby-",
        "test_adapter_reaches_review_with_required_fields_and_upload[jobvite-",
    )
    navigation_required = (
        "test_browser_navigates_local_http_ats_page_to_review_without_submit[greenhouse-",
        "test_browser_navigates_local_http_ats_page_to_review_without_submit[lever-",
        "test_browser_navigates_local_http_ats_page_to_review_without_submit[ashby-",
        "test_browser_navigates_local_http_ats_page_to_review_without_submit[jobvite-",
    )
    navigation_verified = all(
        any(required_name in line and " PASSED" in line
            for line in output.splitlines())
        for required_name in navigation_required
    )
    review_verified = all(
        any(required_name in line and " PASSED" in line
            for line in output.splitlines())
        for required_name in required
    )
    safeguard_verified = any(
        "test_submit_requires_gate_b" in line and " PASSED" in line
        for line in output.splitlines()
    )
    good = (rc == 0 and count >= 13
            and not re.search(r"\d+ skipped", output)
            and review_verified and navigation_verified and safeguard_verified)
    print(f"ATS_FIXTURE_REVIEW_GATE={'PASS' if good else 'FAIL'}; LIVE_REVIEW=NOT_VERIFIED; SUBMISSIONS=NOT_ATTEMPTED", flush=True)
    return 0 if good else (rc or 1)

if __name__ == "__main__":
    raise SystemExit(main())
