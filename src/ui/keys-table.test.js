// keys-table.test.js — FID-04 regression suite (Phase 14 Plan 03, D-15).
//
// Runs in the default vitest node environment (no jsdom, no DOM) — mirrors the
// format.test.js / charts.test.js / state.test.js discipline. It exercises the
// PURE row-selection + status-computation logic that gates whether a `/keys`
// payload reaches the populated table, WITHOUT rendering Preact components (the
// Registry-Safety rule forbids adding a jsdom/testing-library dependency).
//
// WHY this suite exists (FID-04 triage, D-15): the reported "keys already
// generated not displaying" item. Triage walked the data path end-to-end:
//   session_list_keys -> {keys:[...]} (safe projection) -> dashboard.loadKeys
//   (status===200 && Array.isArray(data.keys)) -> KeysTable selectKeyRows guard
//   -> populated/empty/loading/error branches.
// The data path is CORRECT: a well-formed `{keys:[...]}` payload yields its rows;
// only a genuinely empty list yields the empty state. Conclusion = path (b):
// EXPECTED-EMPTY data on the new api.new.ackstorm.ai instance (the user has no
// keys there yet), NOT a render bug. These tests LOCK that the data path stays
// correct so a future regression (e.g. an Array.isArray guard rejecting a valid
// payload) is caught.
import { describe, it, expect } from "vitest";
import { selectKeyRows, isRevoked, isExpired } from "./keys-table.js";

// A representative `/keys` payload in the backend's _project_session_key shape
// (src/api/app/litellm_client.py:387-405): id, key_alias, spend, budget,
// tpm_limit, rpm_limit, models, created_at, expires. No revoked/blocked flag
// (absence == active).
const PAYLOAD = [
  {
    id: "key-abc123",
    key_alias: "ci-runner",
    spend: 12.5,
    budget: null,
    tpm_limit: 1000000,
    rpm_limit: 100,
    models: ["all-team-models"],
    created_at: "2026-03-01T10:00:00+00:00",
    expires: null,
  },
  {
    id: "key-def456",
    key_alias: null,
    spend: 0,
    budget: null,
    tpm_limit: null,
    rpm_limit: null,
    models: null,
    created_at: "2026-02-01T08:00:00+00:00",
    expires: "2099-01-01T00:00:00+00:00",
  },
];

describe("FID-04 — selectKeyRows (the populated-vs-empty render gate)", () => {
  it("returns the rows verbatim for a representative populated /keys payload", () => {
    const rows = selectKeyRows(PAYLOAD);
    expect(rows).toHaveLength(2);
    expect(rows[0].id).toBe("key-abc123");
    // Same array reference passed through — no shape mutation, no row dropping.
    expect(rows).toBe(PAYLOAD);
  });

  it("returns an empty array for the genuinely-empty case (expected-empty, path b)", () => {
    expect(selectKeyRows([])).toEqual([]);
  });

  it("coerces a non-array payload to an empty array (never throws)", () => {
    expect(selectKeyRows(null)).toEqual([]);
    expect(selectKeyRows(undefined)).toEqual([]);
    expect(selectKeyRows({ keys: PAYLOAD })).toEqual([]); // a stray object, not the keys array
  });
});

describe("FID-04 / D-08 — status computation against representative rows", () => {
  it("treats a row with no revoked/blocked flag as active (not revoked, not expired)", () => {
    expect(isRevoked(PAYLOAD[0])).toBe(false);
    expect(isExpired(PAYLOAD[0])).toBe(false); // expires null -> never expired
  });

  it("computes Expired only when expires is in the past", () => {
    const past = { id: "k1", expires: "2000-01-01T00:00:00+00:00" };
    const future = { id: "k2", expires: "2099-01-01T00:00:00+00:00" };
    expect(isExpired(past)).toBe(true);
    expect(isExpired(future)).toBe(false);
  });

  it("Revoked takes precedence — a revoked row is never reported as expired here", () => {
    const revokedAndPast = { id: "k3", revoked: true, expires: "2000-01-01T00:00:00+00:00" };
    expect(isRevoked(revokedAndPast)).toBe(true);
    // isExpired still returns true on the raw date; KeyRow gates Expired on
    // !revoked so the rendered pill is Revoked. This asserts the precedence
    // inputs the row uses, matching KeyRow's `!revoked && isExpired(k)`.
    expect(isExpired(revokedAndPast)).toBe(true);
  });

  it("honors the blocked flag as revoked (backend block)", () => {
    expect(isRevoked({ id: "k4", blocked: true })).toBe(true);
  });
});
