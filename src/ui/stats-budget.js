// stats-budget.js — the Budget status panel for the #/stats Usage & Spend page
// (STATS-08). Preact + htm tagged templates, no JSX, no TypeScript (inherited
// 13-CONTEXT D-04).
//
// This REUSES the dashboard `BudgetBar` logic (dashboard.js:82-118) VERBATIM in
// shape so the page never reintroduces the FID-03 `$0.00 of $0.00` full-green
// 100%-bar defect (CONTEXT D-09):
//   • No budget (budget.has_budget === false / max_budget null) -> HIDE the bar
//     and show `${current} spent · no budget set`. NEVER divide by zero, NEVER a
//     full-green bar with no budget.
//   • Has budget -> a single fill clamped to [0,100]% of an 8px track, colored
//     --accent under budget and switched to --destructive (.budget-fill--over)
//     once current > max_budget. Summing two flex children misrepresented the
//     magnitude (a 2x overspend read as 50/50 — WR-01); the fill width is the
//     spend ratio and the over-budget state is signalled by color.
//
// This is a PURE presentational leaf — no fetch, no data ownership. The 13-05
// container passes the Phase-12 `budget` slice. The CSS is re-namespaced
// (`.stats-budget`) to avoid colliding with the dashboard `.budget-bar` while
// keeping the identical token-only, 8px-track, 999px-radius treatment.
//
// SECURITY (threat T-13-06, info disclosure — ACCEPTED): the budget figures are
// session-scoped, server-shaped (Phase 12); the browser never touches the master
// key or `sk-`. Numeric values pass through format.js (plain strings) and render
// as Preact text children via htm (auto-escaped) — no innerHTML.
import { h } from "preact";
import htm from "htm";
import { formatCurrency } from "./format.js";

const html = htm.bind(h);

// Locked copy (13-UI-SPEC §Copywriting Contract / §7).
const SECTION_LABEL = "BUDGET STATUS";

// ── BudgetPanel ────────────────────────────────────────────────────────────────
// Props:
//   budget — the Phase-12 `budget` slice:
//            {current, max_budget, source, pct, has_budget}
//
// Mirrors dashboard.js BudgetBar (dashboard.js:82-118) in shape.
export function BudgetPanel({ budget }) {
  const b = budget || {};
  const current = typeof b.current === "number" ? b.current : 0;
  const maxBudget = typeof b.max_budget === "number" ? b.max_budget : null;
  // has_budget is the authority; a null max_budget is also "no budget".
  const hasBudget = b.has_budget === true && maxBudget !== null;

  // No budget set: hide the bar, show the spent-no-budget copy. This is the
  // exact FID-03 defect-avoidance the dashboard already ships — never a
  // divide-by-zero, never a full-green 100% bar (D-09).
  if (!hasBudget) {
    return html`
      <div class="stats-budget stats-budget--none">
        <div class="stats-budget-label">${SECTION_LABEL}</div>
        <div class="stats-budget-none">${formatCurrency(current)} spent · no budget set</div>
      </div>
    `;
  }

  // Budget present. Prefer the server-computed `budget.pct` (0..100) when it is
  // a finite number; otherwise derive the ratio from current/max_budget with the
  // dashboard.js:100 divide-by-zero guard (maxBudget > 0 ? ratio : 1). The fill
  // is a SINGLE width clamped to [0,100]%; over-budget is signalled by color.
  const ratio = maxBudget > 0 ? current / maxBudget : 1;
  const pctFromContract =
    typeof b.pct === "number" && Number.isFinite(b.pct) ? b.pct : null;
  const fillPct =
    pctFromContract !== null
      ? Math.max(0, Math.min(100, pctFromContract))
      : Math.max(0, Math.min(1, ratio)) * 100;
  const over = current > maxBudget;

  return html`
    <div class="stats-budget">
      <div class="stats-budget-head">
        <span class="stats-budget-label">${SECTION_LABEL}</span>
        <span class="stats-budget-figure">${formatCurrency(current)} of ${formatCurrency(maxBudget)}</span>
      </div>
      <div class="stats-budget-track">
        <div
          class="stats-budget-fill ${over ? "stats-budget-fill--over" : ""}"
          style=${`width:${fillPct}%`}
        ></div>
      </div>
    </div>
  `;
}

// ── Component stylesheet — var(--*) tokens only ───────────────────────────────
// Re-namespaced clone of the dashboard `.budget-bar` treatment
// (dashboard.js:318-335): 16px-radius --surface card, 8px track with a 999px
// radius, --accent fill switching to --destructive when over budget, and the
// 14px --dim no-budget copy. NEVER a raw hex — var(--*) only. Concatenated into
// app.js's injectShellStyles (wired in 13-05).
export const STATS_BUDGET_CSS = `
.stats-budget {
  background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
  padding: var(--space-lg); display: flex; flex-direction: column; gap: var(--space-sm);
}
.stats-budget .stats-budget-head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-md); }
.stats-budget .stats-budget-label {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 1px; color: var(--dim);
}
.stats-budget .stats-budget-figure { font-family: var(--mono); font-size: 12px; color: var(--text); }
.stats-budget .stats-budget-track {
  display: flex; height: 8px; border-radius: 999px; overflow: hidden;
  background: var(--bg); border: 1px solid var(--border);
}
.stats-budget .stats-budget-fill { height: 100%; background: var(--accent); flex-shrink: 0; transition: width .25s; }
.stats-budget .stats-budget-fill--over { background: var(--destructive); }
.stats-budget .stats-budget-none { font-family: var(--sans); font-size: 14px; color: var(--dim); }
`;
