// keys-table.js — the keys-as-DATA-TABLE surface for the alitellm-auth
// dashboard (DASH-02 / DASH-03 / DASH-06). Preact + htm tagged templates, no
// JSX, no TypeScript (inherited 09-CONTEXT D-04).
//
// This is a PRESENTATIONAL LEAF: it receives the projected `/keys` rows, a
// `freshKeys` map (id -> full sk- held only in parent memory this session), a
// load `status`, and an `onDelete(key)` callback. It performs NO fetch and owns
// NO data — the dashboard container fetches `/keys`, holds the fresh-key map,
// and wires the actual DELETE + confirm modal. This module renders the locked
// 6-column table (Phase 14 D-04: Name+Key ID merged into one Key ID column),
// the Active/Expired/Revoked status pills (D-08), a chevron-toggled expandable
// usage detail (D-05 — per-key spend/tpm/rpm/budget relocated out of the Actions
// cell that previously caused the FID-03 horizontal overflow), compact icon row
// actions (D-06 — reveal/copy/revoke), client-side pagination with an
// always-rendered `Showing X of Y` caption (D-07), the empty state and the
// load-error state.
//
// SECURITY INVARIANTS (threat register 10-03 / 14-03):
//   • T-10-06 / T-10-14 (XSS): every cell/detail/pill value renders as a Preact
//     text child via htm — htm/Preact auto-escapes. No raw-HTML inner-HTML sink
//     and no raw-HTML interpolation are used anywhere.
//   • T-10-07 (info disclosure, fresh keys): the full sk- lives ONLY in the
//     in-memory `freshKeys` map (parent-owned, lost on refresh — D-01). It is
//     never written to any web-storage API and never logged. reveal/copy fire
//     only on an explicit user click.
//   • T-10-08 (info disclosure, pre-existing keys): pre-existing keys have NO full
//     value client-side — copy emits only the key_id, no reveal button is rendered.
import { h } from "preact";
import { useState } from "preact/hooks";
import htm from "htm";
import { formatCurrency, formatInt, formatDate, maskKey } from "./format.js";
import { useCopyFeedback } from "./clipboard.js";

const html = htm.bind(h);

// The em-dash placeholder (matches format.js EM_DASH) for the always-empty
// "Last used" cell and the per-key budget cell (D-17 — inherited from account).
const EM_DASH = "—";

// The masked fresh-key default — a fixed-width run of bullets shown until the
// user explicitly toggles `reveal`. NOT derived from the secret (no length leak).
const MASKED_FRESH = "sk-••••••••••••••••••••";

// Client-side page size (D-07). Prev/Next render only when total rows exceed it.
const PAGE_SIZE = 10;

// The locked column set (UI-SPEC §C2 / §Copywriting Contract). Order is fixed.
// D-04 collapsed the 7-col set to 6 by merging the old `Name` + `Key ID` columns
// into ONE `Key ID` column (alias on top, key id beneath). Removing the column
// (and relocating the usage line out of Actions, D-05) is the FID-03 no-overflow
// fix — the 6-col table fits the 1200px main column without a horizontal scroll.
const COLUMNS = [
  "Key ID", "Created", "Last used", "Expires", "Status", "Actions",
];

// A key is "Revoked" when an explicit revoked/blocked flag is truthy. The
// projected /keys shape carries no positive "active" field, so absence == active
// (UI-SPEC §C4 "Active … when not revoked").
function isRevoked(key) {
  return Boolean(key && (key.revoked || key.blocked));
}

// D-08: a key is "Expired" when its expiry is in the past — computed from the
// projected `expires` field — and only when it is NOT already revoked. Revoked
// takes precedence (a revoked key reads `Revoked`, never `Expired`).
function isExpired(key) {
  if (!key || key.expires == null) return false;
  const ts = Date.parse(key.expires);
  return Number.isFinite(ts) && ts < Date.now();
}

// ── Inline-SVG icon glyphs (reuse the login.js `.vp-icon` --accent idiom) ──────
// 24x24 viewBox stroke icons; sized + colored by .row-action CSS. Text-free —
// the accessible name comes from the button's aria-label/title.
const IconEye = html`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>`;
const IconCopy = html`<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h10"/></svg>`;
const IconTrash = html`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="m6 6 1 14a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-14"/></svg>`;
const IconChevron = html`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m6 9 6 6 6-6"/></svg>`;

