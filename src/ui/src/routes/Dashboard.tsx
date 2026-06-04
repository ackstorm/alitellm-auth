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
import type {
  KeyRow,
  SessionLimits,
  SessionMe,
  SessionSpend,
} from '@/lib/api-types';
import { abbreviate, formatCurrency, formatInt } from '@/lib/format';
import { isRevoked, selectKeyRows } from '@/lib/keys';
import { presetToRange } from '@/lib/stats-presets';
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
    <div className="flex items-center gap-3 rounded-2xl border border-border bg-surface px-4 py-2">
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

// ── MetricTile ───────────────────────────────────────────────────────────────
// One of the four numeric/text tiles (DASH-06): a small lucide accent icon +
// 11px caption label + 24px heading value. Value-only — no sparkline/chart.
function MetricTile({
  label,
  value,
  icon: Icon,
}: {
  label: string;
  value: ReactNode;
  icon: typeof Key;
}) {
  return (
    <div className="flex flex-col gap-2 rounded-2xl border border-border bg-surface p-5">
      <div className="flex items-center gap-2">
        <span className="inline-flex size-[26px] shrink-0 items-center justify-center rounded-lg border border-border">
          <Icon className="size-[15px] text-primary" aria-hidden="true" />
        </span>
        <div className="font-mono text-[11px] font-semibold uppercase tracking-wider text-text-tertiary">
          {label}
        </div>
      </div>
      <div className="break-words font-sans text-2xl font-semibold leading-tight text-text-primary">
        {value}
      </div>
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
      <div className="flex flex-col gap-2 rounded-2xl border border-border bg-surface p-5">
        <div className="flex items-baseline justify-between gap-3">
          <span className="font-mono text-[11px] font-semibold uppercase tracking-wider text-text-tertiary">
            Account budget
          </span>
          <span className="font-mono text-xs text-text-secondary">
            {formatCurrency(current)} · no budget set
          </span>
        </div>
        <div className="flex h-2 overflow-hidden rounded-full border border-border bg-background">
          <div className="h-full bg-border" style={{ width: '0%' }} />
        </div>
      </div>
    );
  }

  const ratio = current / maxBudget;
  const fillPct = Math.max(0, Math.min(1, ratio)) * 100;
  const over = ratio > 1;

  return (
    <div className="flex flex-col gap-2 rounded-2xl border border-border bg-surface p-5">
      <div className="flex items-baseline justify-between gap-3">
        <span className="font-mono text-[11px] font-semibold uppercase tracking-wider text-text-tertiary">
          Account budget
        </span>
        <span className="font-mono text-xs text-text-secondary">
          {formatCurrency(current)} of {formatCurrency(maxBudget)}
        </span>
      </div>
      <div className="flex h-2 overflow-hidden rounded-full border border-border bg-background">
        <div
          className={over ? 'h-full bg-destructive' : 'h-full bg-primary'}
          style={{ width: `${fillPct}%` }}
        />
      </div>
    </div>
  );
}

export function Dashboard({ me }: DashboardProps) {
  const query = useKeys();
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
  const teamValue = me.team_id || EM_DASH;

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
        <MetricTile label="Requests (MTD)" value={requestsValue} icon={BarChart3} />
        <MetricTile label="Spend (MTD)" value={spendValue} icon={DollarSign} />
        <MetricTile label="Team" value={teamValue} icon={Users} />
      </div>

      {/* DASH-06: account budget bar */}
      <BudgetBar limits={me.limits} spend={me.spend} />

      {/* DASH-02: API KEYS section — full width (the dashboard has no sidebar) */}
      <div className="flex min-w-0 flex-col gap-5">
        <div className="flex flex-wrap items-end justify-between gap-5">
          <div>
            <div className="font-mono text-[11px] font-semibold uppercase tracking-widest text-text-secondary">
              API KEYS
            </div>
            <div className="mt-1 font-sans text-sm text-text-secondary">
              Create and manage your LiteLLM virtual keys.
            </div>
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
