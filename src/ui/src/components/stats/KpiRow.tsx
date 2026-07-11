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

// The per-card delta chip. Two states:
//   • finite pct -> signed percent + direction arrow/color;
//   • otherwise  -> nothing. When there is no prior baseline to compare against
//                   (prior window was 0/absent) there is no real trend, so we
//                   render NO chip rather than a confusing "▲ 100% (no info)".
function DeltaChip({
  pct,
  invert,
}: {
  pct: number | null | undefined;
  invert?: boolean;
}): React.ReactElement | null {
  const hasPct = typeof pct === 'number' && Number.isFinite(pct);
  if (!hasPct) return null;

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

// One of the four cards, all with the SAME three-part layout: an 11px caption
// label, the 24px value with its optional detail inline beside it (in muted
// parens, e.g. "5 failed · 6.5%"), and the period-over-period delta chip on its
// own line below. Uniform across the four cards so the detail rows and the chip
// rows line up column-for-column. `sub` is inline content (a <span>) nested in
// the parens; keep it short enough to sit beside the value without wrapping.
function KpiCard({
  label,
  labelTitle,
  value,
  deltaPct,
  invert,
  sub,
  icon: Icon,
}: {
  label: string;
  labelTitle?: string;
  value: string;
  deltaPct: number | null | undefined;
  invert?: boolean;
  /** Short inline note next to the value, in muted parens (e.g. "5 failed · 6.5%"). */
  sub?: React.ReactNode;
  icon: typeof BarChart3;
}): React.ReactElement {
  // DeltaChip holds no hooks, so call it directly to render the chip below.
  const chip = DeltaChip({ pct: deltaPct, invert });
  const hasSub = sub != null && sub !== false;

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-5">
      {/* Icon chip + label row — mirrors the Dashboard MetricTile so the two
          pages' KPI tiles read as the same component. */}
      <div className="flex items-center gap-2">
        <span className="inline-flex size-[26px] shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className="size-[15px]" aria-hidden="true" />
        </span>
        <div
          data-testid={label === 'SPEND' ? 'kpi-spend-label' : undefined}
          title={labelTitle}
          className="font-mono text-[11px] font-semibold uppercase tracking-wider text-text-secondary"
        >
          {label}
        </div>
      </div>
      <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5">
        <span className="break-words font-sans text-2xl font-semibold leading-tight text-text-primary">
          {value}
        </span>
        {hasSub ? (
          <span className="font-mono text-[10px] text-text-tertiary">({sub})</span>
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
      // The headline total already shows the full token count, so the inline sub
      // adds the OUTPUT split and its share of the total: "6.8M out · 22%". Short
      // enough to sit beside the value without wrapping; the title spells it out.
      sub: ((): React.ReactNode => {
        const out =
          typeof t?.output_tokens === 'number' ? t.output_tokens : null;
        if (out === null || out <= 0) return null;
        const total = typeof t?.tokens === 'number' ? t.tokens : null;
        const pct =
          total && total > 0 ? ` · ${((out / total) * 100).toFixed(1)}%` : '';
        return (
          <span data-slot="kpi-tokens" title="Output tokens · share of total tokens">
            {abbreviate(out)} out{pct}
          </span>
        );
      })(),
    },
    {
      label: 'SPEND',
      icon: DollarSign,
      value: formatCurrency(t?.spend),
      labelTitle: 'Gateway-computed spend — includes cache & provider pricing',
      deltaPct: d?.spend_pct,
      invert: true,
    },
    {
      label: 'AVG COST / 1M TOKENS',
      icon: Gauge,
      value: formatCurrency(t?.avg_cost_per_1m_tokens),
      deltaPct: d?.avg_cost_per_1m_tokens_pct,
      invert: true,
    },
  ];

  return (
    <div data-slot="kpi-row" className="flex flex-col gap-2">
      <div className="grid grid-cols-4 gap-3 max-[880px]:grid-cols-2 max-[520px]:grid-cols-1">
        {cards.map((c) => (
          <KpiCard
            key={c.label}
            label={c.label}
            labelTitle={'labelTitle' in c ? c.labelTitle : undefined}
            icon={c.icon}
            value={c.value}
            deltaPct={c.deltaPct}
            invert={c.invert}
            sub={'sub' in c ? c.sub : undefined}
          />
        ))}
      </div>
    </div>
  );
}