// ── KeyRow ─────────────────────────────────────────────────────────────────────
// One table row plus its expandable detail row. `fresh` is the full sk- for this
// row when it was minted this session (else undefined). Reveal/copy reconcile to
// D-01: fresh keys get a reveal toggle + full-value copy; pre-existing keys get
// key_id copy + a masked sk-…last4 display and NO reveal button.
function KeyRow({ item: k, fresh, onDelete }) {
  const [revealed, setRevealed] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const { copied, copy } = useCopyFeedback();

  const revoked = isRevoked(k);
  const expired = !revoked && isExpired(k);
  const id = k.id;
  const name = k.key_alias || maskKey(id);

  // Status pill — Revoked > Expired > Active precedence (UI-SPEC §C4).
  const statusClass = revoked ? "is-revoked" : expired ? "is-expired" : "is-active";
  const statusLabel = revoked ? "Revoked" : expired ? "Expired" : "Active";

  // What `copy` writes, and what the inline key chip displays:
  //   fresh        -> full sk- (copy), masked-or-revealed chip
  //   pre-existing -> key_id   (copy), the key_id verbatim chip
  // The key id is a PUBLIC identifier (key-...), not a secret, so it is shown
  // as-is rather than masked through maskKey() — masking it would discard the
  // real `key-` prefix and misrepresent a public id as a masked secret (WR-02).
  const copyValue = fresh !== undefined ? fresh : id;
  const chipDisplay =
    fresh !== undefined
      ? revealed
        ? fresh
        : MASKED_FRESH
      : id == null
        ? EM_DASH
        : id;

  return html`
    <tr class="key-row" data-revoked=${revoked}>
      <td class="cell-keyid" data-col="keyid">
        <div class="keyid-stack">
          <button
            type="button"
            class="row-expand ${expanded ? "is-open" : ""}"
            aria-label=${expanded ? "Hide usage" : "Show usage"}
            aria-expanded=${expanded}
            title="Usage"
            onClick=${() => setExpanded((v) => !v)}
          >${IconChevron}</button>
          <div class="keyid-lines">
            <div class="keyid-name">${name}</div>
            <div class="keyid-id">
              <span class="key-chip ${fresh !== undefined && revealed ? "is-revealed" : ""}">${chipDisplay}</span>
            </div>
          </div>
        </div>
      </td>
      <td class="cell-created" data-col="created">${formatDate(k.created_at)}</td>
      <td class="cell-lastused" data-col="lastused">${EM_DASH}</td>
      <td class="cell-expires" data-col="expires">${k.expires == null ? "Never" : formatDate(k.expires)}</td>
      <td class="cell-status" data-col="status">
        <span class="status-pill ${statusClass}">${statusLabel}</span>
      </td>
      <td class="cell-actions" data-col="actions">
        <div class="row-actions">
          ${fresh !== undefined
            ? html`<button
                type="button"
                class="row-action action-reveal ${revealed ? "is-on" : ""}"
                aria-label=${revealed ? "Hide key" : "Reveal"}
                title="Reveal"
                onClick=${() => setRevealed((v) => !v)}
              >${IconEye}</button>`
            : null}
          <button
            type="button"
            class="row-action action-copy ${copied ? "is-copied" : ""}"
            aria-label=${copied ? "Copied" : "Copy"}
            title="Copy"
            onClick=${() => copy(copyValue)}
          >${IconCopy}</button>
          <button
            type="button"
            class="row-action action-delete"
            aria-label="Revoke"
            title="Revoke"
            onClick=${() => onDelete && onDelete(k)}
          >${IconTrash}</button>
        </div>
      </td>
    </tr>
    ${expanded
      ? html`<tr class="key-detail-row">
          <td class="key-detail-cell" colspan=${COLUMNS.length}>
            <div class="key-detail">
              <span class="detail-item"><span class="detail-label">Spend</span> ${formatCurrency(k.spend)}</span>
              <span class="detail-item"><span class="detail-label">TPM</span> ${formatInt(k.tpm_limit)}</span>
              <span class="detail-item"><span class="detail-label">RPM</span> ${formatInt(k.rpm_limit)}</span>
              <span class="detail-item"><span class="detail-label">Budget</span> ${EM_DASH}</span>
            </div>
          </td>
        </tr>`
      : null}
  `;
}

