// stats-rail.js — the STATS-PAGE-LOCAL left icon rail for the #/stats Usage &
// Spend page (CONTEXT D-06/D-07). Preact + htm tagged templates, no JSX, no
// TypeScript (inherited 13-CONTEXT D-04).
//
// A 56px vertical rail on the page's left edge, rendered ONLY on #/stats. It is
// NOT a global shell nav — do NOT touch the #/ chrome (CONTEXT D-06; the
// dashboard/login fidelity unification is Phase 14).
//
//   • Real-route icons: Dashboard (-> #/) and Stats (-> #/stats, marked active
//     via the topbar `a.active` accent indicator). Navigation sets
//     window.location.hash (the sidebar.js:23-25 hash-nav idiom; hashchange
//     re-renders via useHashRoute). The hash never hits the server (router.js).
//   • Coming-soon glyphs: the mockup's extra icons render DISABLED (--dim,
//     reduced opacity, `Soon` tooltip) and on click fire the `onComingSoon`
//     callback (the 13-05 container wires it to the toast — D-07/D-13). They are
//     NOT navigable.
//
// Icons are inline SVG stroke icons matching the topbar shield style (app.js:264,
// app.js:119 stroke treatment). Hit target 40px desktop / 44px mobile.
//
// SECURITY: the rail performs NO fetch and renders only constant copy/SVG — no
// contract values, no innerHTML, no network. The coming-soon glyphs invoke a
// caller-supplied no-op callback (the toast) only.
import { h } from "preact";
import htm from "htm";

const html = htm.bind(h);

// The real routes this rail navigates (the router.js allow-list — #/ dashboard,
// #/stats stats). Each carries a stroke-icon path + an accessible tooltip label.
const DASHBOARD_ICON = "M3 12 12 3l9 9M5 10v10h14V10";
const STATS_ICON = "M4 20V10M10 20V4M16 20v-8M22 20H2";

// The disabled "coming soon" glyphs (mockup extras) — labeled `Soon`, not
// navigable; clicking fires onComingSoon. Distinct stroke icons keep the rail
// visually faithful to the mockup without implying a real destination.
const COMING_SOON_GLYPHS = [
  { id: "keys", icon: "M15 7a4 4 0 1 0-3.9 5H13l2 2 2-2 2 2 2-2-2-2" },
  { id: "alerts", icon: "M18 8a6 6 0 1 0-12 0c0 7-3 9-3 9h18s-3-2-3-9M13.7 21a2 2 0 0 1-3.4 0" },
  { id: "settings", icon: "M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.65 1.65 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.65 1.65 0 0 0-2.8 1.2V21a2 2 0 1 1-4 0v-.1A1.65 1.65 0 0 0 7 19.4a2 2 0 1 1-2.8-2.8l.1-.1A1.65 1.65 0 0 0 5.6 14H5a2 2 0 1 1 0-4h.1A1.65 1.65 0 0 0 7 7.6a2 2 0 1 1 2.8-2.8l.1.1A1.65 1.65 0 0 0 12 5.6V5a2 2 0 1 1 4 0v.1A1.65 1.65 0 0 0 18 7" },
];

// One rail icon button (inline SVG stroke icon over a 40px square hit target).
function RailIcon({ path, label, active, disabled, onClick }) {
  return html`
    <button
      type="button"
      class="rail-icon ${active ? "is-active" : ""} ${disabled ? "is-disabled" : ""}"
      title=${label}
      aria-label=${label}
      aria-current=${active ? "page" : undefined}
      onClick=${onClick}
    >
      <svg viewBox="0 0 24 24" aria-hidden="true"><path d=${path} /></svg>
    </button>
  `;
}

// ── StatsRail ────────────────────────────────────────────────────────────────
// Props: { route, onComingSoon }
//   route        : the current resolved route name ("dashboard" | "stats") from
//                  useHashRoute; "stats" marks the Stats glyph active.
//   onComingSoon : () => void — invoked by every disabled glyph (the 13-05
//                  container wires it to the toast). Defaults to a no-op so the
//                  component never throws if unwired.
export function StatsRail({ route, onComingSoon }) {
  const fireComingSoon = typeof onComingSoon === "function" ? onComingSoon : () => {};

  // Real-route navigation: set the hash (sidebar.js:23-25 idiom). hashchange ->
  // useHashRoute re-renders; no full page load, no server hit.
  const goDashboard = () => { window.location.hash = "#/"; };
  const goStats = () => { window.location.hash = "#/stats"; };

  return html`
    <nav class="stats-rail" aria-label="Stats navigation">
      <div class="rail-group">
        <${RailIcon}
          path=${DASHBOARD_ICON}
          label="Dashboard"
          active=${route === "dashboard"}
          onClick=${goDashboard}
        />
        <${RailIcon}
          path=${STATS_ICON}
          label="Stats"
          active=${route === "stats"}
          onClick=${goStats}
        />
      </div>
      <div class="rail-group rail-group-soon">
        ${COMING_SOON_GLYPHS.map(
          (g) => html`<${RailIcon}
            key=${g.id}
            path=${g.icon}
            label="Soon"
            disabled=${true}
            onClick=${fireComingSoon}
          />`,
        )}
      </div>
    </nav>
  `;
}

// ── Component stylesheet — var(--*) tokens only ───────────────────────────────
// A 56px vertical rail (CONTEXT D-06 layout constant, not a spacing token) with
// 40px-square icon hit targets (44px on mobile). The active item reuses the
// topbar `a.active` accent indicator (app.js:130) — accent glyph + a left accent
// border/glow. Disabled glyphs are --dim at reduced opacity. NEVER a raw hex —
// var(--*) only. Concatenated into app.js's injectShellStyles (wired in 13-05).
export const STATS_RAIL_CSS = `
.stats-rail {
  width: 56px; flex: 0 0 56px;
  display: flex; flex-direction: column; justify-content: space-between; align-items: center;
  gap: var(--space-lg);
  padding: var(--space-lg) 0;
  background: var(--surface);
  border-right: 1px solid var(--border);
}
.stats-rail .rail-group { display: flex; flex-direction: column; align-items: center; gap: var(--space-sm); }

.stats-rail .rail-icon {
  position: relative;
  width: 40px; height: 40px;
  display: inline-flex; align-items: center; justify-content: center;
  background: transparent; border: 1px solid transparent; border-radius: 8px;
  color: var(--dim); cursor: pointer;
  transition: color .15s, background .15s, border-color .15s;
}
.stats-rail .rail-icon svg {
  width: 20px; height: 20px;
  stroke: currentColor; fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round;
}
.stats-rail .rail-icon:hover { color: var(--text); }

/* Active route — accent glyph + a left accent indicator + --glow tint (the
 * topbar a.active treatment, vertical-rail variant). */
.stats-rail .rail-icon.is-active {
  color: var(--accent);
  background: var(--glow);
  border-color: var(--accent);
}
.stats-rail .rail-icon.is-active::before {
  content: ""; position: absolute; left: -8px; top: 8px; bottom: 8px;
  width: 2px; border-radius: 999px; background: var(--accent);
}

/* Disabled coming-soon glyphs — --dim at reduced opacity, still clickable to
 * fire the toast but visibly non-navigable. */
.stats-rail .rail-icon.is-disabled { color: var(--dim); opacity: .45; cursor: pointer; }
.stats-rail .rail-icon.is-disabled:hover { color: var(--dim); }

/* Touch targets ≥ 44px on mobile (UI-SPEC §9). */
@media (max-width: 768px) {
  .stats-rail .rail-icon { width: 44px; height: 44px; }
}
`;
