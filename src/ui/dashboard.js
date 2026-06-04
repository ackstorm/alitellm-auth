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
import { useState, useEffect, useCallback, useRef } from "preact/hooks";
import htm from "htm";
import { getJson } from "./api.js";
import { useCopyFeedback } from "./clipboard.js";
import { formatCurrency, formatInt, abbreviate } from "./format.js";
import { KeysTable } from "./keys-table.js";
import { CreateKeyModal } from "./create-key.js";
import { DeleteModal } from "./delete-modal.js";

const html = htm.bind(h);

// The em-dash placeholder (matches format.js EM_DASH). `Monthly requests` and
// `Spend MTD` degrade to it when the additive /api/session/stats fetch (D-09)
// fails or returns a null figure (UI-SPEC §C1 degrade rule).
const EM_DASH = "—";

// ── KPI tile icons (D-10) — reuse the login.js `.vp-icon` --accent SVG idiom ───
// 24x24 viewBox stroke glyphs sized + colored by `.metric-icon` CSS.
const IconKey = html`<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="7.5" cy="15.5" r="4.5"/><path d="m10.5 12.5 8-8"/><path d="m16 6 3 3"/><path d="m19 3 2 2"/></svg>`;
const IconChart = html`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 3v18h18"/><rect x="7" y="12" width="3" height="5"/><rect x="12" y="8" width="3" height="9"/><rect x="17" y="5" width="3" height="12"/></svg>`;
const IconDollar = html`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 1v22"/><path d="M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6"/></svg>`;
const IconPeople = html`<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>`;

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
// One of the four numeric/text tiles (DASH-06): an optional per-tile accent icon
// (D-10) + 11px caption label + 24px heading value. Value-only, no sparkline, no
// chart (D-03/D-06).
function MetricTile({ label, value, icon }) {
  return html`
    <div class="metric-tile">
      <div class="metric-head">
        ${icon ? html`<span class="metric-icon">${icon}</span>` : null}
        <div class="metric-label">${label}</div>
      </div>
      <div class="metric-value">${value}</div>
    </div>
  `;
}

