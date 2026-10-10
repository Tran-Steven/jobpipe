"use strict";
/* Pure, no-network LinkedIn card identity and privacy rules. */
(function (root) {
  const COMPANY_LIMIT = 500, ID_LIMIT = 2000;
  function normalizeCompany(value) {
    if (typeof value !== "string") return "";
    return value.normalize("NFKC").replace(/\s+/g, " ").trim().toLocaleLowerCase("en-US").slice(0, 160);
  }
  function normalizeId(value) {
    const id = String(value ?? "").trim();
    return /^[0-9]{1,32}$/.test(id) ? id : "";
  }
  function jobIdFromUrl(value) {
    if (typeof value !== "string" || value.length > 2048) return "";
    let url;
    try { url = new URL(value, "https://www.linkedin.com/"); } catch { return ""; }
    if (url.protocol !== "https:" || url.username || url.password || url.port || !["www.linkedin.com", "linkedin.com"].includes(url.hostname)) return "";
    const match = url.pathname.match(/^\/jobs\/view\/([0-9]{1,32})(?:\/|$)/);
    return normalizeId(match ? match[1] : url.searchParams.get("currentJobId"));
  }
  function jobIdFromCard(card) {
    for (const key of ["data-job-id", "data-occludable-job-id"]) {
      const value = normalizeId(card.getAttribute(key));
      if (value) return value;
    }
    const nested = card.querySelector("[data-job-id], [data-occludable-job-id]");
    if (nested) {
      const id = normalizeId(nested.getAttribute("data-job-id") || nested.getAttribute("data-occludable-job-id"));
      if (id) return id;
    }
    for (const anchor of card.querySelectorAll('a[href*="/jobs/view/"], a[href*="currentJobId="]')) {
      const id = jobIdFromUrl(anchor.getAttribute("href") || "");
      if (id) return id;
    }
    return "";
  }
  function companyFromCard(card) {
    const selectors = [
      ".job-card-container__company-name", ".job-card-container__primary-description",
      ".artdeco-entity-lockup__subtitle", ".job-card-container__subtitle",
      '[data-job-company]'
    ];
    for (const selector of selectors) {
      const element = card.querySelector(selector);
      const company = normalizeCompany(element && (element.getAttribute("data-job-company") || element.textContent));
      if (company) return company;
    }
    return "";
  }
  function sanitizeState(input) {
    const value = input && typeof input === "object" ? input : {};
    const blocked = Array.isArray(value.blockedCompanies) ? value.blockedCompanies : [];
    const dismissed = Array.isArray(value.hiddenPostingIds) ? value.hiddenPostingIds : [];
    return {
      blockedCompanies: Array.from(new Set(blocked.map(normalizeCompany).filter(Boolean))).slice(0, COMPANY_LIMIT),
      hiddenPostingIds: Array.from(new Set(dismissed.map(normalizeId).filter(Boolean))).slice(0, ID_LIMIT)
    };
  }
  function whyHidden(card, state) {
    const employer = companyFromCard(card), id = jobIdFromCard(card);
    if (employer && state.blockedCompanies.includes(employer)) return "blocked-company";
    if (id && state.hiddenPostingIds.includes(id)) return "dismissed-posting";
    return "";
  }
  function dismissedHistoryCsv(input) {
    // User-triggered offline export only. Never infer APPLIED from Hide/X.
    // Numeric IDs make CSV-injection and embedded credential data impossible.
    // Company blocks are not dismissal events and are not exported.
    const state = sanitizeState(input);
    const lines = ["job_url,status"];
    for (const id of state.hiddenPostingIds) {
      lines.push("https://www.linkedin.com/jobs/view/" + id + ",DISMISSED");
    }
    return lines.join("\r\n") + "\r\n";
  }
  const api = Object.freeze({ normalizeCompany, normalizeId, jobIdFromUrl, jobIdFromCard, companyFromCard, sanitizeState, whyHidden, dismissedHistoryCsv });
  root.JobpipeLinkedInRules = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis === "object" ? globalThis : this);
