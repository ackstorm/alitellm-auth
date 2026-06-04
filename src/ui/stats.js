// stats.js — the Wave-3 CONTAINER for the #/stats Usage & Spend page
// (STATS-02..11). Preact + htm tagged templates, no JSX, no TypeScript
// (inherited 13-CONTEXT D-04 / 09-CONTEXT D-04).
//
// This is the integration owner. It MIRRORS the dashboard.js fetch-on-mount +
// status-state container (dashboard.js:127-266) with the REQUIRED `loadSeq` ref
// guard (dashboard.js:149-169): a date-preset re-query fires while a prior fetch
// is still in flight (the same overlapping-await hazard WR-05 fixed), so only the
// LATEST load may write state.
//
// It owns the date/compare state, drives the re-query against
// GET /api/session/stats (Phase 12), distributes the contract slices + per-figure
// render modes (capabilityRenderMode, stats-presets.js) to the Wave-2 leaves, and
// implements the tiered error/skeleton/empty handling (UI-SPEC §10 / CONTEXT
// D-14/D-15/D-16) plus the no-op "coming soon" toast for every mock extra
// (CONTEXT D-13 / STATS-11).
//
// SECURITY INVARIANTS (threat register 13-05):
//   • T-13-12 (XSS): EVERY dynamic contract value (model, key_alias, budget
//     labels, totals) renders as an htm text child (auto-escaped) inside the
//     leaves. This container builds NO innerHTML from contract strings and uses
//     no raw-HTML injection sink — the page's primary attack surface stays closed.
//   • T-13-13 (info disclosure): the ONLY network call is a read-only
//     stats fetch over the existing OIDC session cookie; the browser never sends
//     or receives the master key or `sk-`.
//   • T-13-14 (CSRF / spoofing): every mock extra (Insights, the rail's disabled
//     glyphs) is a no-op — it calls the toast `show` ONLY. NO network, NO state
//     change. stats.js issues EXACTLY one getJson (asserted by the plan).
//   • T-13-15 (DoS): the loadSeq ref guard discards stale resolves so a rapid
//     preset toggle cannot clobber state with an out-of-order response.
import { h } from "preact";
import { useState, useEffect, useCallback, useRef } from "preact/hooks";
import htm from "htm";
import { getJson } from "./api.js";
import { presetToRange, capabilityRenderMode } from "./stats-presets.js";
import { Skeleton } from "./skeleton.js";
import { useToast, Toast } from "./toast.js";
import { SpendChart, RequestsChart } from "./charts.js";
import { KpiRow } from "./stats-kpis.js";
import { UsageDonut } from "./stats-donut.js";
import { BudgetPanel } from "./stats-budget.js";
import { ModelTable } from "./stats-model-table.js";
import { TopKeys } from "./stats-top-keys.js";
import { StatsRail } from "./stats-rail.js";
import { DateRange } from "./date-range.js";

const html = htm.bind(h);

// Locked copy (13-UI-SPEC §Copywriting Contract / §"Page Surface").
const PAGE_TITLE = "Usage & Spend";
const PAGE_SUB = "Requests, tokens, models, and spend for the selected period.";
const SECTION_DAILY_SPEND = "DAILY SPEND";
const SECTION_REQUESTS = "REQUESTS BY DAY";
const SECTION_USAGE_BY_MODEL = "USAGE BY MODEL";
const SECTION_MODEL_BREAKDOWN = "MODEL BREAKDOWN";
const SECTION_INSIGHTS = "INSIGHTS";
const PILL_BETA = "Beta";
// Whole-page error copy (UI-SPEC §10 / §Copywriting Contract — the locked 502
// treatment; distinct from the in-panel "Couldn't load your usage." line).
const ERR_HEADING = "Couldn't load usage";
const ERR_BODY =
  "We couldn't reach the usage service. Check your connection and retry.";
// Static, illustrative Insights sample copy (UI-SPEC §8 — Beta, performs no
// action; the click path only fires the Coming-soon toast).
const INSIGHTS_SAMPLE =
  "Spend is trending within budget for this period. Detailed insights and recommendations are coming soon.";

