# jobpipe

jobpipe builds on the MIT-licensed Jobops codebase while focusing the product on continuous job discovery and orchestration.

The inherited ATS execution engine remains intentionally conservative: verified candidate facts, deterministic adapters where possible, duplicate-submit protection, and human handoff for CAPTCHA, MFA, account locks, and unknown sensitive answers.

## Command surface

- `python jobpipe.py init`
- `python jobpipe.py policy`
- `python jobpipe.py queue --list`
- `python jobpipe.py status`
- `python jobpipe.py apply-csv --limit 1`

Discovery and continuous orchestration are the primary jobpipe extension layer.
