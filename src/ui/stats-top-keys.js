// stats-top-keys.js — the Top API Keys panel for the #/stats Usage & Spend page
// (STATS-07). Preact + htm tagged templates, no JSX, no TypeScript (inherited
// 13-CONTEXT D-04).
//
// Ranks the user's keys by spend with HAND-ROLLED horizontal bars (no chart
// dep). Each bar REUSES the dashboard `.budget-track`/`.budget-fill` shape
// (dashboard.js:104-117,329-334) — an 8px track with an --accent fill whose
// width is ∝ `spend_pct` (clamped [0,100], divide-by-zero guarded).
//
// PRESENTATIONAL LEAF: it receives the Phase-12 `keys[]` slice (already spend
// desc from the contract), the `capabilities` map, and a render `mode`. No fetch,
// no data ownership — the 13-05 container fetches `/api/session/stats`.
//
// SECURITY INVARIANTS (threat register 13-04):
//   • T-13-08 (XSS): the key label (key_alias || maskKey(id)) and every figure
//     render as Preact text children via htm — htm/Preact auto-escapes. No
//     dangerouslySetInnerHTML and no raw-HTML interpolation anywhere.
//   • T-13-10 (info disclosure — ACCEPTED): `maskKey` shows only a public
//     `key-…last4` form; the full `sk-` is never client-side on this read-only
//     page. The key id is a PUBLIC identifier, so an alias-less key is masked
//     via maskKey(id), never the secret.
import { h } from "preact";
import htm from "htm";
import { formatCurrency, formatInt, maskKey } from "./format.js";

const html = htm.bind(h);

// The em-dash placeholder (matches format.js EM_DASH).
const EM_DASH = "—";

// Locked copy (13-UI-SPEC §Copywriting Contract / §5).
const SECTION_LABEL = "TOP API KEYS";
const COL_KEY = "KEY";
const COL_REQUESTS = "REQUESTS";
const COL_SPEND = "SPEND";
const COL_PCT = "% OF TOTAL";
const COMING_SOON_COPY = "Coming soon";
const EMPTY_COPY = "No usage in this range";

// Render the contract's `spend_pct` fraction as a one-decimal `%` (UI-SPEC
// §Typography: 0.182 -> "18.2%"); a null / non-finite fraction -> em-dash.
function formatPct(fraction) {
  if (typeof fraction !== "number" || !Number.isFinite(fraction)) return EM_DASH;
  return `${(fraction * 100).toFixed(1)}%`;
}

// The bar fill width as a clamped 0..100 percentage of the contract `spend_pct`
// fraction. Divide-by-zero / null / non-finite -> 0 (an empty track), never NaN.
function barWidthPct(fraction) {
  if (typeof fraction !== "number" || !Number.isFinite(fraction)) return 0;
  return Math.max(0, Math.min(100, fraction * 100));
}

// ── KeyRow ───────────────────────────────────────────────────────────────────
// One ranked key row: the label, the hand-rolled horizontal spend-share bar, the
// spend figure, and the `% OF TOTAL`.
function KeyRow({ item: k }) {
  // Public key id is shown masked when there is no alias (maskKey preserves the
  // real `key-` prefix; the full sk- is never client-side here — T-13-10).
  const label = k.key_alias || maskKey(k.id);
  const width = barWidthPct(k.spend_pct);

  return html`
    <div class="stk-row">
      <div class="stk-label" title=${label}>${label == null ? EM_DASH : label}</div>
      <div class="stk-bar">
        <div class="stk-track">
          <div class="stk-fill" style=${`width:${width}%`}></div>
        </div>
      </div>
      <div class="stk-requests">${formatInt(k.requests)}</div>
      <div class="stk-spend">${formatCurrency(k.spend)}</div>
      <div class="stk-pct">${formatPct(k.spend_pct)}</div>
    </div>
  `;
}

// ── TopKeys ──────────────────────────────────────────────────────────────────
// Props: { keys, capabilities, mode }
//   keys         : array of Phase-12 key rows {id, key_alias, requests, spend,
//                  spend_pct} — already spend desc from the contract.
//   capabilities : the contract `capabilities` map (per_key_spend, ...). An
//                  explicit `per_key_spend === false` forces the coming-soon
//                  panel state regardless of `mode`.
//   mode         : optional "ready" | "coming-soon" | "empty" (from
//                  capabilityRenderMode). When absent it is derived from
//                  capabilities + the keys length.
//
// The max number of ranked rows shown (UI-SPEC §5 "top N per the mockup").
const TOP_N = 8;

