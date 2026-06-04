// UsageDonut.tsx — the token-split usage donut for the #/stats Usage & Spend
// page (STATS-05). React + Tailwind + Recharts port of the old hand-rolled
// inline-SVG donut src/ui/stats-donut.js.
//
// The old leaf hand-rolled an inline-SVG ring because uPlot had no pie/donut
// (CONTEXT D-01). ui-next ships Recharts, so this renders a real <PieChart>/<Pie>
// donut. Per the task's token_split intent the two segments are INPUT vs OUTPUT
// tokens (the capability this figure gates on), with the `${total}` figure
// centered under a `TOTAL` caption. Colors come from tokens (var(--primary) +
// a muted second token shade) — NEVER a raw hex.
//
// PURE presentational leaf — no fetch, no data ownership. The container passes
// the Phase-12 `totals` slice + `capabilities`. The render branch is decided by
// capabilityRenderMode(capabilities, 'token_split', hasData):
//   "coming-soon" -> the source's `Coming soon` copy + em-dash where the total sits.
//   "empty"       -> the source's `No usage in this range`.
//   "ready"       -> the donut + legend.
//
// SECURITY (T-13-05, XSS — MITIGATED): all labels render as React text children
// (auto-escaped). No dangerouslySetInnerHTML. Numbers pass through format.ts.
// SECURITY (T-13-07, DoS / divide-by-zero — MITIGATED): the donut renders only
// when there is real data; an all-zero total falls to the "empty" branch.

import * as React from 'react';
import { Cell, Pie, PieChart, ResponsiveContainer } from 'recharts';

import type { StatsCapabilities, StatsTotals } from '@/lib/api-types';
import { abbreviate, formatInt } from '@/lib/format';
import { capabilityRenderMode } from '@/lib/stats-presets';

// The em-dash placeholder (matches format.ts EM_DASH).
const EM_DASH = '—';

// Locked copy, lifted verbatim from stats-donut.js (13-UI-SPEC §Copywriting).
const TOTAL_CAPTION = 'TOTAL';
const COMING_SOON_COPY = 'Coming soon';
const EMPTY_COPY = 'No usage in this range';

// The two token-split segment labels.
const INPUT_LABEL = 'Input';
const OUTPUT_LABEL = 'Output';

// Segment colors from tokens (the accent green + a muted second shade) — never
// a raw hex. --primary === --chart-1 (the series accent); --chart-3 is the
// stepped-down second token shade for the OUTPUT slice.
const INPUT_COLOR = 'var(--primary)';
const OUTPUT_COLOR = 'var(--chart-3)';

// Donut geometry — a fixed-height figure mirroring the old 160px ring.
const DONUT_HEIGHT = 160;

export interface UsageDonutProps {
  /** The Phase-12 `totals` slice (input/output token figures live on models, but
   *  the contract's window totals carry the split when token_split is on). */
  totals: StatsTotals | null | undefined;
  /** Per-model rows — the source of the input/output token split. */
  models: { input_tokens: number; output_tokens: number }[] | null | undefined;
  /** The contract `capabilities` map (gate: `token_split`). */
  capabilities: StatsCapabilities | null | undefined;
}

// Sum a numeric field across the model rows (divide-by-zero safe — a non-number
// contributes 0). Pure.
function sumField(
  rows: { input_tokens: number; output_tokens: number }[] | null | undefined,
  field: 'input_tokens' | 'output_tokens',
): number {
  if (!Array.isArray(rows)) return 0;
  return rows.reduce((acc, r) => {
    const v = r && typeof r[field] === 'number' ? r[field] : 0;
    return acc + v;
  }, 0);
}

// A small state panel (coming-soon / empty) matching the old usage-donut--state
// chrome: a centered, min-height surface card.
function DonutStatePanel({
  children,
  showTotalCap,
}: {
  children: React.ReactNode;
  showTotalCap?: boolean;
}): React.ReactElement {
  return (
    <div
      data-slot="usage-donut-state"
      className="flex min-h-40 flex-col items-center justify-center gap-2 rounded-2xl border border-border bg-surface p-5 text-center"
    >
      {showTotalCap ? (
        <>
          <div className="font-mono text-[11px] font-semibold uppercase tracking-wider text-text-secondary">
            {TOTAL_CAPTION}
          </div>
          <div className="font-sans text-2xl font-semibold leading-tight text-primary">
            {EM_DASH}
          </div>
        </>
      ) : null}
      <div className="font-sans text-sm text-text-secondary">{children}</div>
    </div>
  );
}

export function UsageDonut({
  totals,
  models,
  capabilities,
}: UsageDonutProps): React.ReactElement {
  const inputTokens = sumField(models, 'input_tokens');
  const outputTokens = sumField(models, 'output_tokens');
  // Prefer the contract window total when present; else the derived split sum.
  const total =
    totals && typeof totals.tokens === 'number'
      ? totals.tokens
      : inputTokens + outputTokens;

  // hasData drives the empty distinction; the split must carry real tokens.
  const hasData = inputTokens + outputTokens > 0;
  // StatsCapabilities is a fixed boolean record; capabilityRenderMode wants the
  // open Record<string, boolean> shape, so we read it through that view.
  const mode = capabilityRenderMode(
    capabilities as Record<string, boolean> | null | undefined,
    'token_split',
    hasData
  );

  if (mode === 'coming-soon') {
    return (
      <DonutStatePanel showTotalCap>{COMING_SOON_COPY}</DonutStatePanel>
    );
  }

  if (mode === 'empty') {
    return <DonutStatePanel>{EMPTY_COPY}</DonutStatePanel>;
  }

  const segments = [
    { name: INPUT_LABEL, value: inputTokens, color: INPUT_COLOR },
    { name: OUTPUT_LABEL, value: outputTokens, color: OUTPUT_COLOR },
  ];

  return (
    <div
      data-slot="usage-donut"
      className="flex flex-wrap items-center gap-8 rounded-2xl border border-border bg-surface p-5"
    >
      <div className="relative h-40 w-40 shrink-0">
        <ResponsiveContainer width="100%" height={DONUT_HEIGHT}>
          <PieChart>
            <Pie
              data={segments}
              dataKey="value"
              nameKey="name"
              cx="50%"
              cy="50%"
              innerRadius={56}
              outerRadius={78}
              startAngle={90}
              endAngle={-270}
              stroke="none"
              isAnimationActive={false}
            >
              {segments.map((s) => (
                <Cell key={s.name} fill={s.color} />
              ))}
            </Pie>
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-1">
          <div className="font-mono text-[11px] font-semibold uppercase tracking-wider text-text-secondary">
            {TOTAL_CAPTION}
          </div>
          <div className="font-sans text-2xl font-semibold leading-tight text-primary">
            {abbreviate(total)}
          </div>
        </div>
      </div>
      <ul data-slot="usage-donut-legend" className="flex flex-1 basis-50 flex-col gap-2">
        {segments.map((s) => (
          <li
            key={s.name}
            className="grid grid-cols-[auto_1fr_auto] items-center gap-2 rounded-lg px-2 py-1"
          >
            <span
              className="size-2.5 shrink-0 rounded-full"
              style={{ background: s.color }}
              aria-hidden="true"
            />
            <span className="truncate font-mono text-xs text-text-primary">
              {s.name}
            </span>
            <span className="font-mono text-xs text-text-primary">
              {formatInt(s.value)}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
