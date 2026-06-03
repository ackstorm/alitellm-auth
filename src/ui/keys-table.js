// keys-table.js — the keys-as-DATA-TABLE surface for the alitellm-auth
// dashboard (DASH-02 / DASH-03 / DASH-06). Preact + htm tagged templates, no
// JSX, no TypeScript (inherited 09-CONTEXT D-04).
//
// This is a PRESENTATIONAL LEAF: it receives the projected `/keys` rows, a
// `freshKeys` map (id -> full sk- held only in parent memory this session), a
// load `status`, and an `onDelete(key)` callback. It performs NO fetch and owns
// NO data — the Wave 3 dashboard container fetches `/keys`, holds the fresh-key
// map, and wires the actual DELETE + confirm modal. This module only renders the
// locked 7-column table, the Active/Revoked status pills, per-key numeric usage,
// the row actions (copy / reveal-for-fresh-only / delete), the empty state and
// the load-error state.
//
// SECURITY INVARIANTS (threat register 10-03):
//   • T-10-06 (XSS): every cell value (key_alias, id, models) renders as a Preact
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
// One table row. `fresh` is the full sk- for this row when it was minted this
// session (else undefined). Reveal/copy reconcile to D-01: fresh keys get a
// reveal toggle + full-value copy; pre-existing keys get key_id copy + a masked
// sk-…last4 display and NO reveal button.
function KeyRow({ item: k, fresh, onDelete }) {
  const [revealed, setRevealed] = useState(false);
  const { copied, copy } = useCopyFeedback();

  const revoked = isRevoked(k);
  const id = k.id;
  const name = k.key_alias || maskKey(id);

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
      <td class="cell-name" data-col="name">${name}</td>
      <td class="cell-id" data-col="id">
        <span class="key-chip ${fresh !== undefined && revealed ? "is-revealed" : ""}">${chipDisplay}</span>
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
        <div class="row-actions">
          <button
            type="button"
            class="row-action action-copy"
            onClick=${() => copy(copyValue)}
          >${copied ? "copied!" : "copy"}</button>
          ${fresh !== undefined
            ? html`<button
                type="button"
                class="row-action action-reveal ${revealed ? "is-on" : ""}"
                onClick=${() => setRevealed((v) => !v)}
              >reveal</button>`
            : null}
          <button
            type="button"
            class="row-action action-delete"
            onClick=${() => onDelete && onDelete(k)}
          >delete</button>
        </div>
      </td>
    </tr>
  `;
}

// ── KeysTable ────────────────────────────────────────────────────────────────────
// Props: { keys, freshKeys, status, onDelete }
//   keys      : array of projected /keys rows (no sk-).
//   freshKeys : object map id -> full sk- minted this session (parent-owned).
//   status    : "loading" | "ok" | "error".
//   onDelete  : (key) => void — invoked by the row `delete` action (the parent
//               owns the confirm modal + the actual DELETE).
export function KeysTable({ keys, freshKeys, status, onDelete }) {
  const fresh = freshKeys || {};
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
            (k) => html`<${KeyRow}
              key=${k.id}
              item=${k}
              fresh=${fresh[k.id]}
              onDelete=${onDelete}
            />`,
          )}
        </tbody>
      </table>
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

/* Key-ID / masked chip — neutral mono by default; the revealed fresh chip uses
 * the success.html .key-val treatment (--accent text + --glow tint + border). */
.keys-table .key-chip {
  font-family: var(--mono);
  font-size: 12px;
  color: var(--text);
  word-break: break-all;
}
.keys-table .key-chip.is-revealed {
  color: var(--accent);
  background: var(--glow);
  border: 1px solid rgba(34,197,94,0.2);
  border-radius: 4px;
  padding: 2px 8px;
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

/* Per-key numeric usage (DASH-06) — compact mono labels above the row actions. */
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

/* Row actions — 11px lowercase mono captions; min 44px touch target on mobile. */
.keys-table .row-actions { display: flex; align-items: center; gap: var(--space-sm); }
.keys-table .row-action {
  font-family: var(--mono);
  font-size: 11px;
  font-weight: 600;
  text-transform: lowercase;
  letter-spacing: .5px;
  color: var(--dim);
  background: transparent;
  border: 1px solid rgba(74,81,115,0.5);
  border-radius: 3px;
  padding: var(--space-xs) var(--space-sm);
  cursor: pointer;
  transition: background .15s, border-color .15s, color .15s;
}
.keys-table .row-action:hover { color: var(--text); border-color: var(--dim); }
.keys-table .action-copy { color: var(--accent); }
.keys-table .action-reveal.is-on { color: var(--accent); border-color: var(--accent); }
.keys-table .action-delete { color: var(--destructive); border-color: rgba(239,68,68,0.4); }
.keys-table .action-delete:hover { color: var(--destructive2); border-color: var(--destructive); }

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
  .keys-table .row-action { min-height: 44px; }
}
`;
