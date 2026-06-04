// stats-kpis.js — the 4-card KPI row for the #/stats Usage & Spend page
// (STATS-02). Preact + htm tagged templates, no JSX, no TypeScript (inherited
// 13-CONTEXT D-04 / 09-CONTEXT D-04).
//
// This is a PURE presentational leaf — no fetch, no data ownership. The 13-05
// container passes the Phase-12 `totals` slice + `capabilities` + the Compare
// toggle state + `range.days`. Mirrors the `dashboard.js` `MetricTile`
// (dashboard.js:68-75) structure and the `.metric-tiles` grid
// (dashboard.js:303-316) with the identical 4->2->1 responsive collapse
// (dashboard.js:347-352).
//
// The delta chip follows the LOCKED semantic-direction color table
// (13-UI-SPEC §Color, "Semantic delta direction"): "up" is NOT universally good.
//   • Total Requests / Total Tokens -> accent ▲ (good) / dim ▼
//   • Spend                         -> --dim both directions (neutral)
//   • Avg Cost / 1K req             -> --destructive ▲ (bad) / --accent ▼ (good)
//   • any null *_pct                -> neutral `—` chip in --dim, no arrow
// The chip is shown ONLY when Compare is on AND capabilities.deltas is true AND
// the metric's *_pct is non-null (13-UI-SPEC §2 / CONTEXT D-12/D-15).
//
// SECURITY (threat T-13-06, info disclosure — ACCEPTED): all figures are
// session-scoped, server-shaped (Phase 12); the browser never touches the master
// key or `sk-`. Numeric values pass through format.js formatters (plain strings)
// and render as Preact text children via htm (auto-escaped) — no innerHTML.
import { h } from "preact";
import htm from "htm";
import { abbreviate, formatCurrency } from "./format.js";

const html = htm.bind(h);

// The em-dash placeholder (matches format.js EM_DASH / 13-UI-SPEC §Typography).
const EM_DASH = "—";

// Per-metric semantic disposition (13-UI-SPEC §Color). `tone` selects the chip
// color CLASS for a positive vs negative delta; `null` pct is always neutral.
//   "good-up"  : up is good   (Requests, Tokens) -> accent ▲ / dim ▼
//   "neutral"  : neither good nor bad (Spend)    -> --dim both
//   "bad-up"   : up is bad    (Avg cost)         -> destructive ▲ / accent ▼
const SEMANTICS = {
  requests: "good-up",
  tokens: "good-up",
  spend: "neutral",
  avg_cost_per_1k_req: "bad-up",
};

// Resolve the chip color class + arrow glyph for a metric + its pct fraction,
// per the LOCKED §Color table. A null pct -> neutral `—` chip, no arrow.
function chipStyle(metricKey, pct) {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) {
    return { cls: "kpi-delta--neutral", arrow: "" };
  }
  const up = pct > 0;
  const arrow = up ? "▲" : "▼";
  const tone = SEMANTICS[metricKey] || "neutral";

  if (tone === "neutral") {
    return { cls: "kpi-delta--neutral", arrow };
  }
  if (tone === "good-up") {
    // up is good -> accent ▲ ; down is the neutral-down dim ▼.
    return { cls: up ? "kpi-delta--good" : "kpi-delta--neutral", arrow };
  }
  // "bad-up": up is bad -> destructive ▲ ; down is good -> accent ▼.
  return { cls: up ? "kpi-delta--bad" : "kpi-delta--good", arrow };
}

// Format a contract fraction (e.g. 0.182) as a one-decimal `%` (`18.2%`). The
// sign is dropped from the number because the arrow glyph encodes direction;
// a null/non-finite fraction -> em-dash (never `0%` / `NaN`).
function formatPct(pct) {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) return EM_DASH;
  return `${(Math.abs(pct) * 100).toFixed(1)}%`;
}

// ── KpiCard ──────────────────────────────────────────────────────────────────
// One of the four cards: 11px caption label + 24px heading value (--bright) +
// an optional 12px Label delta chip. `metricKey` drives the semantic color; the
// chip renders ONLY when `showDelta` is true (Compare + capabilities.deltas) —
// a null pct then renders the neutral `—` chip per §Color, never a fake 0%.
function KpiCard({ label, value, metricKey, pct, showDelta }) {
  if (!showDelta) {
    return html`
      <div class="kpi-card">
        <div class="kpi-label">${label}</div>
        <div class="kpi-value">${value}</div>
      </div>
    `;
  }

  const isNull = pct === null || pct === undefined || !Number.isFinite(pct);
  const { cls, arrow } = chipStyle(metricKey, pct);

  return html`
    <div class="kpi-card">
      <div class="kpi-label">${label}</div>
      <div class="kpi-value">${value}</div>
      <div class="kpi-delta ${cls}">
        ${arrow ? html`<span class="kpi-delta-arrow">${arrow}</span>` : null}
        <span class="kpi-delta-pct">${isNull ? EM_DASH : formatPct(pct)}</span>
      </div>
    </div>
  `;
}

