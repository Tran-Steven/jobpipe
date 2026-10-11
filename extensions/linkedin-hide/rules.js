"use strict";
/* Pure, no-network LinkedIn card identity and privacy rules. */
(function (root) {
  const COMPANY_LIMIT = 500, ID_LIMIT = 2000;
  function normalizeCompany(value) {
    if (typeof value !== "string") return "";
    const name = value.normalize("NFKC").replace(/\s+/g, " ").trim().toLocaleLowerCase("en-US");
    return name.length <= 160 ? name : "";
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
    const directId = normalizeId(match?.[1]);
    const queryId = url.pathname.startsWith("/jobs/") ? normalizeId(url.searchParams.get("currentJobId")) : "";
    if (directId && queryId && directId !== queryId) return "";
    return directId || queryId;
  }
  function jobIdFromCard(card) {
    const ids = [];
    for (const key of ["data-job-id", "data-occludable-job-id"]) {
      const id = normalizeId(card.getAttribute(key));
      if (id) ids.push(id);
    }
    for (const node of card.querySelectorAll("[data-job-id], [data-occludable-job-id]")) {
      for (const key of ["data-job-id", "data-occludable-job-id"]) {
        const id = normalizeId(node.getAttribute(key));
        if (id) ids.push(id);
      }
    }
    for (const anchor of card.querySelectorAll('a[href*="/jobs/view/"], a[href*="currentJobId="]')) {
      const href = anchor.getAttribute("href") || "";
      const id = jobIdFromUrl(href);
      if (id) ids.push(id);
      else if (/\/jobs\/view\/|currentJobId=/.test(href)) return "";
    }
    return ids.length && ids.every((id) => id === ids[0]) ? ids[0] : "";
  }
  function companyFromCard(card) {
    const selectors = [
      ".job-card-container__company-name", ".job-card-container__primary-description",
      ".artdeco-entity-lockup__subtitle", ".job-card-container__subtitle",
      '[data-job-company]'
    ];
    const companies = [];
    for (const selector of selectors) {
      const element = card.querySelector(selector);
      if (!element) continue;
      const company = normalizeCompany(element.getAttribute("data-job-company") || element.textContent);
      if (company) companies.push(company);
    }
    return companies.length && companies.every((company) => company === companies[0]) ? companies[0] : "";
  }
  function sanitizeState(input) {
    const value = input && typeof input === "object" ? input : {};
    const blocked = Array.isArray(value.blockedCompanies) ? value.blockedCompanies : [];
    const dismissed = Array.isArray(value.hiddenPostingIds) ? value.hiddenPostingIds : [];
    const applied = Array.isArray(value.appliedPostingIds) ? value.appliedPostingIds : [];
    return {
      blockedCompanies: Array.from(new Set(blocked.map(normalizeCompany).filter(Boolean))).slice(0, COMPANY_LIMIT),
      hiddenPostingIds: Array.from(new Set(dismissed.map(normalizeId).filter(Boolean))).slice(0, ID_LIMIT),
      appliedPostingIds: Array.from(new Set(applied.map(normalizeId).filter(Boolean))).slice(0, ID_LIMIT)
    };
  }
  function whyHidden(card, state) {
    const employer = companyFromCard(card), id = jobIdFromCard(card);
    if (employer && state.blockedCompanies.includes(employer)) return "blocked-company";
    if (id && state.appliedPostingIds.includes(id)) return "user-reported-applied";
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
  function parseAppliedHistoryCsv(value) {
    if (typeof value !== "string" || value.length > 256000) throw new Error("Invalid CSV size");
    const lines = value.replace(/^\uFEFF/, "").split(/\r?\n/);
    if (lines.at(-1) === "") lines.pop();
    if (lines.shift() !== "job_url,status" || lines.length < 1 || lines.length > ID_LIMIT) {
      throw new Error("Invalid applied-history CSV shape");
    }
    const ids = new Set();
    for (const line of lines) {
      const fields = line.split(",");
      if (fields.length !== 2 || fields[1] !== "APPLIED") {
        throw new Error("Only explicit APPLIED rows are accepted");
      }
      const source = fields[0];
      if (!source.startsWith("https://")) throw new Error("Invalid LinkedIn posting URL");
      let url;
      try { url = new URL(source); } catch { throw new Error("Invalid LinkedIn posting URL"); }
      if (!/^\/jobs\/view\/[0-9]{1,32}\/?$/.test(url.pathname)) {
        throw new Error("Invalid LinkedIn posting URL");
      }
      const id = jobIdFromUrl(source);
      if (!id) throw new Error("Invalid LinkedIn posting ID");
      ids.add(id);
    }
    return Array.from(ids);
  }
  const api = Object.freeze({ normalizeCompany, normalizeId, jobIdFromUrl, jobIdFromCard, companyFromCard, sanitizeState, whyHidden, dismissedHistoryCsv, parseAppliedHistoryCsv });
  root.JobpipeLinkedInRules = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
})(typeof globalThis === "object" ? globalThis : this);
