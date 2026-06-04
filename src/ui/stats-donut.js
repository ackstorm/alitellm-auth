// stats-donut.js — the hand-rolled Usage-by-Model donut + legend for the
// #/stats Usage & Spend page (STATS-05). Preact + htm tagged templates, no JSX,
// no TypeScript (inherited 13-CONTEXT D-04).
//
// CONTEXT D-01: uPlot has no pie/donut — this is hand-rolled INLINE SVG. The
// donut shows the Top-5 named slices by spend + one neutral `Other` aggregate
// (CONTEXT D-04), with the `${totalSpend}` figure centered (24px heading) under
// a `TOTAL` caption. Slice color order steps accent -> accent2 -> desaturated
// --dim/--border tones, with `Other` ALWAYS the neutral non-accent color so it
// never competes with a real model (13-UI-SPEC §4 / §Color).
//
// This is a PURE presentational leaf — no fetch, no data ownership. The 13-05
// container passes the Phase-12 `models` slice, the `totalSpend`, and a per-
// figure render `mode` ("ready" | "coming-soon" | "empty").
//
// SECURITY (threat T-13-05, XSS — MITIGATED): model name strings render as
// Preact text children via htm (auto-escaped) — in the legend AND in the hover
// tooltip. The inline SVG never sets text/HTML from unescaped contract data; no
// raw-HTML injection sink, no innerHTML. Numeric values pass through format.js.
//
// SECURITY (threat T-13-07, DoS / divide-by-zero — MITIGATED): every arc
// fraction reuses the `total > 0 ? share/total : 0` guard from dashboard.js
// BudgetBar (dashboard.js:100-102) so a null/zero total never yields NaN.
import { h } from "preact";
import { useState } from "preact/hooks";
import htm from "htm";
import { formatCurrency } from "./format.js";

const html = htm.bind(h);

const EM_DASH = "—";

// Locked copy (13-UI-SPEC §Copywriting Contract).
const OTHER_LABEL = "Other";
const TOTAL_CAPTION = "TOTAL";
const COMING_SOON_COPY = "Coming soon";
const EMPTY_COPY = "No usage in this range";

// SVG geometry — a 160x160 viewBox donut. `R` is the stroke centerline radius;
// the stroke width carves the ring. Component dimensions, NOT spacing tokens
// (13-UI-SPEC §Spacing "Exceptions").
const SVG_SIZE = 160;
const CENTER = SVG_SIZE / 2;
const STROKE = 22;
const R = (SVG_SIZE - STROKE) / 2; // centerline radius
const CIRC = 2 * Math.PI * R;

// Slice color order (13-UI-SPEC §4/§Color): --accent (largest) -> --accent2 ->
// three stepped-down desaturated --dim/--border-derived tones; the trailing
// `Other` bucket is forced to the neutral --dim regardless of position.
const SLICE_COLORS = [
  "var(--accent)",
  "var(--accent2)",
  "var(--text)",
  "var(--dim)",
  "var(--border)",
];
const OTHER_COLOR = "var(--dim)";

// Format a contract spend_pct fraction (e.g. 0.182) as a one-decimal `%`; a
// null/non-finite fraction -> em-dash (never `0%` / `NaN`).
function formatPct(pct) {
  if (pct === null || pct === undefined || !Number.isFinite(pct)) return EM_DASH;
  return `${(pct * 100).toFixed(1)}%`;
}

