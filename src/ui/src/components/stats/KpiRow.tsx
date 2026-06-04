// KpiRow.tsx — the 4-card KPI row for the #/stats Usage & Spend page (STATS-02).
// React + Tailwind port of the old Preact leaf src/ui/stats-kpis.js (ported
// faithfully — same labels, semantics, and delta-chip color table).
//
// PURE presentational leaf — no fetch, no data ownership. The container passes
// the Phase-12 `totals` slice + `capabilities` + the Compare toggle state +
// `range.days`. Mirrors the dashboard MetricTile structure and its 4->2->1
// responsive collapse.
//
// The delta chip follows the LOCKED semantic-direction color table
// (13-UI-SPEC §Color, "Semantic delta direction"): "up" is NOT universally good.
//   • Total Requests / Total Tokens -> primary ▲ (good) / dim ▼
//   • Spend                         -> dim both directions (neutral)
//   • Avg Cost / 1K req             -> destructive ▲ (bad) / primary ▼ (good)
//   • any null *_pct                -> neutral `—` chip in dim, no arrow
// The chip is shown ONLY when Compare is on AND capabilities.deltas is true.

import * as React from 'react';

import type { StatsCapabilities, StatsTotals } from '@/lib/api-types';
import { abbreviate, formatCurrency } from '@/lib/format';
import { cn } from '@/lib/utils';

// The em-dash placeholder (matches format.ts EM_DASH / 13-UI-SPEC §Typography).
const EM_DASH = '—';

// Per-metric semantic disposition (13-UI-SPEC §Color). `tone` selects the chip
// color for a positive vs negative delta; a `null` pct is always neutral.
//   "good-up"  : up is good   (Requests, Tokens) -> primary ▲ / dim ▼
//   "neutral"  : neither good nor bad (Spend)    -> dim both
//   "bad-up"   : up is bad    (Avg cost)         -> destructive ▲ / primary ▼
type Tone = 'good-up' | 'neutral' | 'bad-up';

const SEMANTICS: Record<string, Tone> = {
  requests: 'good-up',
  tokens: 'good-up',
  spend: 'neutral',
  avg_cost_per_1k_req: 'bad-up',
};

// The three chip color CLASSES (token-mapped from the old --accent/--glow,
// --destructive/--glow-err, --dim/--bg trios).
const CHIP_GOOD = 'bg-primary/10 text-primary';
const CHIP_BAD = 'bg-destructive/10 text-destructive';
const CHIP_NEUTRAL = 'bg-background text-text-secondary';

// Resolve the chip color class + arrow glyph for a metric + its pct fraction,
// per the LOCKED §Color table. A null pct -> neutral `—` chip, no arrow.
function chipStyle(metricKey: string, pct: number | null | undefined): {
  cls: string;
  arrow: string;
} {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) {
    return { cls: CHIP_NEUTRAL, arrow: '' };
  }
  const up = pct > 0;
  const arrow = up ? '▲' : '▼';
  const tone = SEMANTICS[metricKey] || 'neutral';

  if (tone === 'neutral') {
    return { cls: CHIP_NEUTRAL, arrow };
  }
  if (tone === 'good-up') {
    // up is good -> primary ▲ ; down is the neutral-down dim ▼.
    return { cls: up ? CHIP_GOOD : CHIP_NEUTRAL, arrow };
  }
  // "bad-up": up is bad -> destructive ▲ ; down is good -> primary ▼.
  return { cls: up ? CHIP_BAD : CHIP_GOOD, arrow };
}

// Format a contract fraction (e.g. 0.182) as a one-decimal `%` (`18.2%`). The
// sign is dropped from the number because the arrow glyph encodes direction;
// a null/non-finite fraction -> em-dash (never `0%` / `NaN`).
function formatPct(pct: number | null | undefined): string {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) return EM_DASH;
  return `${(Math.abs(pct) * 100).toFixed(1)}%`;
}

