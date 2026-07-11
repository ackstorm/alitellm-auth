// Dashboard.tsx — the #/ authenticated content CONTAINER, ported from
// src/ui/dashboard.js (DASH-01 + the numeric half of DASH-06). Preact + htm ->
// React + Tailwind tokens.
//
// Composes the Phase-3 pieces into the live dashboard:
//   • the top row (greeting + endpoint chip, DASH-01),
//   • the four-tile metric header + the account budget bar (DASH-06),
//   • the API KEYS section with the `+ New Key` CTA (which opens the SAME
//     store-driven create modal as the sidebar shortcut), and the KeysTable,
//   • the prop-driven DeleteKeyModal (the dashboard owns `keyToDelete`).
//
// The CREATE modal + Toaster are mounted in AppShell (so the sidebar can also
// open the create modal); the dashboard only triggers openModal().
//
// SECURITY INVARIANTS (threat register 10-05):
//   • T-10-14 (XSS): me.name / me.endpoint / me.team_id render as React text
//     children (auto-escaped). No dangerouslySetInnerHTML anywhere.
//   • T-10-16 (info disclosure, endpoint Copy): the Copy button writes only
//     me.endpoint (a public base URL), on an explicit user click.

import { useMemo, useState, type ReactNode } from 'react';
import { BarChart3, DollarSign, Key, Users } from 'lucide-react';

import { DeleteKeyModal } from '@/components/keys/DeleteKeyModal';
import { KeysTable } from '@/components/keys/KeysTable';
import { useCopyFeedback } from '@/hooks/use-copy-feedback';
import { useKeys } from '@/hooks/use-keys';
import { useStats } from '@/hooks/use-stats';
import { useTeams } from '@/hooks/use-teams';
import type {
  KeyRow,
  SessionLimits,
  SessionMe,
  SessionSpend,
  Team,
} from '@/lib/api-types';
import { BudgetMeter } from '@/components/ui/budget-meter';
import { abbreviate, formatCurrency, formatInt } from '@/lib/format';
import { budgetPctLabel, isMonthlyDuration, projectMonthEnd } from '@/lib/spend-projection';
import { isRevoked, selectKeyRows } from '@/lib/keys';
import { presetToRange } from '@/lib/stats-presets';
import { teamColorVar } from '@/lib/team-color';
import { cn } from '@/lib/utils';
import { useCreateKeyModalStore } from '@/stores/create-key-modal';

// The em-dash placeholder (matches format.ts EM_DASH, U+2014). The two
// stats-derived figures degrade to it; Active keys reads it while the keys
// query is pending/errored so we never show a misleading 0.
const EM_DASH = '—';

export interface DashboardProps {
  me: SessionMe;
}

// ── EndpointChip ──────────────────────────────────────────────────────────────
// DASH-01 right block: `endpoint` caption + the API base URL + a Copy button.
// Copy writes ONLY the public endpoint URL on an explicit click; the button text
// flips to `copied!` for 2s (useCopyFeedback).
function EndpointChip({ endpoint }: { endpoint: string }) {
  const { copied, copy } = useCopyFeedback();
  return (
    <div className="flex items-center gap-3 rounded-xl border border-border bg-surface px-4 py-2">
      <div className="font-mono text-[11px] font-semibold uppercase tracking-wider text-text-tertiary">
        endpoint
      </div>
      <div className="break-all font-mono text-xs text-text-primary">
        {endpoint || EM_DASH}
      </div>
      <button
        type="button"
        onClick={() => endpoint && void copy(endpoint)}
        className={cn(
          'cursor-pointer rounded-lg border px-2 py-1 font-mono text-[11px] font-semibold lowercase tracking-wide transition-colors',
          copied
            ? // While "copied!" is showing: FILLED green background + green border/text.
              'border-primary bg-primary/15 text-primary'
            : // Idle: neutral, with the green hover affordance returning once the
              // 2s feedback expires.
              'border-border text-text-tertiary hover:border-primary hover:text-primary'
        )}
      >
        {copied ? 'copied!' : 'Copy'}
      </button>
    </div>
  );
}