// rankSlices(models) -> [{model, spend, spend_pct, color, isOther}] of at most
// 6 entries: the Top-5 named slices by spend desc + a single summed `Other`.
// Pure: no DOM, no mutation of the input array.
function rankSlices(models) {
  const list = Array.isArray(models) ? models.slice() : [];
  list.sort((a, b) => (b && b.spend ? b.spend : 0) - (a && a.spend ? a.spend : 0));

  const top = list.slice(0, 5).map((m, i) => ({
    model: m && m.model ? m.model : EM_DASH,
    spend: m && typeof m.spend === "number" ? m.spend : 0,
    spend_pct: m && typeof m.spend_pct === "number" ? m.spend_pct : null,
    color: SLICE_COLORS[i] || OTHER_COLOR,
    isOther: false,
  }));

  const rest = list.slice(5);
  if (rest.length > 0) {
    let otherSpend = 0;
    let otherPct = 0;
    let anyPct = false;
    for (const m of rest) {
      if (m && typeof m.spend === "number") otherSpend += m.spend;
      if (m && typeof m.spend_pct === "number") {
        otherPct += m.spend_pct;
        anyPct = true;
      }
    }
    top.push({
      model: OTHER_LABEL,
      spend: otherSpend,
      spend_pct: anyPct ? otherPct : null,
      color: OTHER_COLOR,
      isOther: true,
    });
  }

  return top;
}

// ── DonutSvg ───────────────────────────────────────────────────────────────��─
// The inline-SVG ring. Each slice is a stroked circle segment whose arc length
// is its share of the total spend (divide-by-zero guarded). Hovering a slice
// lifts it into the tooltip via onSlice(index).
function DonutSvg({ slices, total, onSlice, activeIndex }) {
  let offset = 0;
  const segments = slices.map((s, i) => {
    // Divide-by-zero guard (dashboard.js:100 analog): total > 0 ? share : 0.
    const frac = total > 0 ? s.spend / total : 0;
    const dash = frac * CIRC;
    // SVG dash arrays measure clockwise from 3 o'clock; rotate -90 to start top.
    const seg = html`<circle
      key=${i}
      cx=${CENTER}
      cy=${CENTER}
      r=${R}
      fill="none"
      stroke=${s.color}
      stroke-width=${activeIndex === i ? STROKE + 4 : STROKE}
      stroke-dasharray=${`${dash} ${CIRC - dash}`}
      stroke-dashoffset=${-offset}
      class="donut-seg"
      onMouseenter=${() => onSlice(i)}
      onMouseleave=${() => onSlice(-1)}
    ></circle>`;
    offset += dash;
    return seg;
  });

  return html`
    <svg
      class="donut-svg"
      viewBox=${`0 0 ${SVG_SIZE} ${SVG_SIZE}`}
      width=${SVG_SIZE}
      height=${SVG_SIZE}
      role="img"
    >
      <g transform=${`rotate(-90 ${CENTER} ${CENTER})`}>${segments}</g>
    </svg>
  `;
}

// ── UsageDonut ─────────────────────────────────────────────────────────────��─
// Props:
//   models     — the Phase-12 `models` slice ([{model, spend, spend_pct, ...}])
//   totalSpend — the total spend figure centered under the TOTAL caption
//   mode       — "ready" | "coming-soon" | "empty" (capabilityRenderMode output)
//
// "coming-soon" -> Coming soon caption (--dim) + em-dash where the total sits.
// "empty"       -> `No usage in this range`.
// "ready"       -> the donut + legend + hover tooltip.
export function UsageDonut({ models, totalSpend, mode = "ready" }) {
  const [active, setActive] = useState(-1);

  if (mode === "coming-soon") {
    return html`
      <div class="usage-donut usage-donut--state">
        <div class="donut-center-cap">${TOTAL_CAPTION}</div>
        <div class="donut-center-total">${EM_DASH}</div>
        <div class="donut-state-copy">${COMING_SOON_COPY}</div>
      </div>
    `;
  }

  if (mode === "empty") {
    return html`
      <div class="usage-donut usage-donut--state">
        <div class="donut-state-copy">${EMPTY_COPY}</div>
      </div>
    `;
  }

  const slices = rankSlices(models);
  const total =
    typeof totalSpend === "number"
      ? totalSpend
      : slices.reduce((acc, s) => acc + s.spend, 0);

  const activeSlice = active >= 0 && active < slices.length ? slices[active] : null;

  return html`
    <div class="usage-donut">
      <div class="donut-figure">
        <${DonutSvg}
          slices=${slices}
          total=${total}
          onSlice=${setActive}
          activeIndex=${active}
        />
        <div class="donut-center">
          <div class="donut-center-cap">${TOTAL_CAPTION}</div>
          <div class="donut-center-total">${formatCurrency(total)}</div>
        </div>
        ${activeSlice
          ? html`<div class="donut-tooltip">
              <span class="donut-tip-name">${activeSlice.model}</span>
              <span class="donut-tip-spend">${formatCurrency(activeSlice.spend)}</span>
              <span class="donut-tip-pct">${formatPct(activeSlice.spend_pct)}</span>
            </div>`
          : null}
      </div>
      <ul class="donut-legend">
        ${slices.map(
          (s, i) => html`<li
            class="donut-legend-row ${active === i ? "is-active" : ""}"
            onMouseenter=${() => setActive(i)}
            onMouseleave=${() => setActive(-1)}
          >
            <span class="donut-swatch" style=${`background:${s.color}`}></span>
            <span class="donut-legend-name">${s.model}</span>
            <span class="donut-legend-spend">${formatCurrency(s.spend)}</span>
            <span class="donut-legend-pct">${formatPct(s.spend_pct)}</span>
          </li>`
        )}
      </ul>
    </div>
  `;
}