// ── KeysTable ────────────────────────────────────────────────────────────────────
// Props: { keys, freshKeys, status, onDelete }
//   keys      : array of projected /keys rows (no sk-).
//   freshKeys : object map id -> full sk- minted this session (parent-owned).
//   status    : "loading" | "ok" | "error".
//   onDelete  : (key) => void — invoked by the row revoke action (the parent
//               owns the confirm modal + the actual DELETE).
export function KeysTable({ keys, freshKeys, status, onDelete }) {
  const fresh = freshKeys || {};
  const rows = Array.isArray(keys) ? keys : [];

  // D-07 client-side pagination over the already-loaded rows. NO fetch — we slice
  // the loaded array. `page` is clamped so a delete that shrinks the list below
  // the current page boundary still renders.
  const [page, setPage] = useState(0);

  if (status === "loading") {
    return html`
      <div class="keys-table-container">
        <div class="keys-state"><div class="keys-state-body">Loading your keys…</div></div>
      </div>
    `;
  }

  if (status === "error") {
    return html`
      <div class="keys-table-container">
        <div class="keys-state">
          <div class="keys-state-error">Couldn't load your keys. Refresh the page to try again.</div>
        </div>
      </div>
    `;
  }

  if (rows.length === 0) {
    return html`
      <div class="keys-table-container">
        <div class="keys-state">
          <div class="keys-state-heading">No API Keys</div>
          <div class="keys-state-body">You have no virtual keys yet. Create one to get started.</div>
        </div>
      </div>
    `;
  }

  const total = rows.length;
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const startIdx = safePage * PAGE_SIZE;
  const pageRows = rows.slice(startIdx, startIdx + PAGE_SIZE);
  const showPager = total > PAGE_SIZE;

  return html`
    <div class="keys-table-container">
      <table class="keys-table">
        <thead>
          <tr>
            ${COLUMNS.map(
              (c) => html`<th class="col-header" data-col=${c.toLowerCase().replace(/\s+/g, "")}>${c}</th>`,
            )}
          </tr>
        </thead>
        <tbody>
          ${pageRows.map(
            (k) => html`<${KeyRow}
              key=${k.id}
              item=${k}
              fresh=${fresh[k.id]}
              onDelete=${onDelete}
            />`,
          )}
        </tbody>
      </table>
      <div class="keys-pager">
        <div class="keys-pager-caption">
          <span class="pager-label">Showing</span>
          <span class="pager-value">${pageRows.length}</span>
          <span class="pager-label">of</span>
          <span class="pager-value">${total}</span>
        </div>
        ${showPager
          ? html`<div class="keys-pager-controls">
              <button
                type="button"
                class="pager-btn"
                disabled=${safePage <= 0}
                onClick=${() => setPage((p) => Math.max(0, p - 1))}
              >Prev</button>
              <span class="pager-indicator">${safePage + 1} / ${pageCount}</span>
              <button
                type="button"
                class="pager-btn"
                disabled=${safePage >= pageCount - 1}
                onClick=${() => setPage((p) => Math.min(pageCount - 1, p + 1))}
              >Next</button>
            </div>`
          : null}
      </div>
    </div>
  `;
}

