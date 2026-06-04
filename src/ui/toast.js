// toast.js — the "Coming soon" feedback toast for the #/stats Usage & Spend page.
//
// CONTEXT D-13 / STATS-11 / 13-UI-SPEC §10: every mock control on the page
// (Export CSV, PDF, Team/Env filters, spend-alert edit, billing link, Insights,
// the disabled left-rail glyphs) is a NON-FUNCTIONAL placeholder. Interacting
// with one shows THIS toast and nothing else.
//
// NO-OP INVARIANT (threat T-13-04, Information Disclosure):
//   The toast performs NO network request (no HTTP client referenced anywhere
//   here) and NO state change beyond its own visibility. It renders no contract
//   values and touches no key material — it is feedback ONLY. This invariant is
//   asserted by the plan's acceptance criteria (the HTTP-client name must not
//   appear in this module).
//
// The timer hook adapts clipboard.js `useCopyFeedback` (clipboard.js:31-44)
// structurally: `show()` flips `visible` true then clears it after a fixed
// timeout. Position is bottom-center, --surface + 1px --border + 16px radius,
// 14px body, fade in/out, auto-dismiss after 2500ms (UI-SPEC §10).
//
// Module shape: `useToast` hook + `Toast` component + `TOAST_CSS` string, so
// app.js's `injectShellStyles` (wired in 13-05) can concatenate the CSS. CSS
// uses ONLY var(--*) tokens / allowed rgba(...) — never a raw hex.
import { h } from "preact";
import { useState, useRef, useCallback, useEffect } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);

// The locked single-line copy (13-UI-SPEC §Copywriting Contract).
const TOAST_COPY = "Coming soon";

// Auto-dismiss duration (13-UI-SPEC §10 — 2500ms).
const TOAST_DURATION_MS = 2500;

// useToast() -> { visible, show }. `show()` sets `visible = true` then clears it
// after exactly TOAST_DURATION_MS via setTimeout (the clipboard.js feedback
// pattern). Re-calling `show()` while visible restarts the timer so a rapid
// double-click does not leave the toast hanging or dismiss early. The pending
// timer is cleared on unmount. This hook performs NO network call and NO state
// change beyond `visible` (D-13 no-op invariant).
export function useToast() {
  const [visible, setVisible] = useState(false);
  const timerRef = useRef(null);

  const clear = useCallback(() => {
    if (timerRef.current !== null) {
      clearTimeout(timerRef.current);
      timerRef.current = null;
    }
  }, []);

  const show = useCallback(() => {
    clear();
    setVisible(true);
    timerRef.current = setTimeout(() => {
      timerRef.current = null;
      setVisible(false);
    }, TOAST_DURATION_MS);
  }, [clear]);

  // Clear any pending timer on unmount so a dismiss never fires on a gone tree.
  useEffect(() => clear, [clear]);

  return { visible, show };
}

// Toast({ visible }) -> the bottom-center "Coming soon" pill, or null when
// hidden. Renders the locked copy as a Preact text child (auto-escaped, though
// the string is a constant) — no contract values, no innerHTML, no network.
export function Toast({ visible }) {
  if (!visible) return null;
  return html`
    <div class="toast" role="status" aria-live="polite">
      <div class="toast-body">${TOAST_COPY}</div>
    </div>
  `;
}

// ── Component stylesheet — var(--*) tokens only ───────────────────────────────
// Bottom-center, --surface + 1px --border + 16px radius, 14px body, fade in.
// Reuses the inherited slideUp-style entrance feel via a local fade. NO raw hex
// — the decorative shadow uses an rgba(...) literal (allowed, matches base.css).
export const TOAST_CSS = `
@keyframes toastFade {
  from { opacity: 0; transform: translate(-50%, 8px); }
  to   { opacity: 1; transform: translate(-50%, 0); }
}
.toast {
  position: fixed;
  left: 50%;
  bottom: var(--space-2xl);
  transform: translate(-50%, 0);
  z-index: 1000;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  padding: var(--space-md) var(--space-lg);
  box-shadow: 0 8px 32px -8px rgba(0, 0, 0, 0.6);
  animation: toastFade .2s ease-out;
  pointer-events: none;
}
.toast .toast-body {
  font-family: var(--sans);
  font-size: 14px;
  font-weight: 400;
  color: var(--text);
  line-height: 1.5;
  white-space: nowrap;
}
`;
