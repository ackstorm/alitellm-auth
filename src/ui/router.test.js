// router.test.js — vitest unit suite for the PURE resolveRoute() allow-list.
//
// Mirrors the state.test.js style (describe/it/expect, default node env, no
// jsdom) because resolveRoute touches no window/document/fetch. The useHashRoute
// hook (which reads window.location.hash) is intentionally NOT exercised here —
// only the pure route-resolution logic is unit-tested (09-05 plan, behavior
// cases + threat T-09-13 allow-list).
import { describe, it, expect } from "vitest";
import { resolveRoute, ROUTES } from "./router.js";

describe("resolveRoute — pure hash allow-list", () => {
  it('default "#/" -> dashboard', () => {
    expect(resolveRoute("#/")).toBe("dashboard");
  });

  it("empty hash on first load -> dashboard", () => {
    expect(resolveRoute("")).toBe("dashboard");
    expect(resolveRoute(null)).toBe("dashboard");
    expect(resolveRoute(undefined)).toBe("dashboard");
  });

  it('bare "#" -> dashboard', () => {
    expect(resolveRoute("#")).toBe("dashboard");
  });

  it('"#/stats" -> stats', () => {
    expect(resolveRoute("#/stats")).toBe("stats");
  });

  it("unknown route falls back to the default dashboard", () => {
    expect(resolveRoute("#/anything-unknown")).toBe("dashboard");
    expect(resolveRoute("#/keys")).toBe("dashboard");
  });

  it("attacker-supplied hash can never select an unknown view (T-09-13 allow-list)", () => {
    // None of these are in ROUTES -> all fall back to dashboard; the hash is
    // never used as a redirect target.
    expect(resolveRoute("#/javascript:alert(1)")).toBe("dashboard");
    expect(resolveRoute("#//evil.com")).toBe("dashboard");
    expect(resolveRoute("#/../../etc/passwd")).toBe("dashboard");
  });

  it("is pure — same input always yields the same output", () => {
    expect(resolveRoute("#/stats")).toBe(resolveRoute("#/stats"));
    expect(resolveRoute("#/x")).toBe(resolveRoute("#/x"));
  });

  it("ROUTES maps exactly the two known hashes", () => {
    expect(ROUTES["#/"]).toBe("dashboard");
    expect(ROUTES["#/stats"]).toBe("stats");
    expect(Object.keys(ROUTES)).toHaveLength(2);
  });
});
