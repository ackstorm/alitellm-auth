// delete-modal.js — the confirm-before-delete modal (DASH-05).
//
// A leaf component driven by props/callbacks from the Wave 3 dashboard
// container. It re-specs Phase 09's inline push-down confirm into a real
// centered overlay modal (it is NOT the browser confirm dialog), per UI-SPEC
// §7 / D-08.
//
// The modal is OPEN when `keyToDelete` is a non-null key object; closed (renders
// nothing) when it is null. Confirm DELETEs `/api/session/keys/{id}` via the
// `del` write wrapper from api.js (which sends `content-type: application/json`,
// required by the backend write-guard / assert_same_origin).
//
// Backend contract (src/api/app/session.py:session_delete_key):
//   200 { status: "deleted", id }   -> onDeleted(id) so the parent fades the row
//   403                             -> foreign/absent key, NO existence leak (D-12)
//   502                             -> backend failure
// On 403 OR 502 the modal STAYS OPEN and shows the locked in-modal error.
//
// SECURITY:
//   - T-10-10 (XSS): the interpolated {key_id} renders as a Preact text child
//     (htm escapes) — never raw HTML; no dangerouslySetInnerHTML sink.
//   - T-10-13 (EoP): ownership is enforced server-side (403 on a foreign key);
//     this modal only surfaces that as the locked in-modal error.
//   - encodeURIComponent is applied to the id in the URL path (defensive).
import { h } from "preact";
import { useState, useCallback } from "preact/hooks";
import htm from "htm";
import { del } from "./api.js";

const html = htm.bind(h);

const DELETE_ERROR =
  "Couldn't revoke that key. It may already be gone — refresh and try again.";

// ── DeleteModal ───────────────────────────────────────────────────────────────
// Props:
//   keyToDelete — the key object (with `.id`) or null. Modal is open iff non-null.
//   onClose     — () => void; called by Keep Key (border-only dismiss).
//   onDeleted   — (id) => void; called on a 200 so the parent fades/collapses the
//                 row (<=0.3s) and re-fetches /keys.
export function DeleteModal({ keyToDelete, onClose, onDeleted }) {
  const [error, setError] = useState(null);
  const [deleting, setDeleting] = useState(false);

  const onConfirm = useCallback(async () => {
    if (deleting || !keyToDelete) return;
    setError(null);
    setDeleting(true);
    const { status } = await del(
      "/api/session/keys/" + encodeURIComponent(keyToDelete.id)
    );
    setDeleting(false);

    if (status === 200) {
      onDeleted && onDeleted(keyToDelete.id);
      return;
    }
    // 403 (foreign/absent, D-12) or 502 (backend) — keep the modal OPEN.
    setError(DELETE_ERROR);
  }, [keyToDelete, deleting, onDeleted]);

  // Reset transient state then bubble the dismiss up to the parent.
  const handleClose = useCallback(() => {
    setError(null);
    onClose && onClose();
  }, [onClose]);

  // Modal is open only when a key is targeted.
  if (!keyToDelete) return null;

  return html`
    <div class="dm-overlay" role="dialog" aria-modal="true" aria-label="Revoke key">
      <div class="dm-modal">
        <div class="dm-header">
          <div class="dm-title">Revoke Key</div>
        </div>
        <div class="dm-body">
          <div class="dm-text">
            This will permanently revoke ${keyToDelete.id}. This cannot be undone.
          </div>
          ${error ? html`<div class="dm-error">${error}</div>` : null}
        </div>
        <div class="dm-actions">
          <button
            type="button"
            class="dm-keep"
            onClick=${handleClose}
            disabled=${deleting}
          >
            Keep Key
          </button>
          <button
            type="button"
            class="btn retry"
            onClick=${onConfirm}
            disabled=${deleting}
          >
            Confirm Revoke
          </button>
        </div>
      </div>
    </div>
  `;
}

// ── Component stylesheet — var(--*) tokens only ───────────────────────────────
// Reuses the destructive `.btn.retry` CTA (app.js SHELL_CSS) and the
// .card/.panel surface shape (base.css). Only the modal-overlay + confirm-detail
// styles live here. Open animation: short fade/scale-in (<=0.2s).
export const DELETE_MODAL_CSS = `
.dm-overlay {
  position: fixed; inset: 0; z-index: 100;
  display: flex; align-items: center; justify-content: center;
  padding: var(--space-lg);
  background: rgba(0, 0, 0, 0.6);
}
.dm-modal {
  width: 100%; max-width: 420px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  box-shadow: 0 0 80px -20px var(--glow2-err);
  animation: dmScaleIn .18s ease-out;
}
@keyframes dmScaleIn {
  from { opacity: 0; transform: scale(.97); }
  to   { opacity: 1; transform: scale(1); }
}
.dm-header { padding: var(--space-lg) var(--space-lg) 0; }
.dm-title { font-family: var(--sans); font-size: 24px; font-weight: 600; color: var(--bright); }
.dm-body { padding: var(--space-lg); display: flex; flex-direction: column; gap: var(--space-md); }
.dm-text { font-family: var(--sans); font-size: 14px; color: var(--text); line-height: 1.5; word-break: break-word; }
.dm-error { font-family: var(--sans); font-size: 12px; color: var(--destructive); line-height: 1.5; }

.dm-actions {
  display: flex; align-items: center; justify-content: flex-end; gap: var(--space-md);
  padding: 0 var(--space-lg) var(--space-lg);
}
.dm-keep {
  font-family: var(--mono); font-size: 13px; font-weight: 600;
  text-transform: lowercase; letter-spacing: .5px; color: var(--text);
  background: transparent; border: 1px solid var(--border); border-radius: 8px;
  padding: 12px 20px; cursor: pointer;
  transition: border-color .15s, color .15s;
}
.dm-keep:hover { border-color: var(--text); color: var(--bright); }
.dm-keep:disabled, .btn.retry:disabled { opacity: .6; cursor: not-allowed; }
`;