// One of the four cards: 11px caption label + 24px heading value + an optional
// 12px delta chip. `metricKey` drives the semantic color; the chip renders ONLY
// when `showDelta` is true (Compare + capabilities.deltas) — a null pct then
// renders the neutral `—` chip per §Color, never a fake 0%.
function KpiCard({
  label,
  value,
  metricKey,
  pct,
  showDelta,
}: {
  label: string;
  value: string;
  metricKey: string;
  pct: number | null | undefined;
  showDelta: boolean;
}): React.ReactElement {
  const isNull = pct === null || pct === undefined || !Number.isFinite(pct);
  const { cls, arrow } = chipStyle(metricKey, pct);

  return (
    <div className="flex flex-col gap-2 rounded-2xl border border-border bg-surface p-5">
      <div className="font-mono text-[11px] font-semibold uppercase tracking-wider text-text-secondary">
        {label}
      </div>
      <div className="break-words font-sans text-2xl font-semibold leading-tight text-text-primary">
        {value}
      </div>
      {showDelta ? (
        <div
          data-slot="kpi-delta"
          className={cn(
            'inline-flex items-center gap-1 self-start rounded-full px-2 py-1 font-mono text-xs leading-none',
            cls
          )}
        >
          {arrow ? (
            <span data-slot="kpi-delta-arrow" className="text-[11px]">
              {arrow}
            </span>
          ) : null}
          <span data-slot="kpi-delta-pct">{isNull ? EM_DASH : formatPct(pct)}</span>
        </div>
      ) : null}
    </div>
  );
}

export interface KpiRowProps {
  /** The Phase-12 `totals` slice (requests/tokens/spend/avg + deltas). */
  totals: StatsTotals | null | undefined;
  /** The contract `capabilities` map (gate: `deltas`). */
  capabilities: StatsCapabilities | null | undefined;
  /** The Compare toggle state. */
  compareOn: boolean;
  /** `range.days`, used for the `vs prior {N} days` label. */
  rangeDays: number;
}

// Renders exactly four cards (TOTAL REQUESTS / TOTAL TOKENS / SPEND /
// AVG COST / 1K REQ) in a 4->2->1 responsive grid. The delta chips + the
// `vs prior {N} days` label appear only when Compare is on AND
// `capabilities.deltas` is true.
export function KpiRow({
  totals,
  capabilities,
  compareOn,
  rangeDays,
}: KpiRowProps): React.ReactElement {
  const t = totals ?? null;
  const deltas = t?.deltas ?? null;
  const caps = capabilities ?? null;

  // Chips are shown only when Compare is on AND the server advertises deltas.
  const showDelta = Boolean(compareOn) && caps?.deltas === true;

  const cards = [
    {
      label: 'TOTAL REQUESTS',
      value: abbreviate(t?.requests),
      metricKey: 'requests',
      pct: deltas?.requests_pct,
    },
    {
      label: 'TOTAL TOKENS',
      value: abbreviate(t?.tokens),
      metricKey: 'tokens',
      pct: deltas?.tokens_pct,
    },
    {
      label: 'SPEND',
      value: formatCurrency(t?.spend),
      metricKey: 'spend',
      pct: deltas?.spend_pct,
    },
    {
      label: 'AVG COST / 1K REQ',
      value: formatCurrency(t?.avg_cost_per_1k_req),
      metricKey: 'avg_cost_per_1k_req',
      pct: deltas?.avg_cost_per_1k_req_pct,
    },
  ];

  // `vs prior {N} days` — {N} = range.days, shown only alongside the chips.
  const n = Number.isFinite(rangeDays) ? rangeDays : null;

  return (
    <div data-slot="kpi-row" className="flex flex-col gap-2">
      <div className="grid grid-cols-4 gap-3 max-[880px]:grid-cols-2 max-[520px]:grid-cols-1">
        {cards.map((c) => (
          <KpiCard
            key={c.metricKey}
            label={c.label}
            value={c.value}
            metricKey={c.metricKey}
            pct={c.pct}
            showDelta={showDelta}
          />
        ))}
      </div>
      {showDelta && n !== null ? (
        <div
          data-slot="kpi-compare-label"
          className="font-mono text-[11px] font-semibold uppercase tracking-wider text-text-secondary"
        >
          vs prior {n} days
        </div>
      ) : null}
    </div>
  );
}
