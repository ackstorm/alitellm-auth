// dashboard.js — the Wave-3 dashboard CONTAINER for the alitellm-auth SPA
// (DASH-01 + the numeric half of DASH-06). Preact + htm tagged templates, no
// JSX, no TypeScript (inherited 09-CONTEXT D-04).
//
// This is the integration owner. It renders the top row (DASH-01: greeting +
// endpoint chip), the four-tile metric header + account budget bar (DASH-06),
// the `API KEYS` section with the `+ New Key` CTA, and it MOUNTS the Wave-2
// presentational leaves (KeysTable, CreateKeyModal, DeleteModal). It owns the
// data + open-state those leaves need:
//   • keys / keysStatus — fetched from GET /api/session/keys on mount and re-
//     fetched after a create/delete (the App.loadSession fetch-then-branch shape).
//   • freshKeys — the id -> full `sk-` map of keys minted THIS browser session.
//   • createOpen / keyToDelete — the modal open-state.
//
// SECURITY INVARIANTS (threat register 10-05):
//   • T-10-14 (XSS): me.name / me.endpoint / me.team_id render as Preact text
//     children via htm (auto-escaped). No dangerouslySetInnerHTML, no raw-HTML
//     interpolation anywhere.
//   • T-10-15 (info disclosure, fresh keys): the full `sk-` lives ONLY in the
//     in-memory `freshKeys` state below. It is never written to any web Storage
//     API and never logged. It is lost on refresh (D-01).
//   • T-10-16 (info disclosure, endpoint Copy): the Copy button writes only
//     me.endpoint (a public base URL), on an explicit user click, via clipboard.js.
import { h } from "preact";
import { useState, useEffect, useCallback } from "preact/hooks";
import htm from "htm";
import { getJson } from "./api.js";
import { useCopyFeedback } from "./clipboard.js";
import { formatCurrency, formatInt } from "./format.js";
import { KeysTable } from "./keys-table.js";
import { CreateKeyModal } from "./create-key.js";
import { DeleteModal } from "./delete-modal.js";

const html = htm.bind(h);

// The em-dash placeholder (matches format.js EM_DASH) — `Monthly requests` is
// ALWAYS the em-dash this phase (no time-series fetch — UI-SPEC §2).
const EM_DASH = "—";

// A key is "Active" unless an explicit revoked/blocked flag is truthy — mirrors
// keys-table.js isRevoked (absence == active, UI-SPEC §4).
function isRevoked(key) {
  return Boolean(key && (key.revoked || key.blocked));
}

// ── EndpointChip ──────────────────────────────────────────────────────────────
// The DASH-01 RIGHT block: `endpoint` caption + the API base URL (12px mono
// --bright) + a Copy button. Copy writes ONLY me.endpoint (a public URL) on an
// explicit click; `copied!` shows for 2s (clipboard.js useCopyFeedback).
function EndpointChip({ endpoint }) {
  const { copied, copy } = useCopyFeedback();
  return html`
    <div class="endpoint-chip">
      <div class="endpoint-label">endpoint</div>
      <div class="endpoint-value">${endpoint || EM_DASH}</div>
      <button
        type="button"
        class="endpoint-copy"
        onClick=${() => endpoint && copy(endpoint)}
      >${copied ? "copied!" : "Copy"}</button>
    </div>
  `;
}

// ── MetricTile ───────────────────────────────────────────────────────────────
// One of the four numeric/text tiles (DASH-06): 11px caption label + 24px
// heading value. Value-only, no sparkline, no chart (D-03/D-06).
function MetricTile({ label, value }) {
  return html`
    <div class="metric-tile">
      <div class="metric-label">${label}</div>
      <div class="metric-value">${value}</div>
    </div>
  `;
}

// ── BudgetBar ────────────────────────────────────────────────────────────────
// The account budget bar (DASH-06 / UI-SPEC §3). If limits.max_budget is present
// it renders an 8px track with an --accent fill = spend/max_budget (the overflow
// segment uses --destructive when spend > max_budget). Otherwise it HIDES the bar
// and shows the spent-no-budget copy — never a divide-by-zero.
function BudgetBar({ limits, spend }) {
  const current = (spend && typeof spend.current === "number") ? spend.current : 0;
  const maxBudget = limits && typeof limits.max_budget === "number" ? limits.max_budget : null;

  // No budget set (limits null OR max_budget null): no bar, just the spent copy.
  if (maxBudget === null) {
    return html`
      <div class="budget-bar budget-bar--none">
        <div class="budget-none">${formatCurrency(current)} spent · no account budget set</div>
      </div>
    `;
  }

  // Budget present. Render a SINGLE fill clamped to [0, 100]% of the track and
  // color-switch it to --destructive once spend exceeds the budget. Summing two
  // unshrunk flex children misrepresented the magnitude (a 2x overspend read as a
  // 50/50 split — WR-01); the fill width is the spend ratio and the over-budget
  // state is signalled by color, with the figure text carrying the exact amount.
  const ratio = maxBudget > 0 ? current / maxBudget : 1;
  const fillPct = Math.max(0, Math.min(1, ratio)) * 100;
  const over = ratio > 1;

  return html`
    <div class="budget-bar">
      <div class="budget-head">
        <span class="budget-label">Account budget</span>
        <span class="budget-figure">${formatCurrency(current)} of ${formatCurrency(maxBudget)}</span>
      </div>
      <div class="budget-track">
        <div
          class="budget-fill ${over ? "budget-fill--over" : ""}"
          style=${`width:${fillPct}%`}
        ></div>
      </div>
    </div>
  `;
}

