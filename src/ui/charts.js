// charts.js — the uPlot wrapper for the TWO #/stats time-series (STATS-03 Daily
// Spend, STATS-04 Requests-by-Day) plus the pure `seriesToUplot` transform.
//
// CONTEXT D-01/D-02 / 13-UI-SPEC §3: uPlot renders ONLY these two time-series,
// themed to the dark-terminal tokens with NATIVE hover tooltips (D-03, no synced
// crosshair). Everything else on the page (donut, top-keys bars, budget bar)
// stays hand-rolled. Centralizing the uPlot lifecycle + a pure series transform
// keeps the container thin and the transform unit-testable.
//
// Module shape: pure `seriesToUplot` + `SpendChart` + `RequestsChart` +
// `CHARTS_CSS`. The pure transform is import-free and DOM-free so charts.test.js
// runs in the node env (mirrors format.js purity). CSS uses ONLY var(--*) tokens
// / allowed rgba(...) — never a raw hex.
//
// SECURITY (threat T-13-03, XSS): tooltip content is built from `format.js`
// outputs (formatDate / formatCurrency / formatInt — all return plain strings)
// and assigned via `textContent`, NEVER innerHTML. No dangerouslySetInnerHTML.
// Numeric/date contract values pass through the formatters before display.
import { h } from "preact";
import { useRef, useEffect } from "preact/hooks";
import htm from "htm";
import uPlot from "uplot";
import "uplot/dist/uPlot.min.css";
import { formatDate, formatCurrency, formatInt } from "./format.js";

const html = htm.bind(h);

// Locked empty-state copy (13-UI-SPEC §Copywriting Contract / §3).
const EMPTY_COPY = "No usage in this range";

// Chart height (13-UI-SPEC §3 — ~220-260px).
const CHART_HEIGHT = 240;

// ── seriesToUplot (PURE) ──────────────────────────────────────────────────────
// seriesToUplot(series, field) -> [xs, ys].
//   series : the Phase-12 [{date, spend, requests}] contract (or null/empty).
//   field  : "spend" | "requests" — the y field to read.
//
// Maps to uPlot's [xs, ys] array pair: xs are UTC unix SECONDS (uPlot's default
// time axis unit, tz-stable via Date.parse of an explicit Z timestamp), ys are
// the named field per row, both in input order. An empty / null / non-array
// series returns the no-data shape `[[],[]]` so the wrapper renders the empty
// state instead of instantiating an empty uPlot grid.
//
// Pure: no DOM, no uPlot reference, no input mutation — unit-tested in the node
// env (charts.test.js), mirroring format.js.
export function seriesToUplot(series, field) {
  if (!Array.isArray(series) || series.length === 0) {
    return [[], []];
  }
  const xs = new Array(series.length);
  const ys = new Array(series.length);
  for (let i = 0; i < series.length; i++) {
    const point = series[i] || {};
    // UTC midnight unix seconds; an unparseable date becomes NaN (uPlot skips it)
    // rather than throwing — the transform never crashes the render.
    const ms = Date.parse(`${point.date}T00:00:00Z`);
    xs[i] = Number.isNaN(ms) ? NaN : Math.floor(ms / 1000);
    const v = point[field];
    ys[i] = typeof v === "number" ? v : null;
  }
  return [xs, ys];
}

// A series is "empty" (renders the empty state, not an empty grid) when the
// transform produced no x points.
function isNoData([xs]) {
  return !Array.isArray(xs) || xs.length === 0;
}

// ── uPlot tooltip plugin ──────────────────────────────────────────────────────
// A minimal native hover tooltip (D-03). On the closest data index it shows the
// formatted date + the formatted y value. Content is set via textContent only
// (XSS-safe, T-13-03). Each chart owns its own hover — no synced crosshair.
function tooltipPlugin(formatY) {
  let tipEl;
  return {
    hooks: {
      init: (u) => {
        tipEl = document.createElement("div");
        tipEl.className = "chart-tooltip";
        tipEl.style.display = "none";
        u.over.appendChild(tipEl);
      },
      setCursor: (u) => {
        const { idx, left, top } = u.cursor;
        if (idx === null || idx === undefined) {
          if (tipEl) tipEl.style.display = "none";
          return;
        }
        const xVal = u.data[0][idx];
        const yVal = u.data[1][idx];
        if (xVal === undefined || yVal === null || yVal === undefined) {
          tipEl.style.display = "none";
          return;
        }
        // xVal is unix seconds -> ISO for formatDate (UTC, tz-stable).
        const dateLabel = formatDate(new Date(xVal * 1000).toISOString());
        // textContent only — never innerHTML (T-13-03).
        tipEl.textContent = `${dateLabel} · ${formatY(yVal)}`;
        tipEl.style.display = "block";
        tipEl.style.left = `${left}px`;
        tipEl.style.top = `${top}px`;
      },
    },
  };
}

// Read a CSS custom property off :root so uPlot's canvas strokes use the same
// dark-terminal tokens as the hand-rolled panels (canvas can't read var(--*)).
function token(name, fallback) {
  if (typeof window === "undefined" || !window.getComputedStyle) return fallback;
  const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return v || fallback;
}

