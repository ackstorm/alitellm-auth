// skeleton.js — per-panel loading shimmer for the #/stats Usage & Spend page.
//
// CONTEXT D-14 / 13-UI-SPEC §10: loading is PER-PANEL, never a whole-page
// loader. Each panel (KPI card, chart, donut, table, budget) renders a
// shape-matched placeholder that occupies the SAME footprint as the real panel
// while /stats resolves. The shimmer is a subtle `--surface` <-> `--border`
// pulse — it REUSES the inherited `pulse` animation from base.css (base.css:62)
// and introduces NO new color and NO new keyframe (UI-SPEC §10 / §Color).
//
// Module shape: `Skeleton` component + `SKELETON_CSS` string, so app.js's
// `injectShellStyles` (wired in 13-05) can concatenate the CSS. CSS uses ONLY
// var(--*) tokens — never a raw hex.
import { h } from "preact";
import htm from "htm";

const html = htm.bind(h);

// The shape variants a panel can stand in for. Each maps to a CSS modifier that
// gives the placeholder the real panel's footprint (16px-radius card shape):
//   card       — a KPI card / budget panel block
//   chart      — a ~220-260px tall chart panel
//   table-rows — a stack of table row bars
//   bar        — a single short bar (e.g. a horizontal-bar / legend row)
const VARIANTS = new Set(["card", "chart", "table-rows", "bar"]);

// Skeleton({ variant, rows }) -> a shape-matched shimmer placeholder.
//   variant : "card" | "chart" | "table-rows" | "bar"  (default "card")
//   rows    : row count for the "table-rows" variant   (default 5)
// Renders the inherited pulse animation over a `--surface`/`--border` block; no
// data, no contract values, no network — purely decorative (threat T-13-04).
export function Skeleton({ variant = "card", rows = 5 } = {}) {
  const v = VARIANTS.has(variant) ? variant : "card";

  if (v === "table-rows") {
    const count = Number.isFinite(rows) && rows > 0 ? Math.floor(rows) : 5;
    const items = Array.from({ length: count });
    return html`
      <div class="skeleton skeleton--table-rows" aria-hidden="true">
        ${items.map(
          () => html`<div class="skeleton-block skeleton-row"></div>`
        )}
      </div>
    `;
  }

  return html`
    <div class="skeleton skeleton--${v}" aria-hidden="true">
      <div class="skeleton-block"></div>
    </div>
  `;
}

// ── Component stylesheet — var(--*) tokens only, reuses the pulse animation ────
// The shimmer block animates the inherited `pulse` (base.css:62-65) and tints
// between --surface and --border. NO new animation declared, NO raw hex.
export const SKELETON_CSS = `
.skeleton { width: 100%; }
.skeleton-block {
  background: var(--border);
  border: 1px solid var(--border);
  border-radius: 16px;
  animation: pulse 2s ease-in-out infinite;
}

/* Card footprint — a KPI card / budget block. */
.skeleton--card .skeleton-block { height: 96px; }

/* Chart footprint — the ~220-260px uPlot panel height. */
.skeleton--chart .skeleton-block { height: 240px; }

/* A single short bar (horizontal-bar / legend row stand-in). */
.skeleton--bar .skeleton-block { height: 14px; border-radius: 999px; }

/* Table rows — a stack of row-height bars inside a card-shaped container. */
.skeleton--table-rows { display: flex; flex-direction: column; gap: var(--space-md); }
.skeleton--table-rows .skeleton-row {
  height: 16px;
  border-radius: 999px;
  animation: pulse 2s ease-in-out infinite;
}
`;