// ── Sparkline ────────────────────────────────────────────────────────────────
// A tiny inline-SVG area+line trend for the flow-metric tiles (requests, spend).
// Deliberately NOT Recharts — a 96×32 area chart is ~15 lines of SVG and mounting
// a chart lib per card is wasteful. Theme-token colored (stroke/fill primary), so
// it follows dark/light/pastel/red. Returns null for <2 points or an all-flat
// series (nothing to show). Purely decorative → aria-hidden.
function Sparkline({ data, className }: { data: number[]; className?: string }) {
  if (data.length < 2) return null;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min;
  if (range === 0) return null; // flat line carries no signal
  const W = 96;
  const H = 32;
  const pts = data.map((v, i) => {
    const x = (i / (data.length - 1)) * W;
    // 2px top/bottom inset so the peak/trough strokes aren't clipped.
    const y = H - 2 - ((v - min) / range) * (H - 4);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const line = pts.join(' ');
  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      className={className}
      aria-hidden="true"
    >
      <polygon points={`0,${H} ${line} ${W},${H}`} className="fill-primary/10" />
      <polyline
        points={line}
        className="fill-none stroke-primary"
        strokeWidth={1.5}
        strokeLinejoin="round"
        strokeLinecap="round"
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}

// ── MetricTile ───────────────────────────────────────────────────────────────
// One of the four numeric/text tiles (DASH-06): a tinted lucide accent-chip +
// 11px caption label + 24px heading value. Flow metrics (requests/spend) also
// pass `spark` — a per-day series rendered as a right-aligned sparkline that
// fills the card's wide horizontal dead space (all four tiles stay equal height).
function MetricTile({
  label,
  value,
  icon: Icon,
  spark,
}: {
  label: string;
  value: ReactNode;
  icon: typeof Key;
  spark?: number[];
}) {
  return (
    <div className="flex flex-col gap-1.5 overflow-hidden rounded-xl border border-border bg-surface p-4">
      <div className="flex items-center gap-2">
        <span className="inline-flex size-[26px] shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Icon className="size-[15px]" aria-hidden="true" />
        </span>
        <div className="font-mono text-[11px] font-semibold uppercase tracking-wider text-text-tertiary">
          {label}
        </div>
      </div>
      <div className="break-words font-sans text-2xl font-semibold leading-tight text-text-primary">
        {value}
      </div>
      {spark && spark.length > 1 ? (
        // Full-width trend band bled to the card's bottom+side edges (offsets the
        // p-4); `overflow-hidden` on the card clips it to the rounded corners.
        <div className="-mx-4 -mb-4 mt-2 h-8">
          <Sparkline data={spark} className="h-full w-full" />
        </div>
      ) : null}
    </div>
  );
}

// ── TeamTile ─────────────────────────────────────────────────────────────────
// The TEAM tile (DASH-06). A user may belong to several teams, so a single
// 24px value would wrap into an unreadable multi-line blob. With ≥2 teams the
// aliases render as compact muted pills (a wrapped row); with 0/1 team it keeps
// the single 24px value look of the other tiles (falling back to me.team_id).
function TeamTile({ teams, fallback }: { teams: Team[]; fallback: string }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-xl border border-border bg-surface p-4">
      <div className="flex items-center gap-2">
        <span className="inline-flex size-[26px] shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
          <Users className="size-[15px]" aria-hidden="true" />
        </span>
        <div className="font-mono text-[11px] font-semibold uppercase tracking-wider text-text-tertiary">
          Teams
        </div>
      </div>
      {teams.length > 1 ? (
        <div className="flex flex-wrap gap-1.5">
          {teams.map((t, i) => (
            <span
              key={t.id}
              data-slot="team-pill"
              className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface-elevated px-2 py-0.5 font-sans text-xs font-medium text-text-secondary"
            >
              <span
                className="size-2 shrink-0 rounded-full"
                style={{ background: teamColorVar(i) }}
                aria-hidden="true"
              />
              {t.alias}
            </span>
          ))}
        </div>
      ) : (
        <div className="break-words font-sans text-2xl font-semibold leading-tight text-text-primary">
          {teams[0]?.alias || fallback}
        </div>
      )}
    </div>
  );
}

// ── BudgetBar ────────────────────────────────────────────────────────────────
// The account budget bar (DASH-06 / UI-SPEC §C6 / D-11 / FID-03). When
// max_budget is null OR <= 0 it renders a NEUTRAL EMPTY 0%-fill track (a muted
// border-toned fill, NOT primary, NOT full) with the "no budget set" figure —
// never a divide-by-zero and never a full-green bar. Otherwise it renders a
// single fill clamped to [0, 100]% of the spend ratio, color-switching to
// destructive once spend exceeds the budget (the over-budget magnitude is
// carried by the figure text).
function BudgetBar({
  limits,
  spend,
}: {
  limits: SessionLimits | null;
  spend: SessionSpend;
}) {
  const current = typeof spend?.current === 'number' ? spend.current : 0;
  const maxBudget =
    limits && typeof limits.max_budget === 'number' ? limits.max_budget : null;

  if (maxBudget === null || maxBudget <= 0) {
    return (
      <div className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-4">
        <div className="flex items-baseline justify-between gap-3">
          <span className="font-mono text-[11px] font-semibold uppercase tracking-wider text-text-tertiary">
            Account budget
          </span>
          <span className="font-mono text-xs text-text-secondary">
            {formatCurrency(current)} · no budget set
          </span>
        </div>
        <div className="flex h-3 overflow-hidden rounded-full border border-border bg-background">
          <div className="h-full bg-border" style={{ width: '0%' }} />
        </div>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-4">
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-mono text-[11px] font-semibold uppercase tracking-wider text-text-tertiary">
          Account budget
        </span>
        <span className="font-mono text-xs text-text-secondary">
          {formatCurrency(current)} of {formatCurrency(maxBudget)}
          {limits?.budget_duration ? (
            // The budget is per-period; show it so "$X of $Y" isn't ambiguous.
            <span className="text-text-tertiary"> / {limits.budget_duration}</span>
          ) : null}
          {budgetPctLabel(current, maxBudget) ? (
            <span className="text-text-tertiary"> · {budgetPctLabel(current, maxBudget)}</span>
          ) : null}
          {isMonthlyDuration(limits?.budget_duration) ? (
            <span className="text-text-tertiary">
              {' '}· projected {formatCurrency(projectMonthEnd(current))}
            </span>
          ) : null}
        </span>
      </div>
      <BudgetMeter
        current={current}
        maxBudget={maxBudget}
        duration={limits?.budget_duration}
      />
    </div>
  );
}

export function Dashboard({ me }: DashboardProps) {
  const query = useKeys();
  const { data: teams } = useTeams();
  const openModal = useCreateKeyModalStore((s) => s.openModal);

  // The dashboard owns the delete target; KeysTable's per-row revoke action
  // sets it via onDelete, and DeleteKeyModal is prop-driven by it.
  const [keyToDelete, setKeyToDelete] = useState<KeyRow | null>(null);

  // ── Metric tile values (DASH-06 numeric) ───────────────────────────────────
  // Active keys = non-revoked row count, but ONLY once the keys query has loaded
  // successfully — EM_DASH while pending/errored so we never show a misleading 0.
  const activeKeys =
    query.isSuccess && query.data
      ? formatInt(selectKeyRows(query.data).filter((k) => !isRevoked(k)).length)
      : EM_DASH;
  // Requests (MTD) + tokens (MTD) come from /api/session/stats over the
  // month-to-date range. The range is computed once on mount (a fresh `new Date()`
  // each render would thrash the query key). While loading/errored or absent it
  // degrades to EM_DASH; otherwise we show "<req>req / <tokens>tokens" with the
  // units de-emphasized at a smaller size so the composite fits the tile.
  const mtdRange = useMemo(() => presetToRange('This month', new Date()), []);
  const stats = useStats(mtdRange);
  const requestsValue: ReactNode =
    stats.isSuccess && stats.data ? (
      <span className="text-lg">
        {abbreviate(stats.data.totals.requests)}
        <span className="text-text-tertiary text-xs font-normal"> req</span>
        <span className="text-text-tertiary"> / </span>
        {abbreviate(stats.data.totals.tokens)}
        <span className="text-text-tertiary text-xs font-normal"> tokens</span>
      </span>
    ) : (
      EM_DASH
    );
  // Spend MTD uses the documented me.spend.current fallback from dashboard.js;
  // the stats-window total replaces it in Phase 4.
  const spendValue = formatCurrency(me.spend.current);
  // Per-day sparkline series for the flow tiles — free, drawn from the SAME
  // MTD stats query the Requests tile already reads (no extra fetch). Empty
  // while the query is pending/errored; Sparkline no-ops on <2 pts / flat.
  const series =
    stats.isSuccess && stats.data?.series ? stats.data.series : [];
  const requestsSpark = useMemo(() => series.map((p) => p.requests), [series]);
  const spendSpark = useMemo(() => series.map((p) => p.spend), [series]);
  // Team tile lists ALL the user's member teams (read-only — no active-team
  // switching). Falls back to the single me.team_id, then EM_DASH, when the
  // teams query is empty/unavailable.

  return (
    <div className="flex flex-col gap-8">
      {/* DASH-01: greeting + endpoint chip (full width) */}
      <div className="flex flex-wrap items-start justify-between gap-5">
        <div className="font-sans text-2xl font-semibold leading-snug text-text-primary">
          Welcome back, <span className="text-primary">{me.name || EM_DASH}</span>
        </div>
        <EndpointChip endpoint={me.endpoint} />
      </div>

      {/* DASH-06: four-tile metric header */}
      <div className="grid grid-cols-4 gap-3 max-[880px]:grid-cols-2 max-[520px]:grid-cols-1">
        <MetricTile label="Active keys" value={activeKeys} icon={Key} />
        <TeamTile teams={teams ?? []} fallback={me.team_id || EM_DASH} />
        <MetricTile
          label="Requests (MTD)"
          value={requestsValue}
          icon={BarChart3}
          spark={requestsSpark}
        />
        <MetricTile
          label="Spend (MTD)"
          value={spendValue}
          icon={DollarSign}
          spark={spendSpark}
        />
      </div>

      {/* DASH-06: account budget bar */}
      <BudgetBar limits={me.limits} spend={me.spend} />

      {/* DASH-02: API KEYS section — full width (the dashboard has no sidebar) */}
      <div className="flex min-w-0 flex-col gap-5">
        <div className="flex flex-wrap items-end justify-between gap-5">
          <div>
            <h1 className="font-sans text-2xl font-semibold leading-snug text-text-primary">
              API Keys
            </h1>
            <p className="mt-1 max-w-2xl font-sans text-sm text-text-secondary">
              Create and manage your LiteLLM virtual keys.
            </p>
          </div>
          <button
            type="button"
            onClick={openModal}
            className="inline-flex cursor-pointer items-center justify-center rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90"
          >
            + New Key
          </button>
        </div>
        <KeysTable onDelete={setKeyToDelete} />
      </div>

      <DeleteKeyModal keyToDelete={keyToDelete} onClose={() => setKeyToDelete(null)} />
    </div>
  );
}
