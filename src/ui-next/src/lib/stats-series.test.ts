// stats-series.test.ts — vitest unit suite for the PURE `seriesToRecharts`
// transform in stats-series.ts. Runs in the default node env (no DOM, no chart
// lib) because the transform is pure — mirrors format.test.js / charts.test.js.
//
// Contract (ported from src/ui/charts.test.js, adapted to ROW OBJECTS):
//   - series[] is the Phase-12 [{date, spend, requests}] contract.
//   - seriesToRecharts(series) -> [{date, spend, requests}, ...] in input order.
//   - seriesToRecharts([] | null | undefined) -> [] (the "no data" shape) so the
//     chart renders its empty state instead of an empty grid.
//   - a REAL zero stays 0 (never dropped, never null) for BOTH spend and requests.
//   - PURE: never mutates the input.
import { describe, it, expect } from 'vitest';
import { seriesToRecharts } from './stats-series';
import type { StatsSeriesPoint } from './api-types';

// A small, deterministic fixture in the locked contract shape (ported from
// charts.test.js). Typed as StatsSeriesPoint[] so the literals satisfy the
// contract (date string, spend/requests number) with no casts.
const SERIES: StatsSeriesPoint[] = [
  { date: '2026-03-01', spend: 1.5, requests: 10 },
  { date: '2026-03-02', spend: 2.25, requests: 20 },
  { date: '2026-03-03', spend: 0, requests: 0 },
];

describe('seriesToRecharts — row-object mapping', () => {
  it('maps to row objects aligned and IN ORDER', () => {
    expect(seriesToRecharts(SERIES)).toEqual([
      { date: '2026-03-01', spend: 1.5, requests: 10 },
      { date: '2026-03-02', spend: 2.25, requests: 20 },
      { date: '2026-03-03', spend: 0, requests: 0 },
    ]);
  });

  it('keeps a real zero as 0 for both spend and requests (not dropped, not null)', () => {
    const rows = seriesToRecharts(SERIES);
    expect(rows[2].spend).toBe(0);
    expect(rows[2].requests).toBe(0);
  });
});

describe('seriesToRecharts — empty / no-data shape', () => {
  it('returns [] for an empty series', () => {
    expect(seriesToRecharts([])).toEqual([]);
  });

  it('returns [] for a null/undefined series', () => {
    expect(seriesToRecharts(null)).toEqual([]);
    expect(seriesToRecharts(undefined)).toEqual([]);
  });
});

describe('seriesToRecharts — purity', () => {
  it('does not mutate the input series', () => {
    const input: StatsSeriesPoint[] = [{ date: '2026-03-01', spend: 1, requests: 2 }];
    const snapshot = JSON.stringify(input);
    seriesToRecharts(input);
    expect(JSON.stringify(input)).toBe(snapshot);
  });
});
