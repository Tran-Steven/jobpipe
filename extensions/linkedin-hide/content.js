"use strict";
/* Local-only LinkedIn job-card hiding. No cross-origin fetch, clicks on site
 * controls, application submission, or private Jobpipe history changes.
 */
(() => {
  const rules = globalThis.JobpipeLinkedInRules;
  const storage = globalThis.browser ?? globalThis.chrome;
  if (!rules || !storage || !storage.storage?.local) return;
  const KEY = "jobpipe.linkedin.hide.v1";
  const SELECTORS = [
    "li.jobs-search-results__list-item",
    "li.scaffold-layout__list-item",
    "li.jobs-search-two-pane__job-card-container",
    "[data-occludable-job-id]",
    ".job-card-container"
  ].join(", ");
  let state = rules.sanitizeState({});
  let showHidden = false;
  let undoState = null;
  let scheduled = false;
  let panel = null;
  let lastSummary = "";
  const MAX_CARDS_PER_UPDATE = 300;
  let refreshGeneration = 0;
  const digestCache = new Map();

  function identityHashForPosting(id) {
    const identity = rules.linkedInCanonicalIdentity(id);
    if (!identity || !globalThis.crypto?.subtle) return Promise.resolve("");
    let digest = digestCache.get(id);
    if (!digest) {
      digest = crypto.subtle.digest("SHA-256", new TextEncoder().encode(identity))
        .then((buffer) => Array.from(new Uint8Array(buffer), (byte) => byte.toString(16).padStart(2, "0")).join(""))
        .catch(() => "");
      digestCache.set(id, digest);
      if (digestCache.size > 1000) digestCache.delete(digestCache.keys().next().value);
    }
    return digest;
  }

  async function persist(next) {
    const safe = rules.sanitizeState(next);
    const previous = state;
    await storage.storage.local.set({ [KEY]: safe });
    undoState = previous;
    state = safe;
    lastSummary = "";
    refresh();
  }

  function createButton(label, handler, disabled = false) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "jobpipe-visual-hide-button";
    button.textContent = label;
    button.disabled = disabled;
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopImmediatePropagation();
      Promise.resolve(handler()).catch(() => {
        if (panel) panel.querySelector(".jobpipe-visual-hide-status").textContent =
          "Local setting could not be saved.";
      });
    });
    return button;
  }

  function controls(card) {
    const existing = card.querySelector(":scope > .jobpipe-visual-hide-actions");
    if (existing) {
      const buttons = existing.querySelectorAll("button");
      if (buttons[0]) buttons[0].disabled = !rules.jobIdFromCard(card);
      if (buttons[1]) buttons[1].disabled = !rules.companyFromCard(card);
      return;
    }
    const bar = document.createElement("div");
    bar.className = "jobpipe-visual-hide-actions";
    bar.setAttribute("aria-label", "jobpipe job visibility controls");
    bar.append(
      createButton("Hide posting", async () => {
        const id = rules.jobIdFromCard(card);
        if (id) await persist({ ...state, hiddenPostingIds: [...state.hiddenPostingIds, id] });
      }, !rules.jobIdFromCard(card)),
      createButton("Block employer", async () => {
        const company = rules.companyFromCard(card);
        if (company) await persist({ ...state, blockedCompanies: [...state.blockedCompanies, company] });
      }, !rules.companyFromCard(card))
    );
    card.append(bar);
  }

  function findCards() {
    const found = Array.from(document.querySelectorAll(SELECTORS)).slice(0, MAX_CARDS_PER_UPDATE);
    // Avoid double controls on nested card containers.
    return found.filter((node) => !found.some((other) => other !== node && other.contains(node)));
  }

  async function refresh() {
    const generation = ++refreshGeneration;
    const cards = findCards().filter((card) => !card.closest("#jobpipe-visual-hide-panel"));
    for (const card of cards) controls(card);
    const hasPrivateHistory = state.historyAppliedHashes.length + state.historyDismissedHashes.length > 0;
    const hashes = hasPrivateHistory
      ? await Promise.all(cards.map((card) => identityHashForPosting(rules.jobIdFromCard(card))))
      : [];
    if (generation !== refreshGeneration) return;
    let hidden = 0;
    for (const [index, card] of cards.entries()) {
      const reason = rules.whyHidden(card, state, hashes[index] || "");
      if (reason) hidden += 1;
      card.classList.toggle("jobpipe-visual-hidden", Boolean(reason) && !showHidden);
      if (reason) card.dataset.jobpipeVisualHideReason = reason;
      else delete card.dataset.jobpipeVisualHideReason;
    }
    if (!panel) return;
    const summary = `${hidden} hidden on this page · ${state.blockedCompanies.length} blocked employers · ${state.hiddenPostingIds.length} dismissed · ${state.appliedPostingIds.length} reported applied · ${state.historyAppliedHashes.length + state.historyDismissedHashes.length} backup hashes`;
    if (summary !== lastSummary) {
      panel.querySelector(".jobpipe-visual-hide-status").textContent = summary;
      lastSummary = summary;
    }
    panel.querySelector(".jobpipe-visual-hide-undo").disabled = !undoState;
    panel.querySelector(".jobpipe-visual-hide-export").disabled = state.hiddenPostingIds.length === 0;
    panel.querySelector(".jobpipe-visual-hide-show").textContent =
      showHidden ? "Hide matched" : "Show matched";
  }

  function renderRules() {
    if (!panel) return;
    const list = panel.querySelector(".jobpipe-visual-hide-review-list");
    list.replaceChildren();
    for (const company of state.blockedCompanies) {
      const row = document.createElement("div");
      row.className = "jobpipe-visual-hide-rule";
      const name = document.createElement("span");
      name.textContent = company;
      row.append(name, createButton("Unblock", async () => {
        await persist({
          ...state,
          blockedCompanies: state.blockedCompanies.filter((value) => value !== company)
        });
        renderRules();
      }));
      list.append(row);
    }
    const count = document.createElement("p");
    count.textContent = `Individually hidden postings: ${state.hiddenPostingIds.length} (stored by LinkedIn ID, not job URL)`;
    list.append(count);
    list.append(createButton("Clear hidden postings", async () => {
      await persist({ ...state, hiddenPostingIds: [] });
      renderRules();
    }, state.hiddenPostingIds.length === 0));
    const countApplied = document.createElement("p");
    countApplied.textContent = "User-reported applied postings: " + state.appliedPostingIds.length + " (not ATS-verified)";
    list.append(countApplied);
    list.append(createButton("Clear applied imports", async () => {
      await persist({ ...state, appliedPostingIds: [] });
      renderRules();
    }, state.appliedPostingIds.length === 0));
    const backupCount = document.createElement("p");
    backupCount.textContent = "Private history hashes: " +
      (state.historyAppliedHashes.length + state.historyDismissedHashes.length) +
      " (browser-local, not submission verification)";
    list.append(backupCount);
    list.append(createButton("Clear Jobpipe backup", async () => {
      await persist({ ...state, historyAppliedHashes: [], historyDismissedHashes: [] });
      renderRules();
    }, state.historyAppliedHashes.length + state.historyDismissedHashes.length === 0));
  }

  function mountPanel() {
    if (panel || !document.body) return;
    panel = document.createElement("aside");
    panel.id = "jobpipe-visual-hide-panel";
    panel.setAttribute("aria-label", "jobpipe optional LinkedIn filtering");
    // Static, trusted markup only; employer text is always textContent.
    panel.innerHTML = `
      <div class="jobpipe-visual-hide-title">jobpipe · Local hide</div>
      <div class="jobpipe-visual-hide-status" role="status">Checking visible cards</div>
      <div class="jobpipe-visual-hide-toolbar">
        <button type="button" class="jobpipe-visual-hide-show">Show matched</button>
        <button type="button" class="jobpipe-visual-hide-undo" disabled>Undo</button>
        <button type="button" class="jobpipe-visual-hide-review">Review blocked</button>
        <button type="button" class="jobpipe-visual-hide-export" disabled>Export dismissals</button>
        <button type="button" class="jobpipe-visual-hide-import">Import applied CSV</button>
        <button type="button" class="jobpipe-visual-hide-backup">Import Jobpipe backup</button>
      </div>
      <section class="jobpipe-visual-hide-review-list" hidden></section>
      <p class="jobpipe-visual-hide-note">Browser-local visibility only. Import explicit APPLIED URLs or a private SHA-256 Jobpipe history export. Imported backup hashes remain local and can identify your job history. No verified submissions, automatic sync, or applications.</p>`;
    document.body.append(panel);
    const fileInput = document.createElement("input");
    fileInput.type = "file";
    fileInput.accept = ".csv,text/csv";
    fileInput.hidden = true;
    fileInput.className = "jobpipe-visual-hide-import-input";
    panel.append(fileInput);
    panel.querySelector(".jobpipe-visual-hide-import").addEventListener("click", () => fileInput.click());
    const backupInput = document.createElement("input");
    backupInput.type = "file";
    backupInput.accept = ".csv,text/csv";
    backupInput.hidden = true;
    backupInput.className = "jobpipe-visual-hide-backup-input";
    panel.append(backupInput);
    panel.querySelector(".jobpipe-visual-hide-backup").addEventListener("click", () => backupInput.click());
    backupInput.addEventListener("change", async () => {
      const file = backupInput.files?.[0];
      backupInput.value = "";
      if (!file) return;
      try {
        if (file.size > 2000000 || !globalThis.crypto?.subtle) throw new Error("Private hash validation unavailable");
        const hashes = rules.parsePrivateHistoryCsv(await file.text());
        await persist({ ...state, ...hashes });
        panel.querySelector(".jobpipe-visual-hide-status").textContent =
          "Imported Jobpipe hash backup locally. User-reported history only.";
      } catch {
        panel.querySelector(".jobpipe-visual-hide-status").textContent =
          "Jobpipe backup rejected. Use exact identity_hash,status,recorded_at export.";
      }
    });
    fileInput.addEventListener("change", async () => {
      const file = fileInput.files?.[0];
      fileInput.value = "";
      if (!file) return;
      try {
        if (file.size > 256000) throw new Error("CSV exceeds local limit");
        const ids = rules.parseAppliedHistoryCsv(await file.text());
        const merged = Array.from(new Set([...state.appliedPostingIds, ...ids]));
        if (merged.length > 2000) throw new Error("Too many applied postings");
        await persist({ ...state, appliedPostingIds: merged });
        panel.querySelector(".jobpipe-visual-hide-status").textContent =
          ids.length + " user-reported applied posting(s) imported. Not ATS-verified.";
      } catch {
        panel.querySelector(".jobpipe-visual-hide-status").textContent =
          "CSV rejected. Use job_url,status with only LinkedIn jobs/view URLs and APPLIED statuses.";
      }
    });
    panel.querySelector(".jobpipe-visual-hide-show").addEventListener("click", () => {
      showHidden = !showHidden;
      refresh();
    });
    panel.querySelector(".jobpipe-visual-hide-undo").addEventListener("click", async () => {
      if (!undoState) return;
      const previous = undoState;
      undoState = null;
      await persist(previous);
      undoState = null;
      refresh();
    });
    panel.querySelector(".jobpipe-visual-hide-export").addEventListener("click", () => {
      // Explicit, user-triggered file download. Never upload or auto-import.
      // The CSV intentionally omits company names, titles, and all profile data.
      if (!state.hiddenPostingIds.length) return;
      const contents = rules.dismissedHistoryCsv(state);
      const blob = new Blob([contents], { type: "text/csv;charset=utf-8" });
      const blobUrl = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.download = "jobpipe-linkedin-dismissed.csv";
      anchor.href = blobUrl;
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(blobUrl), 15000);
    });
    panel.querySelector(".jobpipe-visual-hide-review").addEventListener("click", () => {
      const list = panel.querySelector(".jobpipe-visual-hide-review-list");
      list.hidden = !list.hidden;
      if (!list.hidden) renderRules();
    });
  }

  function scheduleRefresh() {
    if (scheduled) return;
    scheduled = true;
    window.requestAnimationFrame(() => {
      scheduled = false;
      mountPanel();
      refresh();
    });
  }

  async function initialize() {
    try {
      const stored = await storage.storage.local.get(KEY);
      state = rules.sanitizeState(stored?.[KEY]);
    } catch {
      // No storage approval: never infer or persist any user preference.
      state = rules.sanitizeState({});
    }
    mountPanel();
    scheduleRefresh();
    const observer = new MutationObserver((changes) => {
      if (changes.some((change) => {
        return !panel?.contains(change.target)
          && change.addedNodes.length + change.removedNodes.length > 0;
      })) scheduleRefresh();
    });
    observer.observe(document.body, { childList: true, subtree: true });
    if (storage.storage.onChanged?.addListener) {
      storage.storage.onChanged.addListener((changes, area) => {
        if (area !== "local" || !changes[KEY]) return;
        state = rules.sanitizeState(changes[KEY].newValue);
        lastSummary = "";
        renderRules();
        scheduleRefresh();
      });
    }
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    void initialize();
  }
})();
