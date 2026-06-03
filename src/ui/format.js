// format.js — pure display formatters for the alitellm-auth dashboard SPA.
//
// Every function is PURE: no DOM, no globals, no I/O — mirrors the state.js
// discipline so the formatters are unit-testable in the default vitest node
// environment (no jsdom). The locked display strings come from
// 10-UI-SPEC §Typography:
//
//   formatCurrency(1249.5)                       -> "$1,249.50"
//   formatInt(1000000)                           -> "1,000,000"
//   abbreviate(2450000)                          -> "2.45M"
//   formatDate("2026-03-01T10:00:00+00:00")      -> "Mar 01, 2026"
//   maskKey("sk-abcd1234wxyz")                    -> "sk-…wxyz"
//
// EVERY formatter returns the em-dash "—" (U+2014) for null/undefined (and any
// otherwise-unformattable input) and NEVER throws — null cells render as a
// neutral dash, not a crash.

const EM_DASH = "—"; // — (U+2014), the UI-SPEC null/empty placeholder
const ELLIPSIS = "…"; // … (U+2026), the mask ellipsis

// Coerce to a finite number, or null if the input is null/undefined/NaN.
function asNumber(n) {
  if (n === null || n === undefined) return null;
  const num = typeof n === "number" ? n : Number(n);
  return Number.isFinite(num) ? num : null;
}

const _currencyFmt = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const _intFmt = new Intl.NumberFormat("en-US", {
  maximumFractionDigits: 0,
});

// formatCurrency(n) -> "$1,249.50"; null/undefined/non-numeric -> "—".
export function formatCurrency(n) {
  const num = asNumber(n);
  if (num === null) return EM_DASH;
  return _currencyFmt.format(num);
}

// formatInt(n) -> "1,000,000"; null/undefined/non-numeric -> "—".
export function formatInt(n) {
  const num = asNumber(n);
  if (num === null) return EM_DASH;
  return _intFmt.format(num);
}

// abbreviate(n) -> "2.45M" / "1.5K" / "950"; up to 2 decimals, trailing zeros
// trimmed; null/undefined/non-numeric -> "—".
export function abbreviate(n) {
  const num = asNumber(n);
  if (num === null) return EM_DASH;

  const abs = Math.abs(num);
  const units = [
    { value: 1e9, suffix: "B" },
    { value: 1e6, suffix: "M" },
    { value: 1e3, suffix: "K" },
  ];

  for (const { value, suffix } of units) {
    if (abs >= value) {
      const scaled = num / value;
      // Up to 2 decimals, trailing zeros trimmed (2.45M, 1.5K, 2K).
      const trimmed = parseFloat(scaled.toFixed(2));
      return `${trimmed}${suffix}`;
    }
  }
  // Below 1000 — no suffix, integer form.
  return String(parseFloat(num.toFixed(2)));
}

const _MONTHS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

// formatDate(iso) -> "Mar 01, 2026" (3-letter month, zero-padded day, UTC);
// null/undefined/unparseable -> "—". Never throws.
export function formatDate(iso) {
  if (iso === null || iso === undefined) return EM_DASH;
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return EM_DASH;
  // Use UTC parts so the locked literal is stable regardless of host timezone.
  const month = _MONTHS[d.getUTCMonth()];
  const day = String(d.getUTCDate()).padStart(2, "0");
  const year = d.getUTCFullYear();
  return `${month} ${day}, ${year}`;
}

// maskKey(s) -> "<prefix>…last4", preserving the value's REAL prefix
// (e.g. "sk-abcd1234wxyz" -> "sk-…wxyz", "key-abc123" -> "key…c123").
// null/undefined -> "—"; a value too short to mask meaningfully (<= 4 chars)
// is returned verbatim rather than fabricating an "sk-…" prefix (WR-02).
// Never throws.
export function maskKey(s) {
  if (s === null || s === undefined) return EM_DASH;
  const str = String(s);
  if (str.length <= 4) return str; // too short to mask — show as-is, no fake prefix
  return `${str.slice(0, 3)}${ELLIPSIS}${str.slice(-4)}`;
}
