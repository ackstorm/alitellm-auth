// sidebar.js — the authenticated shell's RIGHT SIDEBAR (Preact + htm, no JSX).
//
// Three panels per 09-UI-SPEC §B "Right sidebar panels (D-08 scope)" + §E
// "Sidebar" locked copy:
//   • QUICK ACTIONS (PRIMARY) — a `Create key` shortcut (Phase 10 wires it via
//     the `onCreateKey` prop to open the Dashboard-owned create modal — the
//     SAME modal the main `+ New Key` CTA opens. It calls NO /keys endpoint
//     here, threat T-09-15) and a `View stats` shortcut that sets the hash to
//     #/stats (the reserved Phase-12 Stats route).
//   • SECURITY (MINIMAL) — static reassurance copy, no interactive controls.
//   • NEED HELP? (MINIMAL) — a single static line pointing at the docs.
//
// Security/Need-help are kept visually subordinate to Quick actions (smaller,
// dimmer) per §B. Component CSS uses only var(--*) tokens (no raw hex).
import { h } from "preact";
import htm from "htm";

const html = htm.bind(h);

// View stats: navigate to the reserved Stats route via the hash router.
// Setting location.hash fires "hashchange" -> useHashRoute re-renders; no full
// page load, no server hit.
function onViewStats() {
  window.location.hash = "#/stats";
}

// Props: { onCreateKey } — the Dashboard-owned opener (threaded through app.js's
// AuthedShell). `Create key` calls it to open the create modal; the sidebar
// itself calls NO /keys endpoint (threat T-09-15: no key material here).
export function RightSidebar({ onCreateKey }) {
  return html`
    <aside class="sidebar">
      <div class="panel panel-primary">
        <div class="panel-label">QUICK ACTIONS</div>
        <button class="panel-action panel-action-primary" type="button" onClick=${onCreateKey}>
          Create key
        </button>
        <button class="panel-action" type="button" onClick=${onViewStats}>
          View stats
        </button>
      </div>

      <div class="panel panel-minimal">
        <div class="panel-label">SECURITY</div>
        <p class="panel-body">
          Keys are shown once. Store them securely. Rotate any compromised key from the table.
        </p>
      </div>

      <div class="panel panel-minimal">
        <div class="panel-label">NEED HELP?</div>
        <p class="panel-body">See the endpoint reference and docs.</p>
      </div>
    </aside>
  `;
}
