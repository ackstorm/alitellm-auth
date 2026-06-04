// Stats.tsx — the #/stats Usage & Spend page CONTAINER (Task 4.6).
//
// React + TanStack Query + Tailwind rebuild of the old Preact container
// src/ui/stats.js (StatsView). It owns the date/compare state, drives the
// re-query against GET /api/session/stats via useStats(range), and composes the
// Phase-4 leaves (KpiRow, SpendChart, RequestsChart, UsageDonut, TopKeys,
// ModelTable, BudgetPanel, DateRange) with per-panel Skeletons while loading and
// a whole-page error card on failure.
//
// DELIBERATE DIVERGENCES from src/ui/stats.js (the new no-sidebar architecture):
//   • NO left StatsRail — the AppShell topbar already provides Dashboard/Stats
//     navigation, so the old page-local rail is redundant (not built here).
//   • NO "Insights" Beta panel and NO coming-soon toast — the mock filler is
//     dropped (consistent with the no-sidebar dashboard).
//   • The page renders FULL WIDTH (AppShell already gives the Outlet the full
//     content width); there is no page-owned right <aside> rail.
//
// The data-status machine collapses to TanStack Query's `isPending` / `isError`
// (useStats throws on any non-200), so the old loadSeq ref guard + the 422-inline
// rangeError distinction are subsumed by the query: a superseding range refetch
// is handled by the queryKey, and useStats throws generically, so rangeError is
// passed as null to DateRange for now (the 422-inline distinction is deferred).

import { useState } from 'react';

import { BudgetPanel } from '@/components/stats/BudgetPanel';
import { DateRange } from '@/components/stats/DateRange';
import { KpiRow } from '@/components/stats/KpiRow';
import { ModelTable } from '@/components/stats/ModelTable';
import { RequestsChart } from '@/components/stats/RequestsChart';
import { SpendChart } from '@/components/stats/SpendChart';
import { TopKeys } from '@/components/stats/TopKeys';
import { UsageDonut } from '@/components/stats/UsageDonut';
import { Skeleton } from '@/components/ui/skeleton';
import { useStats } from '@/hooks/use-stats';
import { presetToRange } from '@/lib/stats-presets';

// Locked copy (mirrors src/ui/stats.js §Copywriting Contract).
const PAGE_TITLE = 'Usage & Spend';
const PAGE_SUB = 'Requests, tokens, models, and spend for the selected period.';
const SECTION_DAILY_SPEND = 'DAILY SPEND';
const SECTION_REQUESTS = 'REQUESTS BY DAY';
const SECTION_USAGE_BY_MODEL = 'USAGE BY MODEL';
const SECTION_MODEL_BREAKDOWN = 'MODEL BREAKDOWN';
const ERR_HEADING = "Couldn't load usage";
const ERR_BODY =
  "We couldn't reach the usage service. Check your connection and retry.";

// The default preset (Phase-12 default window — 30d).
const DEFAULT_PRESET = '30d';

// Shared 11px mono-caption section label (the UI-SPEC §Typography caption role).
const SECTION_LABEL_CLASS =
  'font-mono text-[11px] font-semibold uppercase tracking-widest text-text-secondary';

// A titled surface-card panel: the section label above its body (chart / table).
function Panel({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0 rounded-xl border border-border bg-surface p-5">
      <div className={`${SECTION_LABEL_CLASS} mb-3`}>{label}</div>
      {children}
    </div>
  );
}

