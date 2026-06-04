// stats-model-table.js — the Model Breakdown DATA-TABLE for the #/stats Usage &
// Spend page (STATS-06). Preact + htm tagged templates, no JSX, no TypeScript
// (inherited 13-CONTEXT D-04).
//
// This is the page's densest surface and the one most at risk of reintroducing
// the FID-03 horizontal-overflow defect. It REUSES the keys-table.js treatment
// VERBATIM in shape (keys-table.js:131-187 container + thead/tbody + status
// branches; keys-table.js:330-344 per-`data-col` `@media display:none` column
// drop) so it NEVER scrolls horizontally — it DROPS low-priority columns at
// breakpoints instead (UI-SPEC §9 / CONTEXT D-09).
//
// PRESENTATIONAL LEAF: it receives the Phase-12 `models[]` slice, the
// `capabilities` map, and a load `status`. No fetch, no data ownership — the
// 13-05 container fetches `/api/session/stats` and passes the slice down.
//
// SECURITY INVARIANTS (threat register 13-04):
//   • T-13-08 (XSS): every cell value (model name, counts, spend) renders as a
//     Preact text child via htm — htm/Preact auto-escapes. No
//     dangerouslySetInnerHTML and no raw-HTML interpolation anywhere.
//
// `null` ≠ `0` (Phase-12 D-08): an unavailable figure renders em-dash, never 0.
// Capability-driven cells (D-15): token_split === false -> INPUT/OUTPUT cells
// em-dash; per_model_last_used === false -> the whole LAST USED column em-dash.
import { h } from "preact";
import htm from "htm";
import { formatCurrency, formatInt, formatDate, abbreviate } from "./format.js";

const html = htm.bind(h);

// The em-dash placeholder (matches format.js EM_DASH) — every null / unavailable
// / capability-disabled cell renders THIS, never a `0`.
const EM_DASH = "—";

// The locked section + empty copy (UI-SPEC §Copywriting Contract / §6).
const EMPTY_COPY = "No usage in this range";

// The LOCKED 8-column order (UI-SPEC §6). The `data-col` for each `<th>`/`<td>`
// is the lowercased, space-stripped header (the keys-table.js:170 idiom) — e.g.
// "% SPEND" -> "%spend", "LAST USED" -> "lastused". The responsive drop rules in
// the CSS key off exactly these `data-col` values.
const COLUMNS = [
  "MODEL", "REQUESTS", "INPUT", "OUTPUT", "TOTAL", "SPEND", "% SPEND", "LAST USED",
];

// Map a header label to its `data-col` token (keys-table.js:170 idiom).
function colKey(header) {
  return header.toLowerCase().replace(/\s+/g, "");
}

// Render the contract's `spend_pct` fraction as a one-decimal `%` (UI-SPEC
// §Typography: 0.182 -> "18.2%"); a null / non-finite fraction -> em-dash, never
// "0%" or "NaN".
function formatPct(fraction) {
  if (typeof fraction !== "number" || !Number.isFinite(fraction)) return EM_DASH;
  return `${(fraction * 100).toFixed(1)}%`;
}

// ── ModelRow ─────────────────────────────────────────────────────────────────
// One table row for a single model. The INPUT/OUTPUT cells collapse to em-dash
// when token_split is unavailable; the LAST USED cell collapses to em-dash when
// per_model_last_used is unavailable OR the row's own last_used is null.
function ModelRow({ item: m, tokenSplit, perModelLastUsed }) {
  const inputCell = tokenSplit === false ? EM_DASH : abbreviate(m.input_tokens);
  const outputCell = tokenSplit === false ? EM_DASH : abbreviate(m.output_tokens);
  const lastUsedCell =
    perModelLastUsed === false ? EM_DASH : formatDate(m.last_used);

  return html`
    <tr class="smt-row">
      <td class="smt-cell smt-cell-model" data-col="model">${m.model == null ? EM_DASH : m.model}</td>
      <td class="smt-cell smt-num" data-col="requests">${formatInt(m.requests)}</td>
      <td class="smt-cell smt-num" data-col="input">${inputCell}</td>
      <td class="smt-cell smt-num" data-col="output">${outputCell}</td>
      <td class="smt-cell smt-num" data-col="total">${abbreviate(m.total_tokens)}</td>
      <td class="smt-cell smt-num" data-col="spend">${formatCurrency(m.spend)}</td>
      <td class="smt-cell smt-num" data-col="%spend">${formatPct(m.spend_pct)}</td>
      <td class="smt-cell smt-cell-lastused" data-col="lastused">${lastUsedCell}</td>
    </tr>
  `;
}