// ── Dashboard ────────────────────────────────────────────────────────────────
// Props: { me, registerCreateOpener }
//   me                  — the /api/session/me payload (identity + endpoint +
//                         limits + spend), already fetched by App.
//   registerCreateOpener — optional (opener) => void. The shell calls this once
//                         so the sidebar `Create key` can open the SAME modal as
//                         the main `+ New Key` CTA (wired in app.js, Task 2).
export function Dashboard({ me, registerCreateOpener }) {
  const identity = me || {};

  // /keys data + load status. keysStatus mirrors App.loadSession: "loading"
  // until the first /keys response resolves, then "ok" | "error".
  const [keys, setKeys] = useState([]);
  const [keysStatus, setKeysStatus] = useState("loading");

  // freshKeys: id -> full `sk-` minted this session. IN-MEMORY ONLY — never
  // persisted to any web Storage, never logged, lost on refresh (D-01 / T-10-15).
  const [freshKeys, setFreshKeys] = useState({});

  // Modal open-state owned here so both the main CTA and the sidebar shortcut
  // open the same create modal, and any row delete opens the same confirm modal.
  const [createOpen, setCreateOpen] = useState(false);
  const [keyToDelete, setKeyToDelete] = useState(null);

  // Load /keys (loading -> branch on status, App.loadSession shape). Re-runs
  // after a create or delete to reconcile the table with the server.
  const loadKeys = useCallback(async () => {
    setKeysStatus("loading");
    const { status, data } = await getJson("/api/session/keys");
    if (status === 200 && data && Array.isArray(data.keys)) {
      setKeys(data.keys);
      setKeysStatus("ok");
      return;
    }
    setKeysStatus("error");
  }, []);

  useEffect(() => {
    loadKeys();
  }, [loadKeys]);

  // Expose the create-modal opener up to the shell (Task 2 threads it into the
  // sidebar). Done in an effect so render stays a pure function of state.
  const openCreate = useCallback(() => setCreateOpen(true), []);
  useEffect(() => {
    if (registerCreateOpener) registerCreateOpener(openCreate);
  }, [registerCreateOpener, openCreate]);

  // Create success: record the fresh full `sk-` in memory (D-01), close the
  // modal, and re-fetch /keys so the new row reconciles from the server.
  const onCreated = useCallback(({ id, key }) => {
    if (id) setFreshKeys((prev) => ({ ...prev, [id]: key }));
    setCreateOpen(false);
    loadKeys();
  }, [loadKeys]);

  // Delete success: clear the target and re-fetch /keys.
  const onDeleted = useCallback(() => {
    setKeyToDelete(null);
    loadKeys();
  }, [loadKeys]);

  const openDeleteModal = useCallback((key) => setKeyToDelete(key), []);

  // ── Metric tile values (DASH-06 numeric) ───────────────────────────────────
  // Active keys = non-revoked row count from /keys (— while loading/error so we
  // never show a misleading 0). Monthly requests = em-dash ALWAYS (no fetch).
  // Spend MTD = formatCurrency(me.spend.current). Team = me.team_id.
  const activeKeys =
    keysStatus === "ok"
      ? formatInt(keys.filter((k) => !isRevoked(k)).length)
      : EM_DASH;
  const spendValue =
    identity.spend && typeof identity.spend.current === "number"
      ? formatCurrency(identity.spend.current)
      : EM_DASH;
  const teamValue = identity.team_id || EM_DASH;

  return html`
    <div class="dashboard">
      <div class="dash-top">
        <div class="greeting">
          Welcome back, <span class="greeting-name">${identity.name || EM_DASH}</span>
        </div>
        <${EndpointChip} endpoint=${identity.endpoint} />
      </div>

      <div class="metric-tiles">
        <${MetricTile} label="Active keys" value=${activeKeys} />
        <${MetricTile} label="Monthly requests" value=${EM_DASH} />
        <${MetricTile} label="Spend MTD" value=${spendValue} />
        <${MetricTile} label="Team" value=${teamValue} />
      </div>

      <${BudgetBar} limits=${identity.limits} spend=${identity.spend} />

      <div class="keys-section">
        <div class="keys-section-head">
          <div class="keys-section-text">
            <div class="section-label">API KEYS</div>
            <div class="keys-section-sub">Create and manage your LiteLLM virtual keys.</div>
          </div>
          <button type="button" class="btn keys-new" onClick=${openCreate}>+ New Key</button>
        </div>
        <${KeysTable}
          keys=${keys}
          freshKeys=${freshKeys}
          status=${keysStatus}
          onDelete=${openDeleteModal}
        />
      </div>

      <${CreateKeyModal}
        open=${createOpen}
        onClose=${() => setCreateOpen(false)}
        onCreated=${onCreated}
      />
      <${DeleteModal}
        keyToDelete=${keyToDelete}
        onClose=${() => setKeyToDelete(null)}
        onDeleted=${onDeleted}
      />
    </div>
  `;
}