export function Stats() {
  // Date/compare state (mirrors src/ui/stats.js). `preset` drives the range via
  // presetToRange; `range` is the resolved {start,end} submitted to the server.
  const [preset, setPreset] = useState<string>(DEFAULT_PRESET);
  const [range, setRange] = useState<{ start: string; end: string }>(() =>
    presetToRange(DEFAULT_PRESET, new Date()),
  );
  // compareOn is CLIENT-ONLY (toggles the KPI delta chips, no fetch).
  const [compareOn, setCompareOn] = useState(false);

  const query = useStats(range);

  // A preset click: recompute the range (presetToRange clamps to <=366 days so
  // the client never submits a 422-triggering span); the queryKey refetches.
  const onPreset = (id: string): void => {
    setPreset(id);
    setRange(presetToRange(id, new Date()));
  };
  // The calendar Apply emit: set the explicit range directly.
  const onCustomRange = (r: { start: string; end: string }): void => {
    setPreset('Custom');
    setRange(r);
  };
  // Compare toggle — CLIENT-ONLY, no fetch.
  const onToggleCompare = (): void => {
    setCompareOn((v) => !v);
  };

  const loading = query.isPending;
  const isError = query.isError;
  const data = query.data;

  // Distribute the contract slices. While loading these are null/[]/0.
  const totals = data?.totals ?? null;
  const series = data?.series ?? [];
  const models = data?.models ?? [];
  const keys = data?.keys ?? [];
  const budget = data?.budget ?? null;
  const capabilities = data?.capabilities ?? null;
  const rangeDays = data?.range?.days ?? 0;

  // The header band — title + sub on the LEFT, the date controls on the RIGHT.
  // rangeError is null for now (the 422-inline distinction is deferred; useStats
  // throws generically into isError, surfaced as the whole-page error card).
  const header = (
    <div className="flex flex-wrap items-start justify-between gap-5">
      <div>
        <div className="font-sans text-2xl font-semibold leading-snug text-text-primary">
          {PAGE_TITLE}
        </div>
        <div className="mt-1 font-sans text-sm text-text-secondary">
          {PAGE_SUB}
        </div>
      </div>
      <DateRange
        preset={preset}
        compareOn={compareOn}
        onPreset={onPreset}
        onCustomRange={onCustomRange}
        onToggleCompare={onToggleCompare}
        rangeError={null}
      />
    </div>
  );

  // ── Whole-page error (502 / network) ────────────────────────────────────────
  // The header band still renders above the locked error card; the body is the
  // error card with a bordered destructive retry that re-fires the query.
  if (isError) {
    return (
      <div className="flex flex-col gap-8">
        {header}
        <div className="flex flex-col items-center gap-3 rounded-xl border border-border bg-surface p-12 text-center">
          <div className="font-sans text-2xl font-semibold text-text-primary">
            {ERR_HEADING}
          </div>
          <div className="max-w-md font-sans text-sm text-text-secondary">
            {ERR_BODY}
          </div>
          <button
            type="button"
            onClick={() => void query.refetch()}
            className="inline-flex cursor-pointer items-center justify-center rounded-lg border border-destructive px-4 py-2 font-mono text-xs font-semibold uppercase tracking-wide text-destructive transition-colors hover:bg-destructive/10"
          >
            retry
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-8">
      {header}

      {/* §2 KPI row */}
      {loading ? (
        <div className="grid grid-cols-4 gap-3 max-[880px]:grid-cols-2 max-[520px]:grid-cols-1">
          <Skeleton variant="card" />
          <Skeleton variant="card" />
          <Skeleton variant="card" />
          <Skeleton variant="card" />
        </div>
      ) : (
        <KpiRow
          totals={totals}
          capabilities={capabilities}
          compareOn={compareOn}
          rangeDays={rangeDays}
        />
      )}

      {/* §7 Account budget — full-width band */}
      {loading ? <Skeleton variant="card" /> : <BudgetPanel budget={budget} />}

      {/* §3 the two time-series charts, side-by-side (stack on narrow) */}
      <div className="grid grid-cols-2 gap-3 max-[880px]:grid-cols-1">
        <Panel label={SECTION_DAILY_SPEND}>
          {loading ? <Skeleton variant="chart" /> : <SpendChart series={series} />}
        </Panel>
        <Panel label={SECTION_REQUESTS}>
          {loading ? (
            <Skeleton variant="chart" />
          ) : (
            <RequestsChart series={series} />
          )}
        </Panel>
      </div>

      {/* §5 usage-by-model donut + §6 top keys */}
      <div className="grid grid-cols-2 items-start gap-3 max-[880px]:grid-cols-1">
        <Panel label={SECTION_USAGE_BY_MODEL}>
          {loading ? (
            <Skeleton variant="chart" />
          ) : (
            <UsageDonut
              models={models}
              totalSpend={totals?.spend ?? null}
              capabilities={capabilities}
            />
          )}
        </Panel>
        {loading ? (
          <div className="rounded-xl border border-border bg-surface p-5">
            <Skeleton variant="table-rows" rows={5} />
          </div>
        ) : (
          <TopKeys keys={keys} capabilities={capabilities} />
        )}
      </div>

      {/* §4 Model Breakdown */}
      <div className="min-w-0">
        <div className={`${SECTION_LABEL_CLASS} mb-3`}>
          {SECTION_MODEL_BREAKDOWN}
        </div>
        {loading ? (
          <Skeleton variant="table-rows" rows={6} />
        ) : (
          <ModelTable models={models} capabilities={capabilities} />
        )}
      </div>
    </div>
  );
}