// ── Component stylesheet — var(--*) tokens only ───────────────────────────────
// The donut panel: inline-SVG ring on the left, legend on the right (stacks
// below on narrow). Center figure is the 24px heading; the TOTAL caption is the
// 11px caption. Legend values are 12px mono; the model name truncates. NEVER a
// raw hex — var(--*) tokens only. Concatenated into injectShellStyles (13-05).
export const STATS_DONUT_CSS = `
.usage-donut {
  display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-2xl);
  background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
  padding: var(--space-lg);
}
.usage-donut--state {
  flex-direction: column; align-items: center; justify-content: center;
  gap: var(--space-sm); min-height: 160px; text-align: center;
}
.usage-donut .donut-state-copy { font-family: var(--sans); font-size: 14px; color: var(--dim); }

.usage-donut .donut-figure { position: relative; width: 160px; height: 160px; flex-shrink: 0; }
.usage-donut .donut-svg { display: block; }
.usage-donut .donut-seg { transition: stroke-width .15s; cursor: pointer; }
.usage-donut .donut-center {
  position: absolute; inset: 0; display: flex; flex-direction: column;
  align-items: center; justify-content: center; pointer-events: none; gap: var(--space-xs);
}
.usage-donut .donut-center-cap {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 1px; color: var(--dim);
}
.usage-donut .donut-center-total {
  font-family: var(--sans); font-size: 24px; font-weight: 600; color: var(--accent);
  line-height: 1.3;
}
.usage-donut .donut-tooltip {
  position: absolute; top: -8px; left: 50%; transform: translate(-50%, -100%);
  display: flex; flex-direction: column; gap: var(--space-xs);
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: var(--space-sm) var(--space-md); white-space: nowrap; pointer-events: none;
  font-family: var(--mono); font-size: 12px; color: var(--text); z-index: 2;
}
.usage-donut .donut-tooltip .donut-tip-name { color: var(--bright); }

.usage-donut .donut-legend {
  flex: 1 1 200px; list-style: none; margin: 0; padding: 0;
  display: flex; flex-direction: column; gap: var(--space-sm);
}
.usage-donut .donut-legend-row {
  display: grid; grid-template-columns: auto 1fr auto auto; align-items: center;
  gap: var(--space-sm); padding: var(--space-xs) var(--space-sm); border-radius: 8px;
}
.usage-donut .donut-legend-row.is-active { background: var(--bg); }
.usage-donut .donut-swatch { width: 10px; height: 10px; border-radius: 999px; flex-shrink: 0; }
.usage-donut .donut-legend-name {
  font-family: var(--mono); font-size: 12px; color: var(--text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.usage-donut .donut-legend-spend { font-family: var(--mono); font-size: 12px; color: var(--bright); }
.usage-donut .donut-legend-pct { font-family: var(--mono); font-size: 12px; color: var(--dim); }

@media (max-width: 768px) {
  .usage-donut { flex-direction: column; align-items: center; }
}
`;
