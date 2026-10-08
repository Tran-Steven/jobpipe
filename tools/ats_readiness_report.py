"""Machine-readable local ATS fixture readiness, never live readiness."""
from __future__ import annotations
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
def assess(returncode:int, output:str)->dict:
    marker="ATS_FIXTURE_REVIEW_GATE=PASS"
    passed=returncode==0 and any(line.startswith(marker) for line in output.splitlines())
    return {
        "fixture_review": "passed" if passed else "failed",
        "live_review": "not_verified",
        "real_submissions": "not_attempted",
        "supported_adapters": ["greenhouse","lever","ashby","jobvite"],
        "note": "Local browser fixtures only; this does not verify any real ATS application",
    }

def main()->int:
    try:
        result=subprocess.run(
            [sys.executable, str(ROOT/"tools"/"ats_review_smoke.py")],
            cwd=ROOT, capture_output=True,text=True,timeout=340
        )
        report=assess(result.returncode,result.stdout)
    except (subprocess.TimeoutExpired,OSError) as exc:
        report=assess(1,"")
        report["error"]=type(exc).__name__
    print(json.dumps(report,sort_keys=True))
    return 0 if report["fixture_review"]=="passed" else 1

if __name__=="__main__":
    raise SystemExit(main())