// The default preset (Phase-12 default window — 30d, UI-SPEC §1 / D-10).
const DEFAULT_PRESET = "30d";

// ── SectionLabel ──────────────────────────────────────────────────────────────
// An 11px caption section header (mono, ALL-CAPS, --dim) — the UI-SPEC §Typography
// caption role shared by every band heading. The text is a locked constant.
function SectionLabel({ children }) {
  return html`<div class="stats-section-label">${children}</div>`;
}

// ── ChartPanel ────────────────────────────────────────────────────────────────
// A titled chart band: the caption section label above the uPlot chart (or its
// per-panel skeleton while loading).
function ChartPanel({ label, loading, children }) {
  return html`
    <div class="stats-chart-panel">
      <${SectionLabel}>${label}<//>
      ${loading
        ? html`<${Skeleton} variant="chart" />`
        : children}
    </div>
  `;
}

// ── StatsView ─────────────────────────────────────────────────────────────────
// Props: { me } — the /api/session/me payload (identity; the stats figures come
// from /api/session/stats, fetched here). Mirrors dashboard.js container shape.
export function StatsView({ me }) {
  const identity = me || {};

  // Date/compare state. `preset` drives the range via presetToRange; `range` is
  // the resolved {start, end} submitted to the server. `compareOn` is CLIENT-ONLY
  // (D-12 — toggles the KPI delta chips over server-computed deltas, NO fetch).
  const [preset, setPreset] = useState(DEFAULT_PRESET);
  const [range, setRange] = useState(() =>
    presetToRange(DEFAULT_PRESET, new Date()),
  );
  const [compareOn, setCompareOn] = useState(false);

  // The /stats payload + load status (dashboard.js status-state shape):
  // "loading" until the first response resolves, then "ok" | "error".
  const [stats, setStats] = useState(null);
  const [status, setStatus] = useState("loading");

  // An inline range error surfaced ON the DateRange control (server 422 over-cap
  // / bad custom range) — NOT the whole-page error (UI-SPEC §1).
  const [rangeError, setRangeError] = useState(null);

  // The no-op "coming soon" toast (D-13 / STATS-11). One instance; `show` is
  // threaded down to every mock extra (the rail's disabled glyphs + Insights).
  const { visible: toastVisible, show: showComingSoon } = useToast();

  // Monotonic sequence token so only the LATEST loadStats may write state. A
  // rapid preset change fires overlapping loadStats awaits; without sequencing an
  // earlier fetch could resolve last and clobber `stats` with a stale window
  // (WR-05 carried forward). Each call captures its seq and bails on resolve if a
  // newer call has since started.
  const loadSeq = useRef(0);

  const { start, end } = range;

  // Fetch /api/session/stats for the resolved range. Branch on the never-throw
  // {status, data} contract (api.js): 200 + data -> ok; 502 -> whole-page error
  // (D-16 current-window-fail); 422 -> inline rangeError (NOT whole-page); 0/other
  // -> whole-page error. The loadSeq guard discards a stale resolve.
  const loadStats = useCallback(async () => {
    const seq = ++loadSeq.current;
    setStatus("loading");
    const url = `/api/session/stats?start_date=${start}&end_date=${end}`;
    const { status: code, data } = await getJson(url);
    // A newer load started while this one was in flight — discard this result.
    if (seq !== loadSeq.current) return;

    if (code === 200 && data) {
      setRangeError(null);
      setStats(data);
      setStatus("ok");
      return;
    }
    if (code === 422) {
      // Bad / over-cap custom range — surface inline on the control, keep the
      // previously rendered data + an "ok" page (never a whole-page error).
      const msg =
        (data && (data.detail || data.message)) ||
        "Invalid date range. Choose a range within the last 366 days.";
      setRangeError(typeof msg === "string" ? msg : "Invalid date range.");
      setStatus(stats ? "ok" : "error");
      return;
    }
    // 502 (current-window fetch failed) / 0 (network) / any other -> whole-page.
    setStatus("error");
  }, [start, end, stats]);

  useEffect(() => {
    loadStats();
    // Re-fires whenever the resolved range changes (a preset / custom-range pick).
  }, [start, end]); // eslint-disable-line react-hooks/exhaustive-deps

  // A preset button click: recompute the range via presetToRange (the pure helper
  // clamps to the ~366d cap so the client never submits a 422-triggering span),
  // store it, and let the effect re-query. "Custom" recomputes to the default
  // window until the calendar Apply emits an explicit range.
  const onPreset = useCallback((id) => {
    setPreset(id);
    setRangeError(null);
    setRange(presetToRange(id, new Date()));
  }, []);

  // The calendar Apply emit: set the explicit range directly (the effect
  // re-queries). The server still re-validates (422 -> inline rangeError).
  const onCustomRange = useCallback(({ start: s, end: e }) => {
    setPreset("Custom");
    setRangeError(null);
    setRange({ start: s, end: e });
  }, []);

  // Compare toggle — CLIENT-ONLY, NO fetch (D-12). Flips the KPI delta chips over
  // the server-computed deltas.
  const onToggleCompare = useCallback(() => {
    setCompareOn((v) => !v);
  }, []);

  const route = "stats";
  const loading = status === "loading";

  // ── Whole-page error (D-16 — 502 / network) ────────────────────────────────
  // The rail + header chrome remain; the page body is the locked error card with
  // a red `retry` that re-fires loadStats. Reuses the SHELL_CSS .btn.retry markup
  // (app.js:225-228) — those styles already exist; this never redefines them.
  if (status === "error") {
    return html`
      <div class="stats-page">
        <${StatsRail} route=${route} onComingSoon=${showComingSoon} />
        <div class="stats-main">
          <div class="stats-error" data-state="error">
            <div class="stats-error-heading">${ERR_HEADING}</div>
            <div class="stats-error-body">${ERR_BODY}</div>
            <button class="btn retry" type="button" onClick=${loadStats}>
              <svg viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v5h-5"/></svg>
              retry
            </button>
          </div>
        </div>
        <${Toast} visible=${toastVisible} />
      </div>
    `;
  }

  // ── ok / loading compose ────────────────────────────────────────────────────
  // Distribute the contract slices. While loading `stats` is null, so every
  // figure falls back to its empty slice + the per-panel skeleton renders inline.
  const s = stats || {};
  const totals = s.totals || null;
  const series = s.series || [];
  const models = s.models || [];
  const keys = s.keys || [];
  const budget = s.budget || null;
  const capabilities = s.capabilities || {};
  const rangeDays =
    s.range && Number.isFinite(s.range.days) ? s.range.days : null;

  // Per-figure render modes (D-15) — capabilityRenderMode(caps, figureKey,
  // hasData): an explicit `false` capability -> "coming-soon"; available +
  // no-data -> "empty"; available + data -> "ready". Partial degrade (200 with
  // some figures null) thus shows ONLY the affected panels' state.
  const donutMode = capabilityRenderMode(
    capabilities,
    "per_model_spend",
    models.length > 0,
  );
  const topKeysMode = capabilityRenderMode(
    capabilities,
    "per_key_spend",
    keys.length > 0,
  );
  // The ModelTable owns its own loading/empty/error branch off `status`, so it
  // takes the raw status; the donut/top-keys take a resolved render mode.
  const tableStatus = loading ? "loading" : "ok";
  const totalSpend =
    totals && typeof totals.spend === "number" ? totals.spend : null;

  return html`
    <div class="stats-page">
      <${StatsRail} route=${route} onComingSoon=${showComingSoon} />
      <div class="stats-main">
        <div class="stats">
          <!-- §1 header band: title + sub on the LEFT, date controls top-RIGHT -->
          <div class="stats-header">
            <div class="stats-header-text">
              <div class="stats-title">${PAGE_TITLE}</div>
              <div class="stats-sub">${PAGE_SUB}</div>
            </div>
            <${DateRange}
              preset=${preset}
              compareOn=${compareOn}
              onPreset=${onPreset}
              onCustomRange=${onCustomRange}
              onToggleCompare=${onToggleCompare}
              rangeError=${rangeError}
            />
          </div>

          <!-- the page grid: a main column + a page-owned right column -->
          <div class="stats-grid">
            <div class="stats-grid-main">
              <!-- §2 KPI row -->
              ${loading
                ? html`<div class="stats-kpi-skeletons">
                    <${Skeleton} variant="card" />
                    <${Skeleton} variant="card" />
                    <${Skeleton} variant="card" />
                    <${Skeleton} variant="card" />
                  </div>`
                : html`<${KpiRow}
                    totals=${totals}
                    capabilities=${capabilities}
                    compareOn=${compareOn}
                    rangeDays=${rangeDays}
                  />`}

              <!-- §3 the two uPlot time-series, side-by-side (stack on narrow) -->
              <div class="stats-charts">
                <${ChartPanel} label=${SECTION_DAILY_SPEND} loading=${loading}>
                  <${SpendChart} series=${series} />
                <//>
                <${ChartPanel} label=${SECTION_REQUESTS} loading=${loading}>
                  <${RequestsChart} series=${series} />
                <//>
              </div>

              <!-- §4 donut + §5 top-keys -->
              <div class="stats-donut-keys">
                <div class="stats-donut-panel">
                  <${SectionLabel}>${SECTION_USAGE_BY_MODEL}<//>
                  ${loading
                    ? html`<${Skeleton} variant="chart" />`
                    : html`<${UsageDonut}
                        models=${models}
                        totalSpend=${totalSpend}
                        mode=${donutMode}
                      />`}
                </div>
                ${loading
                  ? html`<div class="stats-topkeys-skeleton">
                      <${Skeleton} variant="table-rows" rows=${5} />
                    </div>`
                  : html`<${TopKeys}
                      keys=${keys}
                      capabilities=${capabilities}
                      mode=${topKeysMode}
                    />`}
              </div>

              <!-- §6 Model Breakdown -->
              <div class="stats-model-breakdown">
                <${SectionLabel}>${SECTION_MODEL_BREAKDOWN}<//>
                <${ModelTable}
                  models=${models}
                  capabilities=${capabilities}
                  status=${tableStatus}
                />
              </div>
            </div>

            <!-- §8 page-owned right column: Budget + Insights (Beta, no-op) -->
            <aside class="stats-grid-right">
              ${loading
                ? html`<${Skeleton} variant="card" />`
                : html`<${BudgetPanel} budget=${budget} />`}
              <div class="stats-insights">
                <div class="stats-insights-head">
                  <span class="stats-section-label">${SECTION_INSIGHTS}</span>
                  <button
                    type="button"
                    class="stats-pill stats-pill-beta"
                    onClick=${showComingSoon}
                  >${PILL_BETA}</button>
                </div>
                <div
                  class="stats-insights-body"
                  onClick=${showComingSoon}
                >${INSIGHTS_SAMPLE}</div>
              </div>
            </aside>
          </div>
        </div>
      </div>
      <${Toast} visible=${toastVisible} />
    </div>
  `;
}

