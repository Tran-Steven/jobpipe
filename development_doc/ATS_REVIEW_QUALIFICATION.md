# Attended ATS Review qualification (non-submitting)

## Goal

Measure whether **current supported ATS adapters** can arrive at their genuine
Review screens without submitting applications, while explicitly separating
fixture success from attended public-site evidence. This is a **future attended
evaluation** procedure. The normal development CI never visits real accounts,
accepts consent/terms, retrieves real OTPs, uploads user materials or clicks
final Submit.

### Qualification phases and non-goals

1. **Fixture gate**: run `python jobctl.py ats-fixture-check` on a development
   machine with Playwright Chromium installed. This exercises local synthetic
   forms and must emit `ATS_FIXTURE_REVIEW_GATE=PASS`. It NEVER proves real-site
   readiness.
2. **Public landing-page diagnostics (separate, explicitly invoked)**: call
   `python -m tools.live_ats_inspect <official ATS https URL>`. Only exact
   official Greenhouse/Lever/Ashby/Jobvite and tenant-scoped Workday hosts are
   accepted. No credentials, form interaction, external uploads or submit
   actions. Navigation outside official hosts, non-HTTPS/private-network
   subresources and mutating requests are denied. This is intentionally a
   diagnostic, not a Review attempt or job-availability guarantee.
3. **Attended Review arrival**: select a representative set of *eligible*
   requisitions, prepare anonymized test accounts and non-sensitive test
   materials with separately approved boundaries, and use the
   **non-submit-only** engine (`request_submit=False`, no Gate B). Stop at
   Review or typed human handoff. Never label a click, landing page or incomplete
   form as Review. Do not try to bypass CAPTCHA/MFA. Save sensitive output and
   browser session data only in external Private Home, never Git.
4. **Operator-attested scorecard**: independently confirm the source, outcome
   and engine record, then create sanitized one-line JSON receipts in an
   **external Private Home file**. Report them with:
   `python jobctl.py ats-qualification-report --input /private/path/receipts.jsonl`
   (optional `--minimum-per-ats 20`).
   A receipt digest alone is a *reference*, not cryptographic proof of the
   browser reaching Review; the report always declares
   `independently_verified=false` and
   `production_submission_authorized=false`.

## Sanitized JSONL receipt contract

One JSON object per **distinct attempt**, required fields only:

```json
{"attempt_id":"attempt-00000001","ats":"greenhouse","environment":"FIXTURE","status":"REVIEW_READY","review_reference_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","human_interventions":0,"observed_at":"2026-10-10T14:00:00-07:00","submission_attempted":false,"reason_code":"NONE"}
```

The example is a **synthetic fixture receipt**, not a statement that a live
Review was reached. Set `environment` to `ATTENDED_LIVE_NON_SUBMIT` only
after a real attended evaluation. For a genuine `REVIEW_READY`, enter a
lowercase SHA-256 reference to the associated local engine Review evidence
and set `reason_code=NONE`. Failure/handoff/incomplete statuses are
`FAILED`, `NEEDS_HUMAN` and `INCOMPLETE`; they must use a safe failure
reason code and `review_reference_hash=null`. Supported reason codes:
`AUTH_REQUIRED`, `CAPTCHA`, `MFA`, `EMAIL_VERIFICATION`,
`ACCOUNT_LOCKED`, `REQUIRED_ANSWER`, `UPLOAD`, `ATS_MARKUP_CHANGED`,
`NAVIGATION`, `BROWSER_CRASH`, `TIMEOUT`, `JOB_CLOSED`, `UNKNOWN`.
Do not put URLs, applicant identities, text from forms, secrets, cookies,
employer-specific questions or screenshots into these JSON records.

Receipts are parsed strictly (2 MB/1,000 attempts limit, no duplicate IDs,
no symlink input, no source-repository path). A real submission is **never**
eligible for this report; `submission_attempted=true` is rejected.

## Decision and gates

- Report the **per-ATS denominator** and Review rate, not only one aggregate.
- The provisional statistical gate requires >=20 attended, non-submitting
  attempts **per ATS** (Greenhouse, Lever, Ashby, Jobvite, Workday), >=95%
  attended operator-attested Review arrivals in every individual ATS, and
  intervention counts/failure reasons reported alongside the rate.
- `NOT_MEASURED`, `INSUFFICIENT_SAMPLE` and `MEASURED_FAIL` cannot qualify
  the product. `MEASURED_PASS` is only an **attended evidence checkpoint**,
  not independently proven live reliability and not authorization for
  production use or real submissions.
- Separately require macOS native lease/runtime qualification, crash/restart
  recovery, the zero-duplicate-intent invariant, and independently checked
  Review evidence. No automatic retry of uncertain submissions. Explicit
  per-run Gate B submission authorization remains its own future release
  decision.
- Report real outcomes and missing evidence, not fabricated estimates.
  Automated CI, a reachable landing page, or fixture smoke success must
  **never** be displayed as the live acceptance metric.

## Development controls

Continue engineering using feature branches, regression tests, full
Ubuntu/macOS CI, and inspected commits before merge. The next evaluation
phase is **not** initiated by making or merging a PR, and cannot be inferred
from the user's search preferences or their request to continue development.
