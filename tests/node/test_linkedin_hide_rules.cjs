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
  assert.equal(state.blockedCompanies.length, 1);
  assert.equal(rules.normalizeCompany("x".repeat(161)), "");
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

test("user-reported applied CSV is atomic, explicit and limited to native job URLs", () => {
  const ids = rules.parseAppliedHistoryCsv(
    "\uFEFFjob_url,status\r\nhttps://www.linkedin.com/jobs/view/101,APPLIED\r\n" +
    "https://linkedin.com/jobs/view/202/,APPLIED\r\n" +
    "https://www.linkedin.com/jobs/view/101,APPLIED\r\n"
  );
  assert.deepEqual(ids, ["101", "202"]);
  const state = rules.sanitizeState({ appliedPostingIds: ids, hiddenPostingIds: ["303"] });
  assert.equal(rules.whyHidden(card({ company: "Acme", id: "101" }), state), "user-reported-applied");
  assert.equal(rules.whyHidden(card({ company: "Acme", id: "303" }), state), "dismissed-posting");
  assert.equal(rules.whyHidden(card({ company: "Acme", id: "404" }), state), "");
  assert.deepEqual(rules.sanitizeState({}).appliedPostingIds, []);
});

test("malformed and ambiguous CSV never partially imports or claims verified submission", () => {
  const bad = [
    "job_url,status\nhttps://www.linkedin.com/jobs/view/12,SUBMITTED_VERIFIED\n",
    "job_url,status\nhttps://www.linkedin.com/jobs/view/12,DISMISSED\n",
    "job_url,status\nhttps://evil.test/jobs/view/12,APPLIED\n",
    "job_url,status\nhttps://www.linkedin.com.evil.test/jobs/view/12,APPLIED\n",
    "job_url,status\nhttps://www.linkedin.com/jobs/search/?currentJobId=12,APPLIED\n",
    "job_url,status\nhttps://www.linkedin.com/jobs/view/12?currentJobId=13,APPLIED\n",
    "job_url,status\nhttps://www.linkedin.com/jobs/view/12,APPLIED,malicious\n",
    "job_url,status\nhttps://user:pass@www.linkedin.com/jobs/view/12,APPLIED\n",
    "job_url,status\nhttps://www.linkedin.com/jobs/view/12,APPLIED\nhttps://evil.test/jobs/view/22,APPLIED\n",
    "job_url,status\n",
    "job_url,status\n" + "https://www.linkedin.com/jobs/view/12,APPLIED\n".repeat(2001),
    "x".repeat(256001)
  ];
  for (const csv of bad) assert.throws(() => rules.parseAppliedHistoryCsv(csv));
});

test("conflicting card attributes and job links never hide the wrong posting", () => {
  const conflicting = {
    getAttribute: (key) => key === "data-job-id" ? "101" : key === "data-occludable-job-id" ? "102" : null,
    querySelector: () => null,
    querySelectorAll: () => []
  };
  const state = rules.sanitizeState({ appliedPostingIds: ["101"], hiddenPostingIds: ["102"] });
  assert.equal(rules.jobIdFromCard(conflicting), "");
  assert.equal(rules.whyHidden(conflicting, state), "");
  const doubleLink = {
    getAttribute: () => null,
    querySelector: () => null,
    querySelectorAll: (selector) => selector.startsWith("a[") ?
      ["/jobs/view/101", "/jobs/view/102"].map((href) => ({ getAttribute: () => href })) : []
  };
  assert.equal(rules.jobIdFromCard(doubleLink), "");
  assert.equal(rules.whyHidden(doubleLink, state), "");
  assert.equal(rules.jobIdFromUrl("https://www.linkedin.com/feed/?currentJobId=101"), "");
});