// ── Component stylesheet — var(--*) tokens only ───────────────────────────────
// Reuses base.css primitives (.panel surface shape, spacing tokens, .section-label
// caption) and app.js's .btn accent CTA. Only the dashboard-detail styles
// (greeting, endpoint chip, metric tiles, budget bar, keys-section head) are new.
// Concatenated into app.js's injectShellStyles. NEVER a raw hex — var(--*) only.
export const DASHBOARD_CSS = `
.dashboard { display: flex; flex-direction: column; gap: var(--space-3xl); animation: slideUp .5s ease-out; }

/* ── DASH-01: greeting + endpoint chip top row ─────────────────────────────── */
.dash-top {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: var(--space-xl); flex-wrap: wrap;
}
.greeting { font-family: var(--sans); font-size: 24px; font-weight: 600; color: var(--bright); line-height: 1.3; }
.greeting .greeting-name { color: var(--accent2); }

.endpoint-chip {
  display: flex; align-items: center; gap: var(--space-md);
  background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
  padding: var(--space-sm) var(--space-lg);
}
.endpoint-chip .endpoint-label {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 1px; color: var(--dim);
}
.endpoint-chip .endpoint-value { font-family: var(--mono); font-size: 12px; color: var(--bright); word-break: break-all; }
.endpoint-chip .endpoint-copy {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: lowercase; letter-spacing: .5px; color: var(--dim);
  background: transparent; border: 1px solid var(--border); border-radius: 8px;
  padding: var(--space-xs) var(--space-md); cursor: pointer;
  transition: border-color .15s, color .15s;
}
.endpoint-chip .endpoint-copy:hover { border-color: var(--accent); color: var(--accent); }

/* ── DASH-06: four-tile metric header ──────────────────────────────────────── */
.metric-tiles { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--space-md); }
.metric-tile {
  background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
  padding: var(--space-lg); display: flex; flex-direction: column; gap: var(--space-sm);
}
.metric-tile .metric-label {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 1px; color: var(--dim);
}
.metric-tile .metric-value {
  font-family: var(--sans); font-size: 24px; font-weight: 600; color: var(--bright);
  line-height: 1.3; word-break: break-word;
}

/* ── DASH-06: account budget bar ───────────────────────────────────────────── */
.budget-bar {
  background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
  padding: var(--space-lg); display: flex; flex-direction: column; gap: var(--space-sm);
}
.budget-bar .budget-head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--space-md); }
.budget-bar .budget-label {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 1px; color: var(--dim);
}
.budget-bar .budget-figure { font-family: var(--mono); font-size: 12px; color: var(--text); }
.budget-bar .budget-track {
  display: flex; height: 8px; border-radius: 999px; overflow: hidden;
  background: var(--bg); border: 1px solid var(--border);
}
.budget-bar .budget-fill { height: 100%; background: var(--accent); flex-shrink: 0; transition: width .25s; }
.budget-bar .budget-fill--over { background: var(--destructive); }
.budget-bar .budget-none { font-family: var(--sans); font-size: 14px; color: var(--dim); }

/* ── DASH-02 keys section head ─────────────────────────────────────────────── */
.keys-section { display: flex; flex-direction: column; gap: var(--space-lg); }
.keys-section-head {
  display: flex; align-items: flex-end; justify-content: space-between;
  gap: var(--space-lg); flex-wrap: wrap;
}
.keys-section-head .keys-section-sub { font-family: var(--sans); font-size: 14px; color: var(--dim); margin-top: var(--space-xs); }
.keys-section-head .keys-new { text-transform: none; }

/* Responsive: tiles stack 2-up then 1-up below the shell breakpoints. */
@media (max-width: 880px) {
  .metric-tiles { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 520px) {
  .metric-tiles { grid-template-columns: 1fr; }
}
`;