// ── Component stylesheet ──────────────────────────────────────────────────────────
// var(--*) tokens ONLY — never a raw hex (UI-SPEC §Color). Reuses base.css
// primitives (.panel shape, spacing tokens) and promotes the login.js .row-pill
// idiom for the status pills + the success.html .key-val chip treatment for the
// revealed fresh-key chip. Concatenated into app.js's injectShellStyles.
export const KEYS_TABLE_CSS = `
/* Table container — reuse the 16px .panel card shape (base.css), surface + 1px
 * border, lg interior padding. overflow-x:auto is a LAST-RESORT narrow-viewport
 * net only; at desktop width the 6-col table (D-04) fits without a scrollbar. */
.keys-table-container {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: var(--space-lg);
  overflow-x: auto;
}

.keys-table { width: 100%; border-collapse: collapse; }

/* Column headers — 11px caption role (mono, ALL-CAPS, --dim). */
.keys-table .col-header {
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 1.5px;
  color: var(--dim);
  text-align: left;
  padding: var(--space-sm) var(--space-md);
  border-bottom: 1px solid var(--border);
  white-space: nowrap;
}

/* Rows — 1px --border divider; sm vertical / md horizontal cell padding. */
.keys-table .key-row td {
  padding: var(--space-sm) var(--space-md);
  border-bottom: 1px solid var(--border);
  vertical-align: top;
}
/* The expandable detail row owns the bottom border so the pair reads as one. */
.keys-table .key-row:last-child td,
.keys-table .key-detail-row:last-child td { border-bottom: none; }

/* Data cells — 12px mono. */
.keys-table .cell-created,
.keys-table .cell-lastused,
.keys-table .cell-expires {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--text);
  white-space: nowrap;
}

/* D-04 merged Key-ID cell — chevron + a two-line stack: the alias name (14px
 * Body 600 --bright) on top, the key-id mono line (12px --dim) beneath. */
.keys-table .cell-keyid { white-space: nowrap; }
.keys-table .keyid-stack { display: flex; align-items: flex-start; gap: var(--space-sm); }
.keys-table .keyid-lines { min-width: 0; }
.keys-table .keyid-name {
  font-family: var(--sans);
  font-size: 14px;
  font-weight: 600;
  color: var(--bright);
  line-height: 1.3;
}
.keys-table .keyid-id { margin-top: 2px; }

/* Chevron expand control (D-05) — touch-safe ≥28px desktop hit target; click/
 * keyboard, NOT hover. Rotates 180deg when open. */
.keys-table .row-expand {
  flex: 0 0 auto;
  display: inline-flex; align-items: center; justify-content: center;
  width: 28px; height: 28px;
  background: transparent; border: 1px solid var(--border); border-radius: 6px;
  color: var(--dim); cursor: pointer;
  transition: color .15s, border-color .15s, transform .18s;
}
.keys-table .row-expand svg { width: 14px; height: 14px; stroke: currentColor; fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.keys-table .row-expand:hover { color: var(--text); border-color: var(--dim); }
.keys-table .row-expand.is-open { color: var(--accent); border-color: var(--accent); transform: rotate(180deg); }

/* Key-ID / masked chip — neutral mono by default; the revealed fresh chip uses
 * the success.html .key-val treatment (--accent text + --glow tint + border). */
.keys-table .key-chip {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--dim);
  word-break: break-all;
}
.keys-table .key-chip.is-revealed {
  color: var(--accent);
  background: var(--glow);
  border: 1px solid rgba(34,197,94,0.2);
  border-radius: 4px;
  padding: 2px 8px;
}

/* D-05 expandable usage detail — a strip below the row, short fade/height in. */
.keys-table .key-detail-cell { padding: 0 var(--space-md) var(--space-sm) !important; }
.keys-table .key-detail {
  display: flex; flex-wrap: wrap; gap: var(--space-lg);
  padding: var(--space-sm) var(--space-md);
  background: var(--bg); border: 1px solid var(--border); border-radius: 8px;
  animation: keyDetailIn .18s ease-out;
}
@keyframes keyDetailIn { from { opacity: 0; transform: translateY(-2px); } to { opacity: 1; transform: translateY(0); } }
.keys-table .detail-item {
  font-family: var(--mono); font-size: 12px; color: var(--text); white-space: nowrap;
}
.keys-table .detail-item .detail-label {
  font-size: 11px; text-transform: uppercase; letter-spacing: 1px;
  color: var(--dim); margin-right: var(--space-xs);
}

/* Status pills — promote the login.js .row-pill idiom. Active = --accent on a
 * --glow tint; Expired = --dim neutral on a --surface tint (NOT destructive);
 * Revoked = --destructive on a --glow-err tint (D-08 three states). */
.keys-table .status-pill {
  display: inline-block;
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 1px;
  border-radius: 999px;
  padding: var(--space-xs) var(--space-sm);
}
.keys-table .status-pill.is-active {
  color: var(--accent);
  background: var(--glow);
  border: 1px solid rgba(34,197,94,0.2);
}
.keys-table .status-pill.is-expired {
  color: var(--dim);
  background: var(--surface);
  border: 1px solid var(--border);
}
.keys-table .status-pill.is-revoked {
  color: var(--destructive);
  background: var(--glow-err);
  border: 1px solid rgba(239,68,68,0.2);
}

/* D-06 icon row actions — compact square icon buttons (eye/clipboard/trash);
 * ≥28px desktop hit target. The accessible name is the button aria-label/title. */
.keys-table .row-actions { display: flex; align-items: center; gap: var(--space-sm); }
.keys-table .row-action {
  display: inline-flex; align-items: center; justify-content: center;
  width: 28px; height: 28px;
  color: var(--dim);
  background: transparent;
  border: 1px solid rgba(74,81,115,0.5);
  border-radius: 6px;
  cursor: pointer;
  transition: background .15s, border-color .15s, color .15s;
}
.keys-table .row-action svg { width: 15px; height: 15px; stroke: currentColor; fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.keys-table .row-action:hover { color: var(--text); border-color: var(--dim); }
.keys-table .action-copy { color: var(--accent); }
.keys-table .action-copy.is-copied { color: var(--accent); border-color: var(--accent); background: var(--glow); }
.keys-table .action-reveal.is-on { color: var(--accent); border-color: var(--accent); }
.keys-table .action-delete { color: var(--destructive); border-color: rgba(239,68,68,0.4); }
.keys-table .action-delete:hover { color: var(--destructive2); border-color: var(--destructive); }

/* D-07 pagination row — caption always; Prev/Next only when rows > page size. */
.keys-table-container .keys-pager {
  display: flex; align-items: center; justify-content: space-between;
  gap: var(--space-md); flex-wrap: wrap;
  margin-top: var(--space-md); padding-top: var(--space-md);
  border-top: 1px solid var(--border);
}
.keys-pager .keys-pager-caption { display: flex; align-items: baseline; gap: var(--space-xs); }
.keys-pager .pager-label {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 1px; color: var(--dim);
}
.keys-pager .pager-value { font-family: var(--mono); font-size: 12px; color: var(--text); }
.keys-pager .keys-pager-controls { display: flex; align-items: center; gap: var(--space-sm); }
.keys-pager .pager-indicator { font-family: var(--mono); font-size: 12px; color: var(--dim); }
.keys-pager .pager-btn {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: lowercase; letter-spacing: .5px; color: var(--dim);
  background: transparent; border: 1px solid var(--border); border-radius: 6px;
  padding: var(--space-xs) var(--space-md); cursor: pointer;
  transition: border-color .15s, color .15s;
}
.keys-pager .pager-btn:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
.keys-pager .pager-btn:disabled { opacity: .4; cursor: not-allowed; }

/* Empty / loading / error states — centered inside the container. */
.keys-state { text-align: center; padding: var(--space-3xl) var(--space-lg); }
.keys-state-heading { font-family: var(--sans); font-size: 24px; font-weight: 600; color: var(--bright); line-height: 1.3; }
.keys-state-body { font-family: var(--sans); font-size: 14px; color: var(--dim); margin-top: var(--space-sm); }
.keys-state-error { font-family: var(--sans); font-size: 14px; color: var(--destructive); }

/* Responsive collapse (< 1024px): drop Last used, then Expires, then Created.
 * Key ID / Status / Actions stay visible (UI-SPEC §C2). */
@media (max-width: 1023px) {
  .keys-table .col-header[data-col="lastused"],
  .keys-table .cell-lastused { display: none; }
}
@media (max-width: 880px) {
  .keys-table .col-header[data-col="expires"],
  .keys-table .cell-expires { display: none; }
}
@media (max-width: 760px) {
  .keys-table .col-header[data-col="created"],
  .keys-table .cell-created { display: none; }
  .keys-table .row-action,
  .keys-table .row-expand { width: 44px; height: 44px; }
}
`;
