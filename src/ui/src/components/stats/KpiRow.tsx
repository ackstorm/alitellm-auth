// KpiRow.tsx — the 4-card KPI row for the #/stats Usage & Spend page (STATS-02).
//
// PURE presentational leaf — no fetch, no data ownership. The container passes
// the `totals` slice; this renders the four headline metrics plus a
// period-over-period delta chip per card (from totals.deltas; a null pct —
// degraded prior window, D-08 — renders no chip). Direction coloring is
// semantic: requests/tokens up = good (primary), spend/avg-cost up = bad
// (destructive) via the `invert` flag.

import * as React from 'react';

import type { StatsTotals } from '@/lib/api-types';
import { abbreviate, formatCurrency, formatInt } from '@/lib/format';

// Signed one-decimal percent: 0.182 -> "+18.2%", -0.05 -> "-5.0%".
function formatSignedPct(fraction: number): string {
  const pct = (fraction * 100).toFixed(1);
  return fraction >= 0 ? `+${pct}%` : `${pct}%`;
}

// The per-card delta chip. Three states:
//   • finite pct          -> signed percent + direction arrow/color;
//   • pct null but isNew  -> a "new" chip (prior baseline was 0, current > 0 —
//                            an undefined %, NOT an infinite one);
//   • otherwise           -> nothing (no prior AND no current activity).
function DeltaChip({
  pct,
  invert,
  isNew,
}: {
  pct: number | null | undefined;
  invert?: boolean;
  isNew?: boolean;
}): React.ReactElement | null {
  const hasPct = typeof pct === 'number' && Number.isFinite(pct);

  if (!hasPct) {
    if (!isNew) return null;
    // Prior baseline was 0/absent: the jump from nothing is a full +100%, but
    // there is no real trend to judge — a NEUTRAL grey note, not a good/bad
    // colored delta.
    return (
      <div
        data-slot="kpi-delta"
        className="font-mono text-[11px] text-text-secondary"
      >
        ▲ 100% <span className="text-text-tertiary">(no previous info)</span>
      </div>
    );
  }

  const value = pct as number;
  const up = value > 0;
  const flat = value === 0;
  const good = flat ? null : invert ? !up : up;
  const color = flat
    ? 'text-text-secondary'
    : good
      ? 'text-primary'
      : 'text-destructive';
  const arrow = flat ? '' : up ? '▲ ' : '▼ ';
  return (
    <div data-slot="kpi-delta" className={`font-mono text-[11px] ${color}`}>
      {arrow}
      {formatSignedPct(value)}{' '}
      <span className="text-text-tertiary">vs prev</span>
    </div>
  );
}

// "new" = the prior-period baseline was 0/undefined (so no % change exists) yet
// the current window has real activity. Distinguishes genuinely-new usage from a
// fully-idle metric (where both windows are 0 → no chip at all).
function isNewMetric(
  pct: number | null | undefined,
  current: number | null | undefined,
): boolean {
  const hasPct = typeof pct === 'number' && Number.isFinite(pct);
  return (
    !hasPct &&
    typeof current === 'number' &&
    Number.isFinite(current) &&
    current > 0
  );
}

// One of the four cards: an 11px caption label above a 24px heading value, an
// optional sub-line (e.g. failed-requests), then the period-over-period chip.
function KpiCard({
  label,
  value,
  deltaPct,
  invert,
  isNew,
  sub,
}: {
  label: string;
  value: string;
  deltaPct: number | null | undefined;
  invert?: boolean;
  isNew?: boolean;
  sub?: React.ReactNode;
}): React.ReactElement {
  return (
    <div className="flex flex-col gap-2 rounded-2xl border border-border bg-surface p-5">
      <div className="font-mono text-[11px] font-semibold uppercase tracking-wider text-text-secondary">
        {label}
      </div>
      <div className="break-words font-sans text-2xl font-semibold leading-tight text-text-primary">
        {value}
      </div>
      {sub}
      <DeltaChip pct={deltaPct} invert={invert} isNew={isNew} />
    </div>
  );
}

export interface KpiRowProps {
  /** The `totals` slice (requests/tokens/spend/avg + deltas). */
  totals: StatsTotals | null | undefined;
}

// Renders exactly four cards (TOTAL REQUESTS / TOTAL TOKENS / SPEND /
// AVG COST / 1M TOKENS) in a 4->2->1 responsive grid.
export function KpiRow({ totals }: KpiRowProps): React.ReactElement {
  const t = totals ?? null;
  const d = t?.deltas ?? null;

  const cards = [
    {
      label: 'TOTAL REQUESTS',
      value: abbreviate(t?.requests),
      deltaPct: d?.requests_pct,
      invert: false,
      isNew: isNewMetric(d?.requests_pct, t?.requests),
      sub:
        typeof t?.failed_requests === 'number' && t.failed_requests > 0 ? (
          <div
            data-slot="kpi-failed"
            className="font-mono text-[11px] text-destructive"
          >
            {formatInt(t.failed_requests)} failed
            {t.requests > 0
              ? ` · ${((t.failed_requests / t.requests) * 100).toFixed(1)}%`
              : ''}
          </div>
        ) : null,
    },
    {
      label: 'TOTAL TOKENS',
      value: abbreviate(t?.tokens),
      deltaPct: d?.tokens_pct,
      invert: false,
      isNew: isNewMetric(d?.tokens_pct, t?.tokens),
      sub:
        typeof t?.cache_hit_pct === 'number' && t.cache_hit_pct > 0 ? (
          <div
            data-slot="kpi-cache"
            className="font-mono text-[11px] text-text-secondary"
          >
            {(t.cache_hit_pct * 100).toFixed(1)}% cached input
          </div>
        ) : null,
    },
    {
      label: 'SPEND',
      value: formatCurrency(t?.spend),
      deltaPct: d?.spend_pct,
      invert: true,
      isNew: isNewMetric(d?.spend_pct, t?.spend),
    },
    {
      label: 'AVG COST / 1M TOKENS',
      value: formatCurrency(t?.avg_cost_per_1m_tokens),
      deltaPct: d?.avg_cost_per_1m_tokens_pct,
      invert: true,
      isNew: isNewMetric(
        d?.avg_cost_per_1m_tokens_pct,
        t?.avg_cost_per_1m_tokens,
      ),
    },
  ];

  return (
    <div data-slot="kpi-row" className="flex flex-col gap-2">
      <div className="grid grid-cols-4 gap-3 max-[880px]:grid-cols-2 max-[520px]:grid-cols-1">
        {cards.map((c) => (
          <KpiCard
            key={c.label}
            label={c.label}
            value={c.value}
            deltaPct={c.deltaPct}
            invert={c.invert}
            isNew={c.isNew}
            sub={'sub' in c ? c.sub : undefined}
          />
        ))}
      </div>
    </div>
  );
}
