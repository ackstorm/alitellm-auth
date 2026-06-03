// sidebar.js — the authenticated shell's RIGHT SIDEBAR (Preact + htm, no JSX).
//
// Three panels per 09-UI-SPEC §B "Right sidebar panels (D-08 scope)" + §E
// "Sidebar" locked copy:
//   • QUICK ACTIONS (PRIMARY) — a `Create key` shortcut (Phase-9 NO-OP stub;
//     Phase 10 wires it to the create form/modal — it calls NO /keys endpoint
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

// Create key: Phase-9 stub. Phase 10 wires this to the create form/modal.
// Intentionally a documented no-op — it must NOT call any /keys endpoint this
// phase (Phase 10 boundary; threat T-09-15: no key material here).
function onCreateKey() {
  // TODO(Phase 10): open the create-key form/modal (+ New Key flow).
}

// View stats: navigate to the reserved Stats route via the hash router.
// Setting location.hash fires "hashchange" -> useHashRoute re-renders; no full
// page load, no server hit.
function onViewStats() {
  window.location.hash = "#/stats";
}

export function RightSidebar() {
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