// ── Component stylesheet — var(--*) tokens only ───────────────────────────────
// The page-owned full-width grid (CONTEXT D-08): the 56px rail on the left edge,
// the main content column + a page-owned right column (Budget + Insights). Band
// rhythm mirrors `.dashboard` (dashboard.js:274) — flex-column, --space-3xl gap,
// slideUp .5s. Section labels reuse the 11px caption role; the Beta pill is a
// 999px pill. NEVER a raw hex — var(--*) only. Concatenated into app.js's
// injectShellStyles (wired in Task 2). The per-panel leaf CSS lives with each
// leaf; this owns ONLY the container grid + header + Insights + the error card.
export const STATS_CSS = `
.stats-page { display: flex; align-items: stretch; gap: 0; min-height: 100%; }
.stats-main { flex: 1 1 auto; min-width: 0; padding: var(--space-xl); }

.stats { display: flex; flex-direction: column; gap: var(--space-3xl); animation: slideUp .5s ease-out; }

/* §1 header band — title/sub left, date controls top-right. */
.stats-header {
  display: flex; align-items: flex-start; justify-content: space-between;
  gap: var(--space-xl); flex-wrap: wrap;
}
.stats-header .stats-title { font-family: var(--sans); font-size: 24px; font-weight: 600; color: var(--bright); line-height: 1.3; }
.stats-header .stats-sub { margin-top: var(--space-xs); font-family: var(--sans); font-size: 14px; color: var(--dim); }

/* Shared 11px caption section label. */
.stats-section-label {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 1.5px; color: var(--dim);
  margin-bottom: var(--space-md);
}

/* The page grid: main column + page-owned right column (Budget + Insights). */
.stats-grid { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: var(--space-2xl); align-items: start; }
.stats-grid-main { display: flex; flex-direction: column; gap: var(--space-3xl); min-width: 0; }
.stats-grid-right { display: flex; flex-direction: column; gap: var(--space-lg); }

/* §2 KPI skeletons — mirror the 4-card grid footprint while loading. */
.stats-kpi-skeletons { display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--space-md); }

/* §3 charts — two panels side-by-side, each a --surface card. */
.stats-charts { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--space-md); }
.stats-chart-panel {
  background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
  padding: var(--space-lg); min-width: 0;
}

/* §4 donut + §5 top-keys — donut left, top-keys right (stack on narrow). */
.stats-donut-keys { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: var(--space-md); align-items: start; }
.stats-donut-panel {
  background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
  padding: var(--space-lg); min-width: 0;
}
.stats-topkeys-skeleton {
  background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
  padding: var(--space-lg);
}

/* §6 Model Breakdown — the section label sits above the table container. */
.stats-model-breakdown { min-width: 0; }

/* §8 Insights panel (Beta, no-op) — static sample copy. */
.stats-insights {
  background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
  padding: var(--space-lg); display: flex; flex-direction: column; gap: var(--space-sm);
}
.stats-insights-head { display: flex; align-items: center; justify-content: space-between; gap: var(--space-md); }
.stats-insights-head .stats-section-label { margin-bottom: 0; }
.stats-insights-body { font-family: var(--sans); font-size: 14px; color: var(--dim); line-height: 1.5; cursor: pointer; }

/* Beta/Soon pill — 999px pill, accent-tinted. */
.stats-pill {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 1px;
  border-radius: 999px; padding: var(--space-xs) var(--space-sm);
  cursor: pointer; line-height: 1;
}
.stats-pill-beta { color: var(--accent); background: var(--glow); border: 1px solid var(--accent); }

/* Whole-page error card (D-16 — 502 / network). Reuses the .btn.retry styles
 * already in SHELL_CSS (app.js) — this only lays out the card. */
.stats-error {
  background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
  padding: var(--space-3xl) var(--space-xl); text-align: center;
  display: flex; flex-direction: column; align-items: center; gap: var(--space-md);
  animation: slideUp .5s ease-out;
}
.stats-error[data-state="error"] { box-shadow: 0 0 80px -20px var(--glow-err); }
.stats-error .stats-error-heading { font-family: var(--sans); font-size: 24px; font-weight: 600; color: var(--bright); }
.stats-error .stats-error-body { font-family: var(--sans); font-size: 14px; color: var(--dim); max-width: 420px; }

/* §9 Responsive collapse — the right column drops below the main grid, then the
 * charts + donut/keys stack 1-up (the tables own their own column drop). */
@media (max-width: 1100px) {
  .stats-grid { grid-template-columns: minmax(0, 1fr); }
  .stats-grid-right { flex-direction: row; flex-wrap: wrap; }
  .stats-grid-right > * { flex: 1 1 280px; }
}
@media (max-width: 880px) {
  .stats-charts { grid-template-columns: minmax(0, 1fr); }
  .stats-donut-keys { grid-template-columns: minmax(0, 1fr); }
  .stats-kpi-skeletons { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 768px) {
  .stats-main { padding: var(--space-lg); }
}
@media (max-width: 520px) {
  .stats-kpi-skeletons { grid-template-columns: 1fr; }
  .stats-grid-right { flex-direction: column; }
}
`;
