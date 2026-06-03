// create-key.js — the `+ New Key` create form/modal (DASH-04).
//
// A leaf component driven by props/callbacks from the Wave 3 dashboard
// container. When `open`, it renders a centered overlay modal with two OPTIONAL
// fields (name -> alias, expires -> duration) that thread into
// `POST /api/session/keys {alias?, duration?}` via the `postJson` write wrapper
// from api.js (which sends `content-type: application/json`, required by the
// backend write-guard / assert_same_origin).
//
// Client-side validation MIRRORS src/api/app/session.py:session_create_key so
// users see the locked validation messages without a round-trip:
//   - alias: 1-128 chars, every char `c.isalnum() || "-_.".includes(c)`
//   - duration: regex /^\d+[dhms]$/
// A server 422 maps back to the same per-field messages.
//
// SECURITY (threat T-10-09, Information Disclosure):
//   - On 200 the returned full `sk-` is shown ONCE in a --glow chip with the
//     locked shown-once warning + a copy button, then handed UP to the parent
//     via `onCreated({ id, key })` for the in-memory fresh-key map ONLY.
//   - The sk- is NEVER written to any browser Storage and NEVER logged
//     (no Storage writes / no logging calls anywhere in this module).
//   - All field values + the returned key render as Preact text children
//     (htm escapes); there is no dangerouslySetInnerHTML sink (T-10-10 XSS).
import { h } from "preact";
import { useState, useCallback } from "preact/hooks";
import htm from "htm";
import { postJson } from "./api.js";
import { useCopyFeedback } from "./clipboard.js";

const html = htm.bind(h);

// ── Validation parity with session.py (mirrored client-side) ──────────────────
// alias safe chars: alphanumeric, dash, underscore, dot — session.py uses
// `c.isalnum() or c in "-_."`. JS has no isalnum(); `/^[\p{L}\p{N}\-_.]+$/u`
// covers the same alphanumeric-plus-three-symbols set with full Unicode letters
// and numbers (Python str.isalnum() is also Unicode-aware).
const ALIAS_RE = /^[\p{L}\p{N}\-_.]+$/u;
// duration: number followed by one of d/h/m/s — session.py regex ^\d+[dhms]$.
const DURATION_RE = /^\d+[dhms]$/;

const ALIAS_ERROR =
  "Name may only contain letters, numbers, dash, underscore, dot (max 128).";
const DURATION_ERROR = "Expiry must look like 90d, 24h, or 30m.";
const CREATE_502_ERROR = "Couldn't create the key. Try again in a moment.";
const SHOWN_ONCE_WARNING =
  "This key is shown once. Copy and store it now — you won't see it again.";

// Validate a trimmed alias against the session.py rules. Returns an error string
// or null. Empty alias is allowed (the field is optional — empty => omitted).
function validateAlias(value) {
  if (value === "") return null; // optional
  if (value.length > 128 || !ALIAS_RE.test(value)) return ALIAS_ERROR;
  return null;
}

// Validate a trimmed duration. Empty is allowed (no expiry). Otherwise it must
// match the LiteLLM duration shape mirrored from session.py.
function validateDuration(value) {
  if (value === "") return null; // optional — no expiry
  if (!DURATION_RE.test(value)) return DURATION_ERROR;
  return null;
}