// Shared axis/grid theming (12px mono --dim ticks, --border gridlines).
function themedAxes() {
  const border = token("--border", "var(--border)");
  const dim = token("--dim", "var(--dim)");
  const mono = token("--mono", "monospace");
  const axis = {
    stroke: dim,
    font: `12px ${mono}`,
    ticks: { stroke: border, width: 1 },
    grid: { stroke: border, width: 1 },
  };
  return [
    { ...axis, space: 48 }, // x (time)
    { ...axis }, // y
  ];
}

// ── useUplotChart ─────────────────────────────────────────────────────────────
// The shared instantiate-on-mount / destroy-on-cleanup discipline (mirrors the
// router.js add/removeEventListener cleanup and dashboard.js's effect/ref usage).
// Re-instantiates when data or the optsBuilder identity changes; ALWAYS destroys
// the prior instance in the effect cleanup so no canvas/listener leaks.
function useUplotChart(data, buildOpts) {
  const containerRef = useRef(null);
  const noData = isNoData(data);

  useEffect(() => {
    if (noData || !containerRef.current) return undefined;
    const width = containerRef.current.clientWidth || 600;
    const opts = buildOpts(width);
    const u = new uPlot(opts, data, containerRef.current);

    // Keep the chart width in sync with its container (responsive collapse).
    const onResize = () => {
      const w = containerRef.current ? containerRef.current.clientWidth : width;
      if (w) u.setSize({ width: w, height: CHART_HEIGHT });
    };
    window.addEventListener("resize", onResize);

    return () => {
      window.removeEventListener("resize", onResize);
      u.destroy();
    };
    // buildOpts is recreated per-render by each chart; data identity drives re-init.
  }, [data, buildOpts, noData]);

  return { containerRef, noData };
}

// EmptyPanel — the locked empty state shown instead of an empty uPlot grid.
function EmptyPanel() {
  return html`
    <div class="chart-empty"><div class="chart-empty-body">${EMPTY_COPY}</div></div>
  `;
}

// ── SpendChart (STATS-03 — Daily Spend, area/line) ────────────────────────────
// accent stroke + --glow2 -> transparent area fill; --border gridlines; 12px
// mono --dim ticks; hover tooltip = formatDate(date) + formatCurrency(spend).
export function SpendChart({ series }) {
  const data = seriesToUplot(series, "spend");

  function buildOpts(width) {
    const accent = token("--accent", "var(--accent)");
    const glow2 = token("--glow2", "var(--glow2)");
    return {
      width,
      height: CHART_HEIGHT,
      cursor: { y: false },
      legend: { show: false },
      axes: themedAxes(),
      scales: { x: { time: true } },
      series: [
        {},
        {
          stroke: accent,
          width: 2,
          fill: glow2,
          points: { show: false },
        },
      ],
      plugins: [tooltipPlugin(formatCurrency)],
    };
  }

  const { containerRef, noData } = useUplotChart(data, buildOpts);
  if (noData) return html`<${EmptyPanel} />`;
  return html`<div class="chart" ref=${containerRef}></div>`;
}

// ── RequestsChart (STATS-04 — Requests by Day, bars) ──────────────────────────
// --accent bars at reduced opacity; same axis/grid theming; hover tooltip =
// formatDate(date) + formatInt(requests).
export function RequestsChart({ series }) {
  const data = seriesToUplot(series, "requests");

  function buildOpts(width) {
    const accent = token("--accent", "var(--accent)");
    return {
      width,
      height: CHART_HEIGHT,
      cursor: { y: false },
      legend: { show: false },
      axes: themedAxes(),
      scales: { x: { time: true } },
      series: [
        {},
        {
          stroke: accent,
          width: 1,
          fill: token("--glow2", "var(--glow2)"),
          paths: uPlot.paths.bars ? uPlot.paths.bars({ size: [0.7, 100] }) : undefined,
          points: { show: false },
        },
      ],
      plugins: [tooltipPlugin(formatInt)],
    };
  }

  const { containerRef, noData } = useUplotChart(data, buildOpts);
  if (noData) return html`<${EmptyPanel} />`;
  return html`<div class="chart" ref=${containerRef}></div>`;
}

// ── Component stylesheet — var(--*) tokens / allowed rgba(...) only ────────────
// Themes the uPlot wrapper + the native hover tooltip + the empty state. The
// canvas strokes are set in JS (uPlot can't read var(--*)); these styles cover
// the surrounding chrome. NO raw hex.
export const CHARTS_CSS = `
.chart { width: 100%; min-height: ${CHART_HEIGHT}px; position: relative; }
.chart .u-axis, .chart .u-legend { font-family: var(--mono); }

.chart-tooltip {
  position: absolute;
  transform: translate(-50%, calc(-100% - 8px));
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: var(--space-xs) var(--space-sm);
  font-family: var(--mono);
  font-size: 12px;
  color: var(--bright);
  white-space: nowrap;
  pointer-events: none;
  z-index: 10;
  box-shadow: 0 4px 16px -4px rgba(0, 0, 0, 0.6);
}

.chart-empty {
  display: flex; align-items: center; justify-content: center;
  min-height: ${CHART_HEIGHT}px;
}
.chart-empty .chart-empty-body {
  font-family: var(--sans); font-size: 14px; color: var(--dim);
}
`;
