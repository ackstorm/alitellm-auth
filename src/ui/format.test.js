// format.test.js — vitest unit suite for the pure display formatters in
// format.js. Runs in the default node environment (no jsdom) because every
// formatter is pure (no DOM/network refs) — mirrors state.test.js discipline.
//
// The locked display strings come from 10-UI-SPEC §Typography
// ("Table number formatting" + "Metric-tile number sizing"): currency to 2
// decimals with thousands separators, integers thousands-grouped, abbreviated
// 2.45M, MMM DD, YYYY dates, sk-…last4 masks, and the em-dash "—" (U+2014) for
// every null/undefined input.
import { describe, it, expect } from "vitest";
import {
  formatCurrency,
  formatInt,
  abbreviate,
  formatDate,
  maskKey,
} from "./format.js";

const EM_DASH = "—"; // — (U+2014)

describe("formatCurrency — USD, 2 decimals, thousands separators", () => {
  it("formats a fractional value to 2 decimals with grouping", () => {
    expect(formatCurrency(1249.5)).toBe("$1,249.50");
  });

  it("formats zero as $0.00", () => {
    expect(formatCurrency(0)).toBe("$0.00");
  });

  it("rounds to 2 decimals", () => {
    expect(formatCurrency(1249.499)).toBe("$1,249.50");
  });

  it("returns the em-dash for null/undefined", () => {
    expect(formatCurrency(null)).toBe(EM_DASH);
    expect(formatCurrency(undefined)).toBe(EM_DASH);
  });

  it("does not throw on a non-numeric input", () => {
    expect(() => formatCurrency("x")).not.toThrow();
    expect(formatCurrency("x")).toBe(EM_DASH);
  });
});

describe("formatInt — thousands-grouped integers", () => {
  it("groups millions with separators", () => {
    expect(formatInt(1000000)).toBe("1,000,000");
  });

  it("formats zero as 0", () => {
    expect(formatInt(0)).toBe("0");
  });

  it("returns the em-dash for null/undefined", () => {
    expect(formatInt(null)).toBe(EM_DASH);
    expect(formatInt(undefined)).toBe(EM_DASH);
  });

  it("does not throw on a non-numeric input", () => {
    expect(() => formatInt("x")).not.toThrow();
    expect(formatInt("x")).toBe(EM_DASH);
  });
});

describe("abbreviate — K/M/B suffixes, up to 2 decimals trimmed", () => {
  it("abbreviates millions", () => {
    expect(abbreviate(2450000)).toBe("2.45M");
  });

  it("abbreviates thousands", () => {
    expect(abbreviate(1500)).toBe("1.5K");
  });

  it("leaves values below 1000 unabbreviated", () => {
    expect(abbreviate(950)).toBe("950");
  });

  it("abbreviates billions", () => {
    expect(abbreviate(2450000000)).toBe("2.45B");
  });

  it("trims trailing zeros (whole thousands)", () => {
    expect(abbreviate(2000)).toBe("2K");
  });

  it("returns the em-dash for null/undefined", () => {
    expect(abbreviate(null)).toBe(EM_DASH);
    expect(abbreviate(undefined)).toBe(EM_DASH);
  });

  it("does not throw on a non-numeric input", () => {
    expect(() => abbreviate("x")).not.toThrow();
    expect(abbreviate("x")).toBe(EM_DASH);
  });
});

describe("formatDate — MMM DD, YYYY", () => {
  it("formats an ISO timestamp to MMM DD, YYYY (zero-padded day)", () => {
    expect(formatDate("2026-03-01T10:00:00+00:00")).toBe("Mar 01, 2026");
  });

  it("zero-pads single-digit days", () => {
    expect(formatDate("2026-12-05T00:00:00+00:00")).toBe("Dec 05, 2026");
  });

  it("returns the em-dash for null/undefined", () => {
    expect(formatDate(null)).toBe(EM_DASH);
    expect(formatDate(undefined)).toBe(EM_DASH);
  });

  it("returns the em-dash for an unparseable date (never throws)", () => {
    expect(() => formatDate("not-a-date")).not.toThrow();
    expect(formatDate("not-a-date")).toBe(EM_DASH);
  });
});

describe("maskKey — sk-…last4", () => {
  it("masks a key to sk-…last4 using the ellipsis char", () => {
    expect(maskKey("sk-abcd1234wxyz")).toBe("sk-…wxyz");
  });

  it("returns the em-dash for null/undefined", () => {
    expect(maskKey(null)).toBe(EM_DASH);
    expect(maskKey(undefined)).toBe(EM_DASH);
  });

  it("does not throw on a short string", () => {
    expect(() => maskKey("ab")).not.toThrow();
  });
});