// ── KpiRow ───────────────────────────────────────────────────────────────────
// Props:
//   totals       — the Phase-12 `totals` slice:
//                  {requests, tokens, spend, avg_cost_per_1k_req,
//                   deltas:{requests_pct, tokens_pct, spend_pct,
//                           avg_cost_per_1k_req_pct}}
//   capabilities — the contract `capabilities` map (gate: `deltas`)
//   compareOn    — boolean, the Compare toggle state
//   rangeDays    — `range.days`, used for the `vs prior {N} days` label
//
// Renders exactly four cards (TOTAL REQUESTS / TOTAL TOKENS / SPEND /
// AVG COST / 1K REQ) in a `repeat(4,1fr)` grid mirroring `.metric-tiles`. The
// delta chips + the `vs prior {N} days` label appear only when Compare is on AND
// `capabilities.deltas` is true.
export function KpiRow({ totals, capabilities, compareOn, rangeDays }) {
  const t = totals || {};
  const deltas = t.deltas || {};
  const caps = capabilities || {};

  // Chips are shown only when Compare is on AND the server advertises deltas.
  const showDelta = Boolean(compareOn) && caps.deltas === true;

  const cards = [
    {
      label: "TOTAL REQUESTS",
      value: abbreviate(t.requests),
      metricKey: "requests",
      pct: deltas.requests_pct,
    },
    {
      label: "TOTAL TOKENS",
      value: abbreviate(t.tokens),
      metricKey: "tokens",
      pct: deltas.tokens_pct,
    },
    {
      label: "SPEND",
      value: formatCurrency(t.spend),
      metricKey: "spend",
      pct: deltas.spend_pct,
    },
    {
      label: "AVG COST / 1K REQ",
      value: formatCurrency(t.avg_cost_per_1k_req),
      metricKey: "avg_cost_per_1k_req",
      pct: deltas.avg_cost_per_1k_req_pct,
    },
  ];

  // `vs prior {N} days` — {N} = range.days, shown only alongside the chips.
  const n = Number.isFinite(rangeDays) ? rangeDays : null;

  return html`
    <div class="kpi-row">
      <div class="kpi-cards">
        ${cards.map(
          (c) => html`<${KpiCard}
            label=${c.label}
            value=${c.value}
            metricKey=${c.metricKey}
            pct=${c.pct}
            showDelta=${showDelta}
          />`
        )}
      </div>
      ${showDelta && n !== null
        ? html`<div class="kpi-compare-label">vs prior ${n} days</div>`
        : null}
    </div>
  `;
}

// ── Component stylesheet — var(--*) tokens only ───────────────────────────────
// Mirrors `.metric-tiles` / `.metric-tile` (dashboard.js:304-316) and its
// 4->2->1 responsive collapse (dashboard.js:347-352). The delta chip is a 999px
// pill (12px Label number + inline arrow) colored by the §Color semantic table.
// Concatenated into app.js's injectShellStyles (wired in 13-05). NEVER a raw hex.
export const STATS_KPIS_CSS = `
.kpi-row { display: flex; flex-direction: column; gap: var(--space-sm); }
.kpi-cards { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--space-md); }
.kpi-card {
  background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
  padding: var(--space-lg); display: flex; flex-direction: column; gap: var(--space-sm);
}
.kpi-card .kpi-label {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 1px; color: var(--dim);
}
.kpi-card .kpi-value {
  font-family: var(--sans); font-size: 24px; font-weight: 600; color: var(--bright);
  line-height: 1.3; word-break: break-word;
}
.kpi-card .kpi-delta {
  display: inline-flex; align-items: center; gap: var(--space-xs);
  align-self: flex-start; border-radius: 999px;
  padding: var(--space-xs) var(--space-sm);
  font-family: var(--mono); font-size: 12px; line-height: 1;
}
.kpi-card .kpi-delta .kpi-delta-arrow { font-size: 11px; }
.kpi-card .kpi-delta--good { color: var(--accent); background: var(--glow); }
.kpi-card .kpi-delta--bad { color: var(--destructive); background: var(--glow-err); }
.kpi-card .kpi-delta--neutral { color: var(--dim); background: var(--bg); }
.kpi-row .kpi-compare-label {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 1px; color: var(--dim);
}

/* Responsive: cards collapse 4 -> 2 -> 1 (mirrors .metric-tiles). */
@media (max-width: 880px) {
  .kpi-cards { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 520px) {
  .kpi-cards { grid-template-columns: 1fr; }
}
`;