test("contradictory employer labels and excessively long names do not produce company blocks", () => {
  const state = rules.sanitizeState({ blockedCompanies: ["Acme"] });
  const ambiguous = {
    getAttribute: () => null,
    querySelector: (selector) => selector === ".job-card-container__company-name" ?
      { textContent: "Acme", getAttribute: () => null } :
      selector === ".job-card-container__primary-description" ?
      { textContent: "Other", getAttribute: () => null } : null,
    querySelectorAll: () => []
  };
  assert.equal(rules.companyFromCard(ambiguous), "");
  assert.equal(rules.whyHidden(ambiguous, state), "");
  assert.equal(rules.normalizeCompany("Acme" + "x".repeat(200)), "");
});

test("Jobpipe hash-only export uses exact Python-compatible LinkedIn URL identity", () => {
  const crypto = require("node:crypto");
  const identity = rules.linkedInCanonicalIdentity("101");
  assert.equal(identity, "https://linkedin.com/jobs/view/101");
  assert.equal(
    crypto.createHash("sha256").update(identity, "utf8").digest("hex"),
    "192468cc5c97be0781e1f586714fd09d31780cc5210618213c71bb85129c9465"
  );
  assert.equal(rules.linkedInCanonicalIdentity("not-numeric"), "");
  const csv = "identity_hash,status,recorded_at\r\n" +
    "192468cc5c97be0781e1f586714fd09d31780cc5210618213c71bb85129c9465,APPLIED_SELF_REPORTED,2026-10-10T19:38:00+00:00\r\n" +
    "e8659817d5aac604501069f0b8bdfb8147cd2cb861d327a7a741cb4ded189c10,DISMISSED,2026-10-10T19:38:01Z\r\n";
  const parsed = rules.parsePrivateHistoryCsv(csv);
  const state = rules.sanitizeState(parsed);
  assert.deepEqual(state.historyAppliedHashes, ["192468cc5c97be0781e1f586714fd09d31780cc5210618213c71bb85129c9465"]);
  assert.deepEqual(state.historyDismissedHashes, ["e8659817d5aac604501069f0b8bdfb8147cd2cb861d327a7a741cb4ded189c10"]);
  assert.equal(rules.whyHidden(card({ id: "101" }), state, state.historyAppliedHashes[0]), "private-history-applied");
  assert.equal(rules.whyHidden(card({ id: "102" }), state, state.historyDismissedHashes[0]), "private-history-dismissed");
  assert.equal(rules.whyHidden(card({ id: "103" }), state, ""), "");
});

test("hash backup rejects forged statuses, conflicting duplicates and malformed fields", () => {
  const a = "192468cc5c97be0781e1f586714fd09d31780cc5210618213c71bb85129c9465";
  const header = "identity_hash,status,recorded_at\n";
  const row = (hash, status, date = "2026-10-10T19:38:00+00:00") => [hash, status, date].join(",") + "\n";
  const bad = [
    header,
    header + row(a, "SUBMITTED_VERIFIED"),
    header + row(a, "APPLIED"),
    header + row(a.toUpperCase(), "DISMISSED"),
    header + row(a, "APPLIED_SELF_REPORTED", "2026-10-10"),
    header + row(a, "APPLIED_SELF_REPORTED", "not-a-date"),
    header + row(a, "APPLIED_SELF_REPORTED") + row(a, "DISMISSED"),
    "job_url,status\nhttps://www.linkedin.com/jobs/view/101,APPLIED\n",
    header + row(a, "DISMISSED") + "malformed-line\n",
    header + row(a, "DISMISSED").repeat(10001),
    "a".repeat(2000001)
  ];
  for (const item of bad) assert.throws(() => rules.parsePrivateHistoryCsv(item));
  assert.deepEqual(rules.sanitizeState({historyAppliedHashes: ["A".repeat(64)],historyDismissedHashes:["not-a-hash"]}).historyAppliedHashes, []);
  const same = rules.parsePrivateHistoryCsv(header + row(a, "DISMISSED") + row(a, "DISMISSED"));
  assert.deepEqual(same.historyDismissedHashes, [a]);
});
