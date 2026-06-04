// charts.test.js — vitest unit suite for the PURE `seriesToUplot` transform in
// charts.js. Runs in the default node environment (no jsdom, no uPlot) because
// `seriesToUplot` is pure (no DOM, no uPlot import) — mirrors format.test.js /
// state.test.js discipline.
//
// Contract (13-02-PLAN <behavior> + 13-UI-SPEC §3 / "Data source"):
//   - series[] is the Phase-12 [{date, spend, requests}] contract.
//   - seriesToUplot(series, "spend")    -> [ [xs], [spend...] ] aligned by index.
//   - seriesToUplot(series, "requests") -> [ [xs], [requests...] ] aligned by index.
//   - seriesToUplot([], field)          -> [[],[]] (the "no data" shape) so the
//     wrapper renders the empty state instead of instantiating uPlot.
//   - xs are uPlot time-axis unix SECONDS, UTC-derived (tz-stable) and ordered
//     exactly as the input series.
import { describe, it, expect } from "vitest";
import { seriesToUplot } from "./charts.js";

// A small, deterministic fixture in the locked contract shape.
const SERIES = [
  { date: "2026-03-01", spend: 1.5, requests: 10 },
  { date: "2026-03-02", spend: 2.25, requests: 20 },
  { date: "2026-03-03", spend: 0, requests: 0 },
];

// Expected x values: unix SECONDS at UTC midnight for each date, input order.
const XS = SERIES.map((p) => Math.floor(Date.parse(`${p.date}T00:00:00Z`) / 1000));

describe("seriesToUplot — spend field", () => {
  it("maps to [xs, spend[]] aligned by index", () => {
    const [xs, ys] = seriesToUplot(SERIES, "spend");
    expect(xs).toEqual(XS);
    expect(ys).toEqual([1.5, 2.25, 0]);
  });

  it("preserves input order", () => {
    const [xs] = seriesToUplot(SERIES, "spend");
    expect(xs).toEqual([...XS]);
  });

  it("keeps a real zero as 0 (not dropped, not null)", () => {
    const [, ys] = seriesToUplot(SERIES, "spend");
    expect(ys[2]).toBe(0);
  });
});

describe("seriesToUplot — requests field", () => {
  it("reads the requests field into the ys array", () => {
    const [xs, ys] = seriesToUplot(SERIES, "requests");
    expect(xs).toEqual(XS);
    expect(ys).toEqual([10, 20, 0]);
  });
});

describe("seriesToUplot — empty / no-data shape", () => {
  it("returns [[],[]] for an empty series", () => {
    expect(seriesToUplot([], "spend")).toEqual([[], []]);
    expect(seriesToUplot([], "requests")).toEqual([[], []]);
  });

  it("returns the no-data shape for a null/undefined series", () => {
    expect(seriesToUplot(null, "spend")).toEqual([[], []]);
    expect(seriesToUplot(undefined, "spend")).toEqual([[], []]);
  });

  it("is purely structural — both arrays empty so the wrapper skips uPlot", () => {
    const [xs, ys] = seriesToUplot([], "spend");
    expect(xs).toHaveLength(0);
    expect(ys).toHaveLength(0);
  });
});

describe("seriesToUplot — purity", () => {
  it("does not mutate the input series", () => {
    const input = [{ date: "2026-03-01", spend: 1, requests: 2 }];
    const snapshot = JSON.stringify(input);
    seriesToUplot(input, "spend");
    expect(JSON.stringify(input)).toBe(snapshot);
  });
});