// ── BudgetBar ────────────────────────────────────────────────────────────────
// The account budget bar (DASH-06 / UI-SPEC §C6). If limits.max_budget is present
// (and > 0) it renders an 8px track with an --accent fill = spend/max_budget (the
// overflow state color-switches to --destructive when spend > max_budget).
// Otherwise (max_budget null OR <= 0 — the FID-03 defect case) it renders a
// NEUTRAL EMPTY 0% track with "no budget set" copy — never a full-green bar and
// never a divide-by-zero.
function BudgetBar({ limits, spend }) {
  const current = (spend && typeof spend.current === "number") ? spend.current : 0;
  const maxBudget = limits && typeof limits.max_budget === "number" ? limits.max_budget : null;

  // No budget set: treat null AND <= 0 identically (D-11 / FID-03 fix). The old
  // code only guarded `=== null`, so `max_budget: 0` fell through to the
  // has-budget branch where `ratio = maxBudget > 0 ? current/maxBudget : 1`
  // forced ratio=1 → a full-green 100% bar. Render an EMPTY neutral track
  // (0% fill, --border/--bg, NOT --accent) instead — an empty bar, NOT a hidden
  // bar and NOT a full-green bar.
  if (maxBudget === null || maxBudget <= 0) {
    return html`
      <div class="budget-bar budget-bar--none">
        <div class="budget-head">
          <span class="budget-label">Account budget</span>
          <span class="budget-figure">${formatCurrency(current)} · no budget set</span>
        </div>
        <div class="budget-track">
          <div class="budget-fill budget-fill--empty" style="width:0%"></div>
        </div>
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

  // Monotonic sequence token so only the LATEST loadKeys may write state. A
  // rapid create-then-delete fires two overlapping loadKeys awaits; without
  // sequencing an earlier fetch could resolve last and clobber `keys` with
  // stale data (WR-05). Each call captures its seq and bails on resolve if a
  // newer call has since started.
  const loadSeq = useRef(0);

  // Load /keys (loading -> branch on status, App.loadSession shape). Re-runs
  // after a create or delete to reconcile the table with the server.
  const loadKeys = useCallback(async () => {
    const seq = ++loadSeq.current;
    // Keep the populated table during a background re-fetch (post-create/delete
    // reconcile): only collapse to the loading placeholder when there is no
    // prior data (initial load). Avoids a visible flash on every mutation while
    // the monotonic loadSeq guard still prevents a stale write (WR-01/WR-05).
    setKeysStatus((s) => (s === "ok" ? s : "loading"));
    const { status, data } = await getJson("/api/session/keys");
    // A newer load started while this one was in flight — discard this result.
    if (seq !== loadSeq.current) return;
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

  // ── D-09: additive KPI stats fetch (Monthly requests / Spend MTD) ───────────
  // A SEPARATE state + effect from loadKeys — the stats fetch MUST NOT block or
  // couple to the keys render (UI-SPEC §C1 / Interaction Contracts). It hits the
  // Phase-12 /api/session/stats endpoint over a ~30d UTC window and degrades to
  // EM_DASH on any failure/null. A stats failure never surfaces a whole-dashboard
  // error — `statsTotals` simply stays null and the two tiles read the em-dash.
  const [statsTotals, setStatsTotals] = useState(null);
  useEffect(() => {
    let live = true;
    (async () => {
      const end = new Date();
      const start = new Date(end.getTime() - 30 * 24 * 60 * 60 * 1000);
      const iso = (d) => d.toISOString().slice(0, 10); // YYYY-MM-DD (UTC)
      const url = `/api/session/stats?start_date=${iso(start)}&end_date=${iso(end)}`;
      const { status, data } = await getJson(url);
      if (!live) return;
      if (status === 200 && data && data.totals) {
        setStatsTotals(data.totals);
      }
      // On any non-200 / missing-totals: leave statsTotals null → tiles em-dash.
    })();
    return () => { live = false; };
  }, []);

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

  // Delete success: clear the target, DROP the deleted id's fresh `sk-` from the
  // in-memory map (so a deleted key's secret-bearing state does not linger past
  // the row's lifetime — WR-05), and re-fetch /keys. DeleteModal passes
  // onDeleted(keyToDelete.id); the id was previously dropped (IN-01) which
  // blocked this pruning.
  const onDeleted = useCallback((id) => {
    setKeyToDelete(null);
    if (id) {
      setFreshKeys((prev) => {
        if (!(id in prev)) return prev;
        const next = { ...prev };
        delete next[id];
        return next;
      });
    }
    loadKeys();
  }, [loadKeys]);

  const openDeleteModal = useCallback((key) => setKeyToDelete(key), []);

  // ── Metric tile values (DASH-06 numeric) ───────────────────────────────────
  // Active keys = non-revoked row count from /keys (— while loading/error so we
  // never show a misleading 0). Monthly requests / Spend MTD = the additive
  // /api/session/stats totals (D-09), degrading to em-dash on failure/null.
  // Team = me.team_id.
  const activeKeys =
    keysStatus === "ok"
      ? formatInt(keys.filter((k) => !isRevoked(k)).length)
      : EM_DASH;
  const requestsValue =
    statsTotals && typeof statsTotals.requests === "number"
      ? abbreviate(statsTotals.requests)
      : EM_DASH;
  // Spend MTD prefers the stats-window total; falls back to me.spend.current so
  // the tile still renders a figure before/without the stats fetch resolving.
  const spendValue =
    statsTotals && typeof statsTotals.spend === "number"
      ? formatCurrency(statsTotals.spend)
      : identity.spend && typeof identity.spend.current === "number"
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
        <${MetricTile} label="Active keys" value=${activeKeys} icon=${IconKey} />
        <${MetricTile} label="Monthly requests" value=${requestsValue} icon=${IconChart} />
        <${MetricTile} label="Spend MTD" value=${spendValue} icon=${IconDollar} />
        <${MetricTile} label="Team" value=${teamValue} icon=${IconPeople} />
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
.metric-tile .metric-head { display: flex; align-items: center; gap: var(--space-sm); }
.metric-tile .metric-icon {
  flex: 0 0 auto; width: 26px; height: 26px; border-radius: 8px;
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--glow); border: 1px solid var(--border);
}
.metric-tile .metric-icon svg { width: 15px; height: 15px; stroke: var(--accent); fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
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
/* D-11 no-budget state — an EMPTY neutral track (0% fill on the --bg track),
 * NOT a hidden bar and NOT a full-green bar. */
.budget-bar .budget-fill--empty { background: var(--border); }
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
