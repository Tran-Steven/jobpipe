"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const rules = require("../../extensions/linkedin-hide/rules.js");

function card({ company, id, href } = {}) {
  return {
    getAttribute(key) {
      if (key === "data-job-id") return id ?? null;
      return null;
    },
    querySelector(selector) {
      if (selector.includes("data-job-id")) return null;
      if (selector.includes("company-name") && company) {
        return { textContent: company, getAttribute: () => null };
      }
      return null;
    },
    querySelectorAll() {
      return href ? [{ getAttribute: () => href }] : [];
    }
  };
}

test("normalizes only exact employer names without invented fuzzy aliases", () => {
  assert.equal(rules.normalizeCompany("  ACME\t  Inc.  "), "acme inc.");
  assert.equal(rules.normalizeCompany(""), "");
  const state = rules.sanitizeState({
    blockedCompanies: ["Acme, Inc.", "ACME, INC.", "Acme"],
    hiddenPostingIds: ["123", "123", "bad", 1234]
  });
  assert.deepEqual(state.blockedCompanies, ["acme, inc.", "acme"]);
  assert.deepEqual(state.hiddenPostingIds, ["123", "1234"]);
  assert.equal(rules.whyHidden(card({company:"Acme",id:"999"}),state),"blocked-company");
  assert.equal(rules.whyHidden(card({company:"Acme, Inc",id:"999"}),state),"");
});

test("LinkedIn numeric IDs accepted only from exact official HTTPS host", () => {
  assert.equal(rules.jobIdFromUrl("https://www.linkedin.com/jobs/view/1234567890/"), "1234567890");
  assert.equal(rules.jobIdFromUrl("/jobs/search/?currentJobId=100200"), "100200");
  for (const bad of [
    "https://www.linkedin.com.evil.test/jobs/view/123",
    "https://evil.test/jobs/view/123",
    "http://www.linkedin.com/jobs/view/123",
    "javascript:alert(1)",
    "https://www.linkedin.com/jobs/view/foo",
    "https://www.linkedin.com/jobs/search/?currentJobId=not-numeric",
    "https://user:pass@www.linkedin.com/jobs/view/123",
  ]) {
    assert.equal(rules.jobIdFromUrl(bad), "", bad);
  }
});

test("card state uses only native numeric identity, never job title inference", () => {
  const state = rules.sanitizeState({
    hiddenPostingIds: ["9988"], blockedCompanies: []
  });
  assert.equal(rules.whyHidden(card({company:"Example",id:"9988"}),state),"dismissed-posting");
  assert.equal(rules.whyHidden(card({company:"Example",id:"9977"}),state),"");
  assert.equal(rules.whyHidden(card({company:"Example",href:"/jobs/view/9988"}),state),"dismissed-posting");
  assert.equal(rules.whyHidden(card({company:"Example",href:"https://evil.test/jobs/view/9988"}),state),"");
});

test("malformed and oversize saved values are discarded and bounded", () => {
  const state = rules.sanitizeState({
    blockedCompanies: [null, {}, "Company", "Company", "x".repeat(800)],
    hiddenPostingIds: ["100", "000", "-1", "1".repeat(100), undefined]
  });
  assert.equal(state.blockedCompanies.length, 2);
  assert.equal(state.blockedCompanies[1].length,160);
  assert.deepEqual(state.hiddenPostingIds, ["100", "000"]);
  const long = rules.sanitizeState({
    blockedCompanies: Array.from({ length: 700 }, (_,i) => "company" + i),
    hiddenPostingIds: Array.from({ length: 3000 }, (_,i) => String(i))
  });
  assert.equal(long.blockedCompanies.length,500);
  assert.equal(long.hiddenPostingIds.length,2000);
});


test("explicit dismissal export contains only verified numeric job IDs, never inferred APPLIED", () => {
  const csv = rules.dismissedHistoryCsv({
    blockedCompanies: ["Secret Staffing Corp", "Private Employer"],
    hiddenPostingIds: ["101", "102", "101", "=HYPERLINK(1)", "abc"]
  });
  assert.equal(csv,
    "job_url,status\r\n" +
    "https://www.linkedin.com/jobs/view/101,DISMISSED\r\n" +
    "https://www.linkedin.com/jobs/view/102,DISMISSED\r\n");
  assert.ok(!csv.includes("APPLIED"));
  assert.ok(!csv.includes("Secret Staffing"));
  assert.ok(!csv.includes("Private Employer"));
  assert.ok(!csv.includes("=HYPERLINK"));
});

test("no individual dismissal exports only CSV headers, not whole blocked companies", () => {
  assert.equal(
    rules.dismissedHistoryCsv({ blockedCompanies: ["Sensitive Firm"], hiddenPostingIds: [] }),
    "job_url,status\r\n"
  );
  assert.ok(!rules.dismissedHistoryCsv({hiddenPostingIds: ["0"]}).includes("www.linkedin.com.evil"));
});
