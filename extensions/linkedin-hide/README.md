# Optional local-only LinkedIn job hiding (experimental)

This unpacked WebExtension is an **optional browser visibility aid**, not an ATS
integration. It runs only under `linkedin.com/jobs/*` (Chrome/Firefox-compatible
MV3 syntax). It hides job cards from view, never clicks LinkedIn's application,
dismissal, or submission controls, never fetches remote URLs, and never sends
cards, cookies, credentials, LinkedIn profiles or application history to jobpipe.

## Install for local evaluation

In Chrome open `chrome://extensions`, enable Developer Mode, and choose
**Load unpacked** with this directory. In Firefox, use the temporary add-on
developer workflow if supported by the running Firefox version. No store
distribution or automatic installation is provided.

Use **Hide posting** on a card with a recognized LinkedIn numeric job ID,
or **Block employer** on a card with a recognized company label. Hidden IDs
and normalized employer names are saved in *the browser extension's local
storage*, not in the jobpipe private SQLite history. **Undo**, **Show matched**
and **Review blocked** allow reversing changes. Unknown job IDs cannot be
durably hidden, and ambiguous employer labels are not guessed.

### Hide user-reported applied postings

Click **Import applied CSV** in the extension and select a local UTF-8 file with
the exact `job_url,status` header and rows like:

```csv
job_url,status
https://www.linkedin.com/jobs/view/123456789,APPLIED
```

Every row must contain the explicit `APPLIED` state and an official LinkedIn
`/jobs/view/{numeric-id}` URL. Invalid rows, mixed statuses, ambiguous IDs,
oversized files, or malformed headers reject the **whole file**. A file may
contain at most 2,000 rows and 256 KB of text. Only numeric posting IDs are
retained in extension-local storage, never the original URLs or CSV text.

The extension hides these cards as **user-reported applied**, not verified
ATS submissions. Use **Review blocked** to clear applied imports separately
from dismissed postings, or temporarily **Show matched**. The extension cannot
derive posting URLs from Jobpipe's hash-only private history exports. Prepare
this CSV only from applications you personally confirm, keep it private, and
delete the local copy when it is no longer required. This import does not
update Jobpipe's private submission ledger or authorize an application.
### Import a Jobpipe private history backup (hash-only)

Run `python jobctl.py job-history-export --csv ~/Downloads/jobpipe-private-history.csv`
from your own configured Private Home. The resulting export has the exact
`identity_hash,status,recorded_at` columns and no source URLs. It is still
**sensitive job-search history**: hashes of public posting URLs can be
guessed or matched by someone who knows the original URL.

On a LinkedIn jobs page, select **Import Jobpipe backup** and choose the
exported CSV. The extension validates the entire local file (up to 10,000 rows
and 2 MB), stores the exact SHA-256 hash values in its own browser-local storage,
and checks only the native LinkedIn IDs of currently displayed cards by hashing
their canonical `https://linkedin.com/jobs/view/{id}` identity with WebCrypto.
Self-reported applied entries hide as such; dismissed entries remain distinct.
Unknown or ATS-only hashes cannot be linked to LinkedIn without separately
verified posting identities, and no company/title inference is performed.

Use **Review blocked → Clear Jobpipe backup** to remove just the imported
hashes; **Show matched** temporarily reveals hidden cards. Importing a later
backup replaces the earlier imported hash snapshot without changing separately
manually dismissed or user-reported applied IDs. Nothing automatically syncs
with Jobpipe or changes its private database. No site application/submit
controls are clicked. Delete the exported CSV from Downloads when finished.
### Optional manual import of your hidden postings

Use **Export dismissals** only when you want to transfer individual hidden
LinkedIn postings into jobpipe. The browser downloads
`jobpipe-linkedin-dismissed.csv` with the columns `job_url,status`.
Every exported row is exactly `DISMISSED`, **never `APPLIED`**. Blocking
a company does not create a dismissal row for all its jobs; neither does a
LinkedIn X click that this extension did not explicitly observe.

Preview the CSV locally before committing:

```bash
python jobctl.py job-history-import --csv ~/Downloads/jobpipe-linkedin-dismissed.csv
# After reviewing counts, explicitly commit:
python jobctl.py job-history-import --csv ~/Downloads/jobpipe-linkedin-dismissed.csv --commit
```

This is **not** automatic synchronization. The file contains LinkedIn
posting URLs (sensitive browsing history) and may remain in Downloads.
Keep it private and delete it there when no longer required. Import refuses
to overwrite a previously applied posting with `DISMISSED`.

## Security and product boundaries

- Permissions: extension-local storage only; a content script on LinkedIn job
  pages. No cookies, tabs, webRequest or local filesystem permissions.
- No auto-apply, automatic final clicks, ATS login, CAPTCHA interaction, or
  cross-service data sharing.
- Only native numeric LinkedIn posting IDs, normalized employer names, and
  explicitly imported SHA-256 history hashes are stored locally, never full URLs. These values may still be sensitive local
  history and must not be logged or uploaded.
- Company/title similarity alone never marks a job as already applied.
- Conflicting job identities, contradictory employer labels, and overlong employer
  names fail closed rather than hiding potentially unrelated job cards.
- Site HTML/selector changes may break visual filtering; this is a pre-eval
  implementation, not a verified current LinkedIn integration.
- The extension does **not** silently synchronize with jobpipe Private Home.
  Its explicit CSV handoff is user-initiated, local-only, previewable and
  recorded as `DISMISSED`, not proof of submission. An authenticated opt-in
  automatic sync and real-site UX testing remain in issue #6. The server's
  independent duplicate-submit checks remain authoritative regardless of
  which cards are hidden in the browser.