export function TopKeys({ keys, capabilities, mode }) {
  const caps = capabilities || {};
  const rows = Array.isArray(keys) ? keys : [];

  // per_key_spend === false (or an explicit coming-soon mode) -> the panel-level
  // coming-soon state (D-15): no bars, em-dash where a figure would sit.
  const comingSoon = caps.per_key_spend === false || mode === "coming-soon";
  if (comingSoon) {
    return html`
      <div class="stk-panel">
        <div class="stk-head"><span class="stk-section-label">${SECTION_LABEL}</span></div>
        <div class="stk-state">
          <div class="stk-state-coming">${COMING_SOON_COPY}</div>
          <div class="stk-state-dash">${EM_DASH}</div>
        </div>
      </div>
    `;
  }

  // A real but empty keys: [] (or an explicit empty mode) -> the no-usage state.
  if (rows.length === 0 || mode === "empty") {
    return html`
      <div class="stk-panel">
        <div class="stk-head"><span class="stk-section-label">${SECTION_LABEL}</span></div>
        <div class="stk-state"><div class="stk-state-body">${EMPTY_COPY}</div></div>
      </div>
    `;
  }

  const ranked = rows.slice(0, TOP_N);

  return html`
    <div class="stk-panel">
      <div class="stk-head"><span class="stk-section-label">${SECTION_LABEL}</span></div>
      <div class="stk-table">
        <div class="stk-colhead">
          <span class="stk-col stk-col-key">${COL_KEY}</span>
          <span class="stk-col stk-col-bar"></span>
          <span class="stk-col stk-col-requests">${COL_REQUESTS}</span>
          <span class="stk-col stk-col-spend">${COL_SPEND}</span>
          <span class="stk-col stk-col-pct">${COL_PCT}</span>
        </div>
        ${ranked.map(
          (k, i) => html`<${KeyRow} key=${k.id || i} item=${k} />`,
        )}
      </div>
    </div>
  `;
}

// ── Component stylesheet — var(--*) tokens only ───────────────────────────────
// The 16px-radius --surface panel, an 11px caption section label + column heads,
// and the hand-rolled horizontal bars reusing the dashboard budget-bar shape
// (dashboard.js:329-334): an 8px track (999px radius, --bg fill, 1px --border)
// with an --accent fill. NEVER a raw hex — var(--*) only. Concatenated into
// app.js's injectShellStyles (wired in 13-05).
export const STATS_TOP_KEYS_CSS = `
.stk-panel {
  background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
  padding: var(--space-lg); display: flex; flex-direction: column; gap: var(--space-md);
}
.stk-head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-md); }
.stk-section-label {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 1.5px; color: var(--dim);
}

.stk-table { display: flex; flex-direction: column; gap: var(--space-sm); }

/* Shared 5-track grid: KEY | bar (flex) | REQUESTS | SPEND | % OF TOTAL. */
.stk-colhead,
.stk-row {
  display: grid;
  grid-template-columns: minmax(80px, 1.4fr) minmax(0, 2fr) 72px 88px 80px;
  align-items: center;
  gap: var(--space-md);
}
.stk-colhead { padding-bottom: var(--space-xs); border-bottom: 1px solid var(--border); }
.stk-col {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 1px; color: var(--dim);
}
.stk-col-requests, .stk-col-spend, .stk-col-pct { text-align: right; }

.stk-row { padding: var(--space-xs) 0; }
.stk-label {
  font-family: var(--mono); font-size: 12px; color: var(--bright);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.stk-requests, .stk-spend, .stk-pct {
  font-family: var(--mono); font-size: 12px; color: var(--text); text-align: right; white-space: nowrap;
}

/* Hand-rolled horizontal spend-share bar — the dashboard budget-bar shape. */
.stk-bar { width: 100%; }
.stk-track {
  height: 8px; border-radius: 999px; overflow: hidden;
  background: var(--bg); border: 1px solid var(--border);
}
.stk-fill { height: 100%; background: var(--accent); transition: width .25s; }

/* Coming-soon / empty states. */
.stk-state { text-align: center; padding: var(--space-xl) var(--space-lg); }
.stk-state-coming {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 1px; color: var(--dim);
}
.stk-state-dash { font-family: var(--mono); font-size: 12px; color: var(--dim); margin-top: var(--space-sm); }
.stk-state-body { font-family: var(--sans); font-size: 14px; color: var(--dim); }

/* Responsive: drop REQUESTS, then % OF TOTAL, keeping KEY/bar/SPEND. */
@media (max-width: 768px) {
  .stk-colhead, .stk-row { grid-template-columns: minmax(72px, 1.4fr) minmax(0, 2fr) 88px 80px; }
  .stk-col-requests, .stk-requests { display: none; }
}
@media (max-width: 520px) {
  .stk-colhead, .stk-row { grid-template-columns: minmax(64px, 1.4fr) minmax(0, 2fr) 88px; }
  .stk-col-pct, .stk-pct { display: none; }
}
`;
