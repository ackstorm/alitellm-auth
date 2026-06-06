// KpiRow.tsx — the 4-card KPI row for the #/stats Usage & Spend page (STATS-02).
// React + Tailwind port of the old Preact leaf src/ui/stats-kpis.js.
//
// PURE presentational leaf — no fetch, no data ownership. The container passes
// the `totals` slice; this renders the four headline metrics. The Compare /
// delta-chip surface was removed, so there is no per-metric delta coloring here.

import * as React from 'react';

import type { StatsTotals } from '@/lib/api-types';
import { abbreviate, formatCurrency } from '@/lib/format';

// One of the four cards: an 11px caption label above a 24px heading value.
function KpiCard({
  label,
  value,
}: {
  label: string;
  value: string;
}): React.ReactElement {
  return (
    <div className="flex flex-col gap-2 rounded-2xl border border-border bg-surface p-5">
      <div className="font-mono text-[11px] font-semibold uppercase tracking-wider text-text-secondary">
        {label}
      </div>
      <div className="break-words font-sans text-2xl font-semibold leading-tight text-text-primary">
        {value}
      </div>
    </div>
  );
}

export interface KpiRowProps {
  /** The `totals` slice (requests/tokens/spend/avg). */
  totals: StatsTotals | null | undefined;
}

// Renders exactly four cards (TOTAL REQUESTS / TOTAL TOKENS / SPEND /
// AVG COST / 1K REQ) in a 4->2->1 responsive grid.
export function KpiRow({ totals }: KpiRowProps): React.ReactElement {
  const t = totals ?? null;

  const cards = [
    { label: 'TOTAL REQUESTS', value: abbreviate(t?.requests) },
    { label: 'TOTAL TOKENS', value: abbreviate(t?.tokens) },
    { label: 'SPEND', value: formatCurrency(t?.spend) },
    { label: 'AVG COST / 1K REQ', value: formatCurrency(t?.avg_cost_per_1k_req) },
  ];

  return (
    <div data-slot="kpi-row" className="flex flex-col gap-2">
      <div className="grid grid-cols-4 gap-3 max-[880px]:grid-cols-2 max-[520px]:grid-cols-1">
        {cards.map((c) => (
          <KpiCard key={c.label} label={c.label} value={c.value} />
        ))}
      </div>
    </div>
  );
}
