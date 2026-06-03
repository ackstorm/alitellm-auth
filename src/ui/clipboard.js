// clipboard.js — copy-to-clipboard helper + a 2s "copied!" feedback hook.
//
// Ports the imperative success.html copyKey() pattern (clipboard.writeText +
// a 2000ms feedback toggle) into a Preact-friendly module reused by the
// endpoint chip, the key-ID copy button, and the fresh-key copy button.
//
// SECURITY (threat T-10-01, Information Disclosure):
//   - copyText writes ONLY the caller-supplied string, on an explicit user
//     gesture — there is no auto-copy.
//   - the clipboard value is NEVER logged (no logging calls anywhere here).
//   - copyText never throws — a denied/unavailable clipboard resolves false so
//     the caller can fall back silently.
import { useState } from "preact/hooks";

// copyText(text) -> Promise<boolean>. Writes `text` to the clipboard on an
// explicit user action; resolves true on success, false on any failure
// (clipboard API unavailable, permission denied). Never throws, never logs.
export async function copyText(text) {
  try {
    if (!navigator?.clipboard?.writeText) return false;
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

// useCopyFeedback() -> { copied, copy }. `copy(text)` awaits copyText then, on
// success, sets `copied = true` and clears it after exactly 2000ms (the
// success.html 2s feedback pattern). On failure `copied` stays false.
export function useCopyFeedback() {
  const [copied, setCopied] = useState(false);

  async function copy(text) {
    const ok = await copyText(text);
    if (ok) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
    return ok;
  }

  return { copied, copy };
}
