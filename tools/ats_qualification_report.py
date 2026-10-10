"""Offline, bounded, privacy-safe ATS Review-arrival qualification scorecard.

Inputs are operator-attested sanitized receipts gathered during a SEPARATE
attended, non-submitting evaluation. This tool NEVER visits an ATS or submits
applications. Hashes are references, not independently verified proof, and
even a measured pass is NOT production authorization.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
_MAX_BYTES = 2_000_000
_MAX_RECEIPTS = 1000
_ATS = ("greenhouse", "lever", "ashby", "jobvite", "workday")
_ENVIRONMENTS = frozenset({"FIXTURE", "ATTENDED_LIVE_NON_SUBMIT"})
_STATUSES = frozenset({"REVIEW_READY", "NEEDS_HUMAN", "FAILED", "INCOMPLETE"})
_FIELDS = frozenset({
    "attempt_id", "ats", "environment", "status", "review_reference_hash",
    "human_interventions", "observed_at", "submission_attempted", "reason_code",
})
_ID = re.compile(r"[a-zA-Z0-9_-]{8,80}\Z")
_DIGEST = re.compile(r"[0-9a-f]{64}\Z")
_FAILURES = frozenset({
    "NONE", "AUTH_REQUIRED", "CAPTCHA", "MFA", "EMAIL_VERIFICATION",
    "ACCOUNT_LOCKED", "REQUIRED_ANSWER", "UPLOAD", "ATS_MARKUP_CHANGED",
    "NAVIGATION", "BROWSER_CRASH", "TIMEOUT", "JOB_CLOSED", "UNKNOWN",
})


def _validate_receipt(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict) or set(item) != _FIELDS:
        raise ValueError("qualification receipt schema is invalid")
    if not isinstance(item["attempt_id"], str) or _ID.fullmatch(item["attempt_id"]) is None:
        raise ValueError("attempt_id must be a sanitized opaque identifier")
    if item["ats"] not in _ATS or item["environment"] not in _ENVIRONMENTS:
        raise ValueError("ATS or environment is unsupported")
    if item["status"] not in _STATUSES:
        raise ValueError("qualification status is unsupported")
    if type(item["human_interventions"]) is not int or not 0 <= item["human_interventions"] <= 50:
        raise ValueError("human intervention count is invalid")
    if item["submission_attempted"] is not False:
        raise ValueError("qualification receipts may not include real submissions")
    if item["reason_code"] not in _FAILURES:
        raise ValueError("reason code must be one of the sanitized enum values")
    if (
        item["status"] == "REVIEW_READY"
        and item["reason_code"] != "NONE"
    ) or (
        item["status"] != "REVIEW_READY"
        and item["reason_code"] == "NONE"
    ):
        raise ValueError("review and reason code conflict")
    proof = item["review_reference_hash"]
    if item["status"] == "REVIEW_READY":
        if not isinstance(proof, str) or _DIGEST.fullmatch(proof) is None:
            raise ValueError("Review requires an engine record reference hash")
    elif proof is not None:
        raise ValueError("non-Review outcome cannot claim Review evidence")
    timestamp = item["observed_at"]
    if not isinstance(timestamp, str) or len(timestamp) > 40:
        raise ValueError("observed_at must be a timezone-aware timestamp")
    try:
        instant = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("observed_at must be RFC 3339") from exc
    if instant.tzinfo is None:
        raise ValueError("observed_at requires timezone")
    return item


def read_receipts(path: Path) -> list[dict[str, Any]]:
    """Reject repository-local data, symlink input, malformed rows, and huge files."""
    path = Path(path).expanduser()
    if path.is_symlink() or not path.is_file():
        raise ValueError("qualification input must be a regular external file")
    resolved = path.resolve()
    if resolved == ROOT or ROOT in resolved.parents:
        raise ValueError("qualification evidence must not be stored in the source repository")
    if path.stat().st_size > _MAX_BYTES:
        raise ValueError("qualification input exceeds the maximum size")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if len(rows) >= _MAX_RECEIPTS:
                raise ValueError("qualification receipt limit exceeded")
            if not line.strip():
                raise ValueError("qualification receipts cannot include blank lines")
            try:
                item = _validate_receipt(json.loads(line))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError("invalid sanitized qualification receipt") from exc
            if item["attempt_id"] in seen:
                raise ValueError("duplicate attempt_id would distort denominator")
            seen.add(item["attempt_id"])
            rows.append(item)
    return rows


def assess(receipts: list[Mapping[str, Any]], *, minimum_per_ats: int = 20) -> dict[str, Any]:
    """Compute auditable metrics, never asserting independently verified live proof."""
    if type(minimum_per_ats) is not int or not 1 <= minimum_per_ats <= 100:
        raise ValueError("minimum_per_ats must be from 1 through 100")
    validated = [_validate_receipt(dict(item)) for item in receipts]
    if len(validated) > _MAX_RECEIPTS:
        raise ValueError("qualification receipt limit exceeded")
    ids = [item["attempt_id"] for item in validated]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate attempts would inflate the Review denominator")
    live = [x for x in validated if x["environment"] == "ATTENDED_LIVE_NON_SUBMIT"]
    fixture = [x for x in validated if x["environment"] == "FIXTURE"]
    per_ats = {}
    for ats in _ATS:
        rows = [item for item in live if item["ats"] == ats]
        reached = sum(item["status"] == "REVIEW_READY" for item in rows)
        attempted = len(rows)
        per_ats[ats] = {
            "attempted": attempted,
            "review_reached_attested": reached,
            "review_arrival_rate": reached / attempted if attempted else None,
            "human_interventions": sum(item["human_interventions"] for item in rows),
            "interventions_per_attempt": (
                sum(item["human_interventions"] for item in rows) / attempted
                if attempted else None
            ),
            "reasons": dict(sorted(Counter(
                item["reason_code"] for item in rows if item["reason_code"] != "NONE"
            ).items())),
            "minimum_sample_met": attempted >= minimum_per_ats,
        }
    count = len(live)
    reached = sum(x["status"] == "REVIEW_READY" for x in live)
    measured = all(
        report["minimum_sample_met"] and (
            report["review_arrival_rate"] is not None
            and report["review_arrival_rate"] >= 0.95
        )
        for report in per_ats.values()
    )
    return {
        "contract_version": "ats-review-qualification-v1",
        "evidence_provenance": "OPERATOR_ATTESTED_NOT_INDEPENDENTLY_VERIFIED",
        "fixture_attempts_excluded": len(fixture),
        "live_attended_non_submit_attempts": count,
        "review_reached_attested": reached,
        "attested_review_arrival_rate": reached / count if count else None,
        "human_interventions_total": sum(x["human_interventions"] for x in live),
        "per_ats": per_ats,
        "qualification_gate": (
            "NOT_MEASURED" if count == 0 else
            "INSUFFICIENT_SAMPLE" if any(
                not x["minimum_sample_met"] for x in per_ats.values()
            ) else "MEASURED_PASS" if measured else "MEASURED_FAIL"
        ),
        "independently_verified": False,
        "production_submission_authorized": False,
        "message": (
            "These are sanitized operator-attested non-submit observations. "
            "A measured pass does not prove independent live Review arrival "
            "or authorize real submissions."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--minimum-per-ats", type=int, default=20)
    args = parser.parse_args()
    try:
        report = assess(
            read_receipts(args.input), minimum_per_ats=args.minimum_per_ats
        )
    except (OSError, UnicodeError, TypeError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