// ── CreateKeyModal ────────────────────────────────────────────────────────────
// Props:
//   open       — boolean; when false the component renders nothing.
//   onClose    — () => void; called by Cancel (and after dismissing the result).
//   onCreated  — ({ id, key }) => void; called once on a 200 so the parent
//                records the fresh full sk- in memory and re-fetches /keys.
export function CreateKeyModal({ open, onClose, onCreated }) {
  const [alias, setAlias] = useState("");
  const [duration, setDuration] = useState("");
  const [aliasError, setAliasError] = useState(null);
  const [durationError, setDurationError] = useState(null);
  const [formError, setFormError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  // `result` holds the shown-once response { id, key } after a 200, switching the
  // modal from the form view to the shown-once key view. Kept in component state
  // only — never persisted (T-10-09).
  const [result, setResult] = useState(null);
  const { copied, copy } = useCopyFeedback();

  const onSubmit = useCallback(
    async (e) => {
      e.preventDefault();
      if (submitting) return;
      setFormError(null);

      const aliasValue = alias.trim();
      const durationValue = duration.trim();

      // Mirror session.py validation BEFORE the fetch so the locked field
      // messages surface without a round-trip.
      const aErr = validateAlias(aliasValue);
      const dErr = validateDuration(durationValue);
      setAliasError(aErr);
      setDurationError(dErr);
      if (aErr || dErr) return;

      // Body omits empty fields — an empty body is valid (session.py defaults).
      const body = {};
      if (aliasValue) body.alias = aliasValue;
      if (durationValue) body.duration = durationValue;

      setSubmitting(true);
      const { status, data } = await postJson("/api/session/keys", body);
      setSubmitting(false);

      if (status === 200 && data && data.key) {
        // Show the full sk- ONCE; hand it up to the parent fresh-key map.
        setResult({ id: data.id, key: data.key });
        onCreated && onCreated({ id: data.id, key: data.key });
        return;
      }
      if (status === 422) {
        // Map a server-side validation rejection back to the field messages.
        // The backend validates alias before duration; surface both defensively.
        setAliasError(validateAlias(aliasValue) || ALIAS_ERROR);
        setDurationError(validateDuration(durationValue));
        return;
      }
      // 502 (or any other non-200): in-form error, form stays open.
      setFormError(CREATE_502_ERROR);
    },
    [alias, duration, submitting, onCreated]
  );

  // Reset transient state then bubble the close up to the parent.
  const handleClose = useCallback(() => {
    setAlias("");
    setDuration("");
    setAliasError(null);
    setDurationError(null);
    setFormError(null);
    setResult(null);
    onClose && onClose();
  }, [onClose]);

  if (!open) return null;

  // ── Shown-once result view ──────────────────────────────────────────────────
  if (result) {
    return html`
      <div class="ck-overlay" role="dialog" aria-modal="true" aria-label="New key">
        <div class="ck-modal">
          <div class="ck-header">
            <div class="ck-title">Key created</div>
          </div>
          <div class="ck-body">
            <div class="ck-shown-once">${SHOWN_ONCE_WARNING}</div>
            <div class="ck-key-chip">${result.key}</div>
            <button
              type="button"
              class="ck-copy"
              onClick=${() => copy(result.key)}
            >
              ${copied ? html`<span class="ck-copied">copied!</span>` : "copy"}
            </button>
          </div>
          <div class="ck-actions">
            <button type="button" class="btn" onClick=${handleClose}>done</button>
          </div>
        </div>
      </div>
    `;
  }

  // ── Form view ───────────────────────────────────────────────────────────────
  return html`
    <div class="ck-overlay" role="dialog" aria-modal="true" aria-label="Create key">
      <form class="ck-modal" onSubmit=${onSubmit}>
        <div class="ck-header">
          <div class="ck-title">Create Key</div>
        </div>
        <div class="ck-body">
          <div class="ck-field">
            <label class="ck-label" for="ck-name">name</label>
            <input
              id="ck-name"
              class="ck-input"
              type="text"
              placeholder="key-YYYY-MM-DD"
              value=${alias}
              onInput=${(e) => setAlias(e.target.value)}
              disabled=${submitting}
            />
            <div class="ck-helper">
              Letters, numbers, dash, underscore, dot. Up to 128 characters.
            </div>
            ${aliasError
              ? html`<div class="ck-field-error">${aliasError}</div>`
              : null}
          </div>

          <div class="ck-field">
            <label class="ck-label" for="ck-expires">expires</label>
            <input
              id="ck-expires"
              class="ck-input"
              type="text"
              placeholder="no expiry"
              value=${duration}
              onInput=${(e) => setDuration(e.target.value)}
              disabled=${submitting}
            />
            <div class="ck-helper">
              Leave blank for no expiry. Format: 90d, 24h, 30m.
            </div>
            ${durationError
              ? html`<div class="ck-field-error">${durationError}</div>`
              : null}
          </div>

          ${formError
            ? html`<div class="ck-form-error">${formError}</div>`
            : null}
        </div>
        <div class="ck-actions">
          <button
            type="button"
            class="ck-cancel"
            onClick=${handleClose}
            disabled=${submitting}
          >
            Cancel
          </button>
          <button class="btn" type="submit" disabled=${submitting}>
            Create Key
          </button>
        </div>
      </form>
    </div>
  `;
}

// ── Component stylesheet — var(--*) tokens only ───────────────────────────────
// Reuses the .btn accent CTA (app.js SHELL_CSS) and the .card/.panel surface
// shape (base.css). Only the modal-overlay + form-detail styles live here.
export const CREATE_KEY_CSS = `
.ck-overlay {
  position: fixed; inset: 0; z-index: 100;
  display: flex; align-items: center; justify-content: center;
  padding: var(--space-lg);
  background: rgba(0, 0, 0, 0.6);
}
.ck-modal {
  width: 100%; max-width: 440px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  box-shadow: 0 0 80px -20px var(--glow2);
  animation: ckScaleIn .18s ease-out;
}
@keyframes ckScaleIn {
  from { opacity: 0; transform: scale(.97); }
  to   { opacity: 1; transform: scale(1); }
}
.ck-header { padding: var(--space-lg) var(--space-lg) 0; }
.ck-title { font-family: var(--sans); font-size: 24px; font-weight: 600; color: var(--bright); }
.ck-body { padding: var(--space-lg); display: flex; flex-direction: column; gap: var(--space-lg); }

.ck-field { display: flex; flex-direction: column; gap: var(--space-xs); }
.ck-label {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 1px; color: var(--dim);
}
.ck-input {
  font-family: var(--mono); font-size: 12px; color: var(--text);
  background: var(--bg); border: 1px solid var(--border); border-radius: 8px;
  padding: 10px var(--space-md); outline: none;
  transition: border-color .15s;
}
.ck-input:focus { border-color: var(--accent); }
.ck-input::placeholder { color: var(--dim); }
.ck-helper { font-family: var(--sans); font-size: 12px; color: var(--dim); }
.ck-field-error { font-family: var(--sans); font-size: 12px; color: var(--destructive); }
.ck-form-error { font-family: var(--sans); font-size: 12px; color: var(--destructive); }

/* Shown-once result chip — reuses the success.html .key-val accent treatment. */
.ck-shown-once { font-family: var(--sans); font-size: 12px; color: var(--accent); line-height: 1.5; }
.ck-key-chip {
  font-family: var(--mono); font-size: 12px; word-break: break-all;
  color: var(--accent); background: var(--glow);
  border: 1px solid var(--border); border-radius: 4px;
  padding: var(--space-md);
}
.ck-copy {
  align-self: flex-start;
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: lowercase; color: var(--accent);
  background: transparent; border: 1px solid var(--border); border-radius: 8px;
  padding: 6px var(--space-md); cursor: pointer;
  transition: border-color .15s, color .15s;
}
.ck-copy:hover { border-color: var(--accent); }
.ck-copied { color: var(--accent); }

.ck-actions {
  display: flex; align-items: center; justify-content: flex-end; gap: var(--space-md);
  padding: 0 var(--space-lg) var(--space-lg);
}
.ck-cancel {
  font-family: var(--mono); font-size: 13px; font-weight: 600;
  text-transform: lowercase; letter-spacing: .5px; color: var(--text);
  background: transparent; border: 1px solid var(--border); border-radius: 8px;
  padding: 12px 20px; cursor: pointer;
  transition: border-color .15s, color .15s;
}
.ck-cancel:hover { border-color: var(--accent); color: var(--bright); }
.ck-cancel:disabled, .ck-input:disabled, .btn:disabled { opacity: .6; cursor: not-allowed; }
`;
