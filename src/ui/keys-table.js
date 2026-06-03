// keys-table.js — the keys-as-DATA-TABLE surface for the alitellm-auth
// dashboard (DASH-02 / DASH-06). Preact + htm tagged templates, no JSX, no
// TypeScript (inherited 09-CONTEXT D-04).
//
// This is a PRESENTATIONAL LEAF: it receives the projected `/keys` rows and a
// load `status`, and renders. It performs NO fetch and owns NO data — the
// Wave 3 dashboard container fetches `/keys`. This module renders the locked
// 7-column table, the Active/Revoked status pills, the per-key numeric usage,
// the empty state and the load-error state. (The D-01 reveal/copy split + the
// delete row action are layered on in Task 2.)
//
// SECURITY INVARIANTS (threat register 10-03):
//   • T-10-06 (XSS): every cell value (key_alias, id, models) renders as a Preact
//     text child via htm — htm/Preact auto-escapes. No raw-HTML inner-HTML sink
//     and no raw-HTML interpolation are used anywhere.
import { h } from "preact";
import htm from "htm";
import { formatCurrency, formatInt, formatDate, maskKey } from "./format.js";

const html = htm.bind(h);

// The em-dash placeholder (matches format.js EM_DASH) for the always-empty
// "Last used" cell and the per-key budget cell (D-17 — inherited from account).
const EM_DASH = "—";

// The locked column set (UI-SPEC §4 / §Copywriting Contract). Order is fixed.
const COLUMNS = [
  "Name", "Key ID", "Created", "Last used", "Expires", "Status", "Actions",
];

// A key is "Active" unless an explicit revoked/blocked flag is truthy. The
// projected /keys shape carries no positive "active" field, so absence == active
// (UI-SPEC §4 "Active … when not revoked").
function isRevoked(key) {
  return Boolean(key && (key.revoked || key.blocked));
}

// ── KeyRow ─────────────────────────────────────────────────────────────────────
// One table row: the locked 7 columns + per-key numeric usage. The Key ID cell
// shows the masked sk-…last4 derived from the id.
function KeyRow({ item: k }) {
  const revoked = isRevoked(k);
  const id = k.id;
  const name = k.key_alias || maskKey(id);

  return html`
    <tr class="key-row" data-revoked=${revoked}>
      <td class="cell-name" data-col="name">${name}</td>
      <td class="cell-id" data-col="id">
        <span class="key-chip">${maskKey(id)}</span>
      </td>
      <td class="cell-created" data-col="created">${formatDate(k.created_at)}</td>
      <td class="cell-lastused" data-col="lastused">${EM_DASH}</td>
      <td class="cell-expires" data-col="expires">${k.expires == null ? "Never" : formatDate(k.expires)}</td>
      <td class="cell-status" data-col="status">
        <span class="status-pill ${revoked ? "is-revoked" : "is-active"}">${revoked ? "Revoked" : "Active"}</span>
      </td>
      <td class="cell-actions" data-col="actions">
        <div class="usage-line">
          <span class="usage-item"><span class="usage-label">spend</span> ${formatCurrency(k.spend)}</span>
          <span class="usage-item"><span class="usage-label">tpm</span> ${formatInt(k.tpm_limit)}</span>
          <span class="usage-item"><span class="usage-label">rpm</span> ${formatInt(k.rpm_limit)}</span>
          <span class="usage-item"><span class="usage-label">budget</span> ${EM_DASH}</span>
        </div>
      </td>
    </tr>
  `;
}

// ── KeysTable ────────────────────────────────────────────────────────────────────
// Props: { keys, status }
//   keys   : array of projected /keys rows (no sk-).
//   status : "loading" | "ok" | "error".
export function KeysTable({ keys, status }) {
  const rows = Array.isArray(keys) ? keys : [];

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
          ${rows.map(
            (k) => html`<${KeyRow} key=${k.id} item=${k} />`,
          )}
        </tbody>
      </table>
    </div>
  `;
}

// ── Component stylesheet ──────────────────────────────────────────────────────────
// var(--*) tokens ONLY — never a raw hex (UI-SPEC §Color). Reuses base.css
// primitives (.panel shape, spacing tokens) and promotes the login.js .row-pill
// idiom for the status pills. Concatenated into app.js's injectShellStyles.
export const KEYS_TABLE_CSS = `
/* Table container — reuse the 16px .panel card shape (base.css), surface + 1px
 * border, lg interior padding. */
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
.keys-table .key-row:last-child td { border-bottom: none; }

/* Data cells — 12px mono. */
.keys-table .cell-name,
.keys-table .cell-id,
.keys-table .cell-created,
.keys-table .cell-lastused,
.keys-table .cell-expires {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--text);
  white-space: nowrap;
}
.keys-table .cell-name { color: var(--bright); }

/* Key-ID / masked chip — neutral mono. */
.keys-table .key-chip {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--text);
  word-break: break-all;
}

/* Status pills — promote the login.js .row-pill idiom. Active = --accent on a
 * --glow tint; Revoked = --destructive on a --glow-err tint. */
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
.keys-table .status-pill.is-revoked {
  color: var(--destructive);
  background: var(--glow-err);
  border: 1px solid rgba(239,68,68,0.2);
}

/* Per-key numeric usage (DASH-06) — compact mono labels in the Actions cell. */
.keys-table .usage-line {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-sm);
  margin-bottom: var(--space-sm);
}
.keys-table .usage-item {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--text);
  white-space: nowrap;
}
.keys-table .usage-item .usage-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: var(--dim);
  margin-right: var(--space-xs);
}

/* Empty / loading / error states — centered inside the container. */
.keys-state { text-align: center; padding: var(--space-3xl) var(--space-lg); }
.keys-state-heading { font-family: var(--sans); font-size: 24px; font-weight: 600; color: var(--bright); line-height: 1.3; }
.keys-state-body { font-family: var(--sans); font-size: 14px; color: var(--dim); margin-top: var(--space-sm); }
.keys-state-error { font-family: var(--sans); font-size: 14px; color: var(--destructive); }

/* Responsive collapse (< 1024px): drop Last used, then Expires, then Created.
 * Name / Key ID / Status / Actions stay visible (UI-SPEC §4). */
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
}
`;
