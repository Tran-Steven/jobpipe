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

## Security and product boundaries

- Permissions: extension-local storage only; a content script on LinkedIn job
  pages. No cookies, tabs, webRequest or local filesystem permissions.
- No auto-apply, automatic final clicks, ATS login, CAPTCHA interaction, or
  cross-service data sharing.
- Only numeric LinkedIn posting IDs (not full URLs), and normalized company
  names are stored by the extension. These values may still be sensitive local
  history and must not be logged or uploaded.
- Company/title similarity alone never marks a job as already applied.
- Site HTML/selector changes may break visual filtering; this is a pre-eval
  implementation, not a verified current LinkedIn integration.
- The extension does **not** silently synchronize with jobpipe Private Home.
  A separately authenticated, opt-in sync and real-site UX testing remain
  in issue #6. The server's independent duplicate-submit checks remain
  authoritative regardless of which cards are hidden in the browser.
