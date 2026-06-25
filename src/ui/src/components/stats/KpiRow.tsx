// KpiRow.tsx — the 4-card KPI row for the #/stats Usage & Spend page (STATS-02).
//
// PURE presentational leaf — no fetch, no data ownership. The container passes
// the `totals` slice; this renders the four headline metrics plus a
// period-over-period delta chip per card (from totals.deltas; a null pct —
// degraded prior window, D-08 — renders no chip). Direction coloring is
// semantic: requests/tokens up = good (primary), spend/avg-cost up = bad
// (destructive) via the `invert` flag.

import { BarChart3, Coins, DollarSign, Gauge } from 'lucide-react';
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
        ▲ 100% <span className="text-text-tertiary">(no info)</span>
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

// One of the four cards: an 11px caption label, then the 24px heading value with
// the optional sub (failed-requests / cached-input) inlined in muted parentheses
// next to it (baseline-aligned), and the period-over-period chip on its own line
// below. `sub` must be inline (a <span>) so it nests inside the parens.
function KpiCard({
  label,
  value,
  deltaPct,
  invert,
  isNew,
  sub,
  icon: Icon,
}: {
  label: string;
  value: string;
  deltaPct: number | null | undefined;
  invert?: boolean;
  isNew?: boolean;
  sub?: React.ReactNode;
  icon: typeof BarChart3;
}): React.ReactElement {
  // DeltaChip holds no hooks, so call it directly to render the chip below.
  const chip = DeltaChip({ pct: deltaPct, invert, isNew });
  const hasSub = sub != null && sub !== false;

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-5">
      {/* Icon chip + label row — mirrors the Dashboard MetricTile so the two
          pages' KPI tiles read as the same component. */}
      <div className="flex items-center gap-2">
        <span className="inline-flex size-[26px] shrink-0 items-center justify-center rounded-lg border border-border">
          <Icon className="size-[15px] text-primary" aria-hidden="true" />
        </span>
        <div className="font-mono text-[11px] font-semibold uppercase tracking-wider text-text-secondary">
          {label}
        </div>
      </div>
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="break-words font-sans text-2xl font-semibold leading-tight text-text-primary">
          {value}
        </span>
        {hasSub ? (
          <span className="font-mono text-[10px] text-text-tertiary">
            ({sub})
          </span>
        ) : null}
      </div>
      {chip}
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
      icon: BarChart3,
      value: abbreviate(t?.requests),
      deltaPct: d?.requests_pct,
      invert: false,
      isNew: isNewMetric(d?.requests_pct, t?.requests),
      sub:
        typeof t?.failed_requests === 'number' && t.failed_requests > 0 ? (
          <span data-slot="kpi-failed" className="text-destructive">
            {formatInt(t.failed_requests)} failed
            {t.requests > 0
              ? ` · ${((t.failed_requests / t.requests) * 100).toFixed(1)}%`
              : ''}
          </span>
        ) : null,
    },
    {
      label: 'TOTAL TOKENS',
      icon: Coins,
      value: abbreviate(t?.tokens),
      deltaPct: d?.tokens_pct,
      invert: false,
      isNew: isNewMetric(d?.tokens_pct, t?.tokens),
      // The headline total is dominated by (mostly cached) input, so spell out the
      // input/output split + cache-hit rate: "856M in · 6.8M out · 93% cached".
      sub: ((): React.ReactNode => {
        const parts: string[] = [];
        if (typeof t?.input_tokens === 'number' && t.input_tokens > 0)
          parts.push(`${abbreviate(t.input_tokens)} in`);
        if (typeof t?.output_tokens === 'number' && t.output_tokens > 0)
          parts.push(`${abbreviate(t.output_tokens)} out`);
        if (typeof t?.cache_hit_pct === 'number' && t.cache_hit_pct > 0)
          parts.push(`${(t.cache_hit_pct * 100).toFixed(1)}% cached`);
        return parts.length ? (
          <span data-slot="kpi-tokens" className="text-text-secondary">
            {parts.join(' · ')}
          </span>
        ) : null;
      })(),
    },
    {
      label: 'SPEND',
      icon: DollarSign,
      value: formatCurrency(t?.spend),
      deltaPct: d?.spend_pct,
      invert: true,
      isNew: isNewMetric(d?.spend_pct, t?.spend),
    },
    {
      label: 'AVG COST / 1M TOKENS',
      icon: Gauge,
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
            icon={c.icon}
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
