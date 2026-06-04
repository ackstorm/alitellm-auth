// keys.ts — pure row-selection + status-computation for the /keys data table.
//
// Ported verbatim (semantics) from src/ui/keys-table.js. These three functions
// are PURE — no DOM, no I/O — so the populated-vs-empty render gate and the
// status pills are unit-testable without a component renderer (no jsdom dep).

import type { KeyRow } from './api-types';

// A key is "Revoked" when an explicit revoked/blocked flag is truthy. The
// projected /keys shape carries no positive "active" field, so absence == active
// (UI-SPEC §C4 "Active … when not revoked").
export function isRevoked(key: KeyRow | null | undefined): boolean {
  return Boolean(key && (key.revoked || key.blocked));
}

// D-08: a key is "Expired" when its expiry is in the past — computed from the
// projected `expires` field. This does NOT consider revoked; revoked-precedence
// (a revoked key reads `Revoked`, never `Expired`) is the CALLER's concern via
// `!isRevoked(k) && isExpired(k)`.
export function isExpired(key: KeyRow | null | undefined): boolean {
  if (!key || key.expires == null) return false;
  const ts = Date.parse(key.expires);
  return Number.isFinite(ts) && ts < Date.now();
}

// FID-04 (D-15) guard — the PURE row-selection gate the keys table uses to
// decide whether to render populated rows or the empty/loading/error state.
// Returns the SAME array reference when given an array (no copy, no mutation),
// and an empty array for anything else (null/undefined/object). Never throws.
export function selectKeyRows(value: unknown): KeyRow[] {
  return Array.isArray(value) ? (value as KeyRow[]) : [];
}
