"""No-submit ATS fixture Review gate. Does not prove live ATS readiness."""
from __future__ import annotations
import os
from pathlib import Path
import signal
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TEST = "tests/test_ats_adapter_contract.py"
PATTERNS = (
    "adapter_reaches_review_with_required_fields_and_upload",
    "submit_requires_gate_b",
    "review_requires_a_final_submit_control",
)

def main() -> int:
    command = [sys.executable, "-m", "pytest", "-q", "--tb=short", TEST,
               "-k", " or ".join(PATTERNS)]
    proc = subprocess.Popen(command, cwd=ROOT, start_new_session=True)
    try:
        rc = proc.wait(timeout=300)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
        print("ATS_FIXTURE_REVIEW_GATE=TIMEOUT; LIVE_REVIEW=NOT_VERIFIED; SUBMISSIONS=NOT_ATTEMPTED", flush=True)
        return 124
    print(f"ATS_FIXTURE_REVIEW_GATE={'PASS' if rc == 0 else 'FAIL'}; LIVE_REVIEW=NOT_VERIFIED; SUBMISSIONS=NOT_ATTEMPTED", flush=True)
    return rc

if __name__ == "__main__":
    raise SystemExit(main())