// ── ModelTable ───────────────────────────────────────────────────────────────
// Props: { models, capabilities, status }
//   models       : array of Phase-12 model rows
//                  {model, requests, input_tokens, output_tokens, total_tokens,
//                   spend, spend_pct, last_used}.
//   capabilities : the contract `capabilities` map (token_split,
//                  per_model_last_used, ...). A missing entry is treated as
//                  AVAILABLE — only an explicit `false` collapses a column.
//   status       : "loading" | "ok" | "error".
export function ModelTable({ models, capabilities, status }) {
  const caps = capabilities || {};
  const tokenSplit = caps.token_split;
  const perModelLastUsed = caps.per_model_last_used;

  if (status === "loading") {
    return html`
      <div class="smt-container">
        <div class="smt-state"><div class="smt-state-body">Loading usage…</div></div>
      </div>
    `;
  }

  if (status === "error") {
    return html`
      <div class="smt-container">
        <div class="smt-state">
          <div class="smt-state-error">Couldn't load your usage. Check your connection and retry.</div>
        </div>
      </div>
    `;
  }

  const rows = Array.isArray(models) ? models : [];

  if (rows.length === 0) {
    return html`
      <div class="smt-container">
        <div class="smt-state"><div class="smt-state-body">${EMPTY_COPY}</div></div>
      </div>
    `;
  }

  // Default sort: SPEND descending (UI-SPEC §6 — matches the donut's spend-share
  // narrative). Copy before sorting so the parent's array is never mutated; a
  // missing/non-numeric spend sorts last (treated as -Infinity).
  const spendOf = (m) =>
    typeof m.spend === "number" && Number.isFinite(m.spend) ? m.spend : -Infinity;
  const sorted = rows.slice().sort((a, b) => spendOf(b) - spendOf(a));

  return html`
    <div class="smt-container">
      <table class="smt-table">
        <thead>
          <tr>
            ${COLUMNS.map(
              (c) => html`<th class="smt-col-header" data-col=${colKey(c)}>${c}</th>`,
            )}
          </tr>
        </thead>
        <tbody>
          ${sorted.map(
            (m, i) => html`<${ModelRow}
              key=${m.model || i}
              item=${m}
              tokenSplit=${tokenSplit}
              perModelLastUsed=${perModelLastUsed}
            />`,
          )}
        </tbody>
      </table>
    </div>
  `;
}

// ── Component stylesheet — var(--*) tokens only ───────────────────────────────
// A re-namespaced clone of the keys-table.js treatment (keys-table.js:194-345):
// the 16px-radius --surface container, the 11px caption column headers, 12px
// mono cells, 1px --border row dividers, and CRUCIALLY the per-`data-col`
// `@media display:none` column-drop (keys-table.js:330-344) that GUARANTEES the
// table never overflows horizontally (FID-03 avoidance — UI-SPEC §9 drop order:
// INPUT/OUTPUT first, then % SPEND, then LAST USED; MODEL and SPEND ALWAYS
// visible). NEVER a raw hex — var(--*) only (the one rgba(...) matches the
// keys-table.js row-action border, an allowed literal). Concatenated into
// app.js's injectShellStyles (wired in 13-05).
export const STATS_MODEL_TABLE_CSS = `
/* Table container — the 16px --surface card shape. overflow-x is a belt-and-
 * suspenders guard ONLY; the no-overflow GUARANTEE is the @media column drop
 * below, not horizontal scroll (FID-03 — the table must fit by dropping cols). */
.smt-container {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: var(--space-lg);
  overflow-x: hidden;
}

.smt-table { width: 100%; border-collapse: collapse; table-layout: fixed; }

/* Column headers — 11px caption role (mono, ALL-CAPS, --dim). */
.smt-table .smt-col-header {
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: var(--dim);
  text-align: right;
  padding: var(--space-sm) var(--space-md);
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}
/* MODEL header + LAST USED are left-aligned; numeric columns are right-aligned. */
.smt-table .smt-col-header[data-col="model"],
.smt-table .smt-col-header[data-col="lastused"] { text-align: left; }

/* Rows — 1px --border divider; sm vertical / md horizontal cell padding. */
.smt-table .smt-row td {
  padding: var(--space-sm) var(--space-md);
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
}
.smt-table .smt-row:last-child td { border-bottom: none; }

/* Data cells — 12px mono. Numeric cells right-aligned. */
.smt-table .smt-cell {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--text);
  white-space: nowrap;
}
.smt-table .smt-num { text-align: right; }
/* MODEL cell — --bright, truncates long model ids rather than widening. */
.smt-table .smt-cell-model {
  color: var(--bright);
  text-align: left;
  max-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
}
.smt-table .smt-cell-lastused { text-align: left; }

/* Empty / loading / error states — centered inside the container. */
.smt-state { text-align: center; padding: var(--space-3xl) var(--space-lg); }
.smt-state-body { font-family: var(--sans); font-size: 14px; color: var(--dim); }
.smt-state-error { font-family: var(--sans); font-size: 14px; color: var(--destructive); }

/* ── No-horizontal-overflow column drop (UI-SPEC §9 / CONTEXT D-09 / FID-03) ────
 * Recommended drop order: INPUT/OUTPUT first, then % SPEND, then LAST USED.
 * MODEL and SPEND are NEVER dropped. This is the no-overflow GUARANTEE — the
 * table sheds columns so it always fits its container; it never scrolls. */
@media (max-width: 1024px) {
  .smt-table .smt-col-header[data-col="input"],
  .smt-table .smt-cell[data-col="input"],
  .smt-table .smt-col-header[data-col="output"],
  .smt-table .smt-cell[data-col="output"] { display: none; }
}
@media (max-width: 860px) {
  .smt-table .smt-col-header[data-col="%spend"],
  .smt-table .smt-cell[data-col="%spend"] { display: none; }
}
@media (max-width: 680px) {
  .smt-table .smt-col-header[data-col="lastused"],
  .smt-table .smt-cell[data-col="lastused"] { display: none; }
}
`;
