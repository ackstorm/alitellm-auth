// date-range.js — the date-range control cluster for the #/stats Usage & Spend
// page (STATS-09 / UI-SPEC §1). Preact + htm tagged templates, no JSX, no
// TypeScript (inherited 13-CONTEXT D-04).
//
// Three controls, top-right of the page header band (per the mockup):
//   • Preset buttons (PRESETS from stats-presets.js): 7d / 30d / 90d /
//     This month / Last month / This year / Custom. The active preset is
//     accent-tinted (the topbar `a.active` / `.panel-action` idiom, app.js:130,
//     app.js:151-162); a click calls onPreset(presetId) and the 13-05 container
//     computes {start,end} via presetToRange (every preset respects the ~366d
//     cap in the pure helper, D-10) and re-queries /stats.
//   • Custom — opens a HAND-BUILT dark-terminal calendar popover reusing the
//     create-key.js `.ck-overlay`/`.ck-modal` shell shape (create-key.js:246-263).
//     The day-grid + month-nav are hand-rolled over the token set (D-11 — NO
//     native date inputs, no heavy dep) with Apply/Cancel; Apply calls
//     onCustomRange({start,end}). The server still re-validates (422 over-cap /
//     bad range), surfaced as the inline `rangeError`.
//   • Compare — a CLIENT-ONLY boolean toggle calling onToggleCompare. It
//     shows/hides the KPI delta chips over the SERVER-computed deltas — NO fetch,
//     NO backend change (D-12). This module references no HTTP client at all.
//
// SECURITY (threat register 13-04):
//   • T-13-09 (Tampering): presetToRange (the pure helper, called by the
//     container) clamps to the ~366d cap so the client never submits an over-cap
//     range; the server re-validates (422), surfaced as the inline rangeError.
//   • T-13-11 (Spoofing — ACCEPTED): Compare is client-only show/hide over
//     server-computed deltas; no fetch, no trust boundary crossed.
import { h } from "preact";
import { useState } from "preact/hooks";
import htm from "htm";
import { PRESETS } from "./stats-presets.js";

const html = htm.bind(h);

// Locked copy (13-UI-SPEC §Copywriting Contract / §1).
const COMPARE_LABEL = "Compare";
const APPLY_LABEL = "Apply";
const CANCEL_LABEL = "Cancel";
const CUSTOM_PRESET = "Custom";

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];
const WEEKDAY_LABELS = ["S", "M", "T", "W", "T", "F", "S"];

// Format a UTC Date as "YYYY-MM-DD" (tz-stable, mirrors stats-presets.js).
function toUTCDateString(d) {
  const year = d.getUTCFullYear();
  const month = String(d.getUTCMonth() + 1).padStart(2, "0");
  const day = String(d.getUTCDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

// The current UTC month/year as {year, month} for the calendar's initial view.
function currentMonth() {
  const now = new Date();
  return { year: now.getUTCFullYear(), month: now.getUTCMonth() };
}

// Build the day grid for a given UTC month: a leading run of nulls for the
// weekday offset, then 1..daysInMonth. Pure, deterministic on {year, month}.
function buildMonthGrid(year, month) {
  const firstWeekday = new Date(Date.UTC(year, month, 1)).getUTCDay();
  const daysInMonth = new Date(Date.UTC(year, month + 1, 0)).getUTCDate();
  const cells = [];
  for (let i = 0; i < firstWeekday; i++) cells.push(null);
  for (let d = 1; d <= daysInMonth; d++) cells.push(d);
  return cells;
}

// ── CalendarPopover ──────────────────────────────────────────────────────────
// A hand-built two-click range picker (D-11 — no native date input). The user
// clicks a start day then an end day; Apply emits {start, end} as YYYY-MM-DD
// strings (start <= end normalized). Cancel dismisses with no emit.
function CalendarPopover({ onApply, onCancel }) {
  const init = currentMonth();
  const [view, setView] = useState(init);
  const [startDate, setStartDate] = useState(null); // UTC Date or null
  const [endDate, setEndDate] = useState(null);     // UTC Date or null

  const cells = buildMonthGrid(view.year, view.month);

  const prevMonth = () => {
    const m = view.month - 1;
    setView(m < 0 ? { year: view.year - 1, month: 11 } : { year: view.year, month: m });
  };
  const nextMonth = () => {
    const m = view.month + 1;
    setView(m > 11 ? { year: view.year + 1, month: 0 } : { year: view.year, month: m });
  };

  const pickDay = (day) => {
    if (day == null) return;
    const picked = new Date(Date.UTC(view.year, view.month, day));
    // First pick (or restarting after a complete range) sets the start.
    if (startDate === null || endDate !== null) {
      setStartDate(picked);
      setEndDate(null);
      return;
    }
    // Second pick sets the end; normalize so start <= end.
    if (picked.getTime() < startDate.getTime()) {
      setEndDate(startDate);
      setStartDate(picked);
    } else {
      setEndDate(picked);
    }
  };

  // A day is "in range" (start..end inclusive) or one of the two endpoints.
  const dayState = (day) => {
    if (day == null) return "";
    const t = Date.UTC(view.year, view.month, day);
    const s = startDate ? startDate.getTime() : null;
    const e = endDate ? endDate.getTime() : null;
    if (s !== null && t === s) return "is-start";
    if (e !== null && t === e) return "is-end";
    if (s !== null && e !== null && t > s && t < e) return "is-inrange";
    return "";
  };

  const canApply = startDate !== null;
  const apply = () => {
    if (!canApply) return;
    // A single-day pick (no end) collapses to a one-day range start==end.
    const end = endDate || startDate;
    onApply({ start: toUTCDateString(startDate), end: toUTCDateString(end) });
  };

  return html`
    <div class="dr-overlay" onClick=${onCancel}>
      <div class="dr-modal" onClick=${(e) => e.stopPropagation()}>
        <div class="dr-cal-head">
          <button type="button" class="dr-cal-nav" onClick=${prevMonth} aria-label="Previous month">‹</button>
          <span class="dr-cal-title">${MONTH_NAMES[view.month]} ${view.year}</span>
          <button type="button" class="dr-cal-nav" onClick=${nextMonth} aria-label="Next month">›</button>
        </div>
        <div class="dr-cal-grid">
          ${WEEKDAY_LABELS.map(
            (w, i) => html`<span key=${"wd" + i} class="dr-cal-weekday">${w}</span>`,
          )}
          ${cells.map(
            (day, i) => html`<button
              key=${"d" + i}
              type="button"
              class="dr-cal-day ${day == null ? "is-empty" : ""} ${dayState(day)}"
              disabled=${day == null}
              onClick=${() => pickDay(day)}
            >${day == null ? "" : day}</button>`,
          )}
        </div>
        <div class="dr-cal-actions">
          <button type="button" class="dr-btn dr-btn-ghost" onClick=${onCancel}>${CANCEL_LABEL}</button>
          <button type="button" class="dr-btn dr-btn-primary" disabled=${!canApply} onClick=${apply}>${APPLY_LABEL}</button>
        </div>
      </div>
    </div>
  `;
}

// ── DateRange ────────────────────────────────────────────────────────────────
// Props:
//   preset          : the active preset id (one of PRESETS) — accent-tinted.
//   compareOn       : the client-only Compare boolean.
//   onPreset        : (presetId) => void — a preset button click. The container
//                     computes the range via presetToRange and re-queries.
//   onCustomRange   : ({start, end}) => void — the calendar Apply emit.
//   onToggleCompare : () => void — the client-only Compare toggle (NO fetch).
//   rangeError      : optional inline error string (server 422 over-cap / bad
//                     range) — surfaced ON the control, NOT a whole-page error.
export function DateRange({
  preset,
  compareOn,
  onPreset,
  onCustomRange,
  onToggleCompare,
  rangeError,
}) {
  const [calOpen, setCalOpen] = useState(false);

  const clickPreset = (p) => {
    if (p === CUSTOM_PRESET) {
      setCalOpen(true);
      if (typeof onPreset === "function") onPreset(p);
      return;
    }
    setCalOpen(false);
    if (typeof onPreset === "function") onPreset(p);
  };

  const applyCustom = (range) => {
    setCalOpen(false);
    if (typeof onCustomRange === "function") onCustomRange(range);
  };

  return html`
    <div class="date-range">
      <div class="dr-presets">
        ${PRESETS.map(
          (p) => html`<button
            key=${p}
            type="button"
            class="dr-preset ${preset === p ? "is-active" : ""}"
            onClick=${() => clickPreset(p)}
          >${p}</button>`,
        )}
        <button
          type="button"
          class="dr-compare ${compareOn ? "is-on" : ""}"
          aria-pressed=${compareOn ? "true" : "false"}
          onClick=${() => typeof onToggleCompare === "function" && onToggleCompare()}
        >${COMPARE_LABEL}</button>
      </div>
      ${rangeError
        ? html`<div class="dr-error">${rangeError}</div>`
        : null}
      ${calOpen
        ? html`<${CalendarPopover} onApply=${applyCustom} onCancel=${() => setCalOpen(false)} />`
        : null}
    </div>
  `;
}

// ── Component stylesheet — var(--*) tokens only ───────────────────────────────
// Preset buttons reuse the `.panel-action` / topbar `a.active` accent-active
// idiom (app.js:130,151-162); the calendar popover reuses the create-key.js
// `.ck-overlay`/`.ck-modal` shell shape (create-key.js:246-263). NEVER a raw hex
// — var(--*) only (the overlay scrim rgba(...) matches create-key.js, allowed).
// Concatenated into app.js's injectShellStyles (wired in 13-05).
export const DATE_RANGE_CSS = `
.date-range { display: flex; flex-direction: column; align-items: flex-end; gap: var(--space-sm); position: relative; }
.dr-presets { display: flex; flex-wrap: wrap; align-items: center; gap: var(--space-sm); }

/* Preset buttons — caption-role 11px mono; inactive --dim/border, active
 * accent-tinted (the topbar a.active treatment). */
.dr-preset, .dr-compare {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: .5px;
  color: var(--dim); background: transparent;
  border: 1px solid var(--border); border-radius: 8px;
  padding: var(--space-xs) var(--space-md); cursor: pointer; min-height: 32px;
  transition: color .15s, border-color .15s, background .15s;
}
.dr-preset:hover, .dr-compare:hover { color: var(--text); border-color: var(--dim); }
.dr-preset.is-active {
  color: var(--accent); background: var(--glow); border-color: var(--accent);
}

/* Compare — a client-only toggle; the "on" state is accent-tinted. */
.dr-compare.is-on { color: var(--accent); background: var(--glow); border-color: var(--accent); }

/* Inline server-range error (NOT a whole-page error). */
.dr-error { font-family: var(--sans); font-size: 12px; color: var(--destructive); text-align: right; }

/* ── Calendar popover — the create-key.js modal shell shape (create-key.js:246) ─ */
.dr-overlay {
  position: fixed; inset: 0; z-index: 100;
  display: flex; align-items: center; justify-content: center;
  padding: var(--space-lg);
  background: rgba(0, 0, 0, 0.6);
}
.dr-modal {
  width: 100%; max-width: 320px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 16px;
  box-shadow: 0 0 80px -20px var(--glow2);
  padding: var(--space-lg);
  display: flex; flex-direction: column; gap: var(--space-md);
}

.dr-cal-head { display: flex; align-items: center; justify-content: space-between; }
.dr-cal-title { font-family: var(--mono); font-size: 12px; font-weight: 600; color: var(--bright); }
.dr-cal-nav {
  font-family: var(--mono); font-size: 14px; color: var(--dim);
  background: transparent; border: 1px solid var(--border); border-radius: 8px;
  width: 28px; height: 28px; cursor: pointer; transition: color .15s, border-color .15s;
}
.dr-cal-nav:hover { color: var(--accent); border-color: var(--accent); }

.dr-cal-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: var(--space-xs); }
.dr-cal-weekday {
  font-family: var(--mono); font-size: 11px; font-weight: 600; color: var(--dim);
  text-align: center; padding: var(--space-xs) 0;
}
.dr-cal-day {
  font-family: var(--mono); font-size: 12px; color: var(--text);
  background: transparent; border: 1px solid transparent; border-radius: 6px;
  aspect-ratio: 1 / 1; min-height: 30px; cursor: pointer;
  transition: color .15s, background .15s, border-color .15s;
}
.dr-cal-day:hover { border-color: var(--accent); color: var(--bright); }
.dr-cal-day.is-empty { cursor: default; }
.dr-cal-day.is-inrange { background: var(--glow); color: var(--accent); }
.dr-cal-day.is-start, .dr-cal-day.is-end {
  background: var(--accent); color: var(--bg); border-color: var(--accent);
}

.dr-cal-actions { display: flex; justify-content: flex-end; gap: var(--space-sm); margin-top: var(--space-xs); }
.dr-btn {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: .5px;
  border-radius: 8px; padding: var(--space-xs) var(--space-md); cursor: pointer; min-height: 32px;
  transition: color .15s, background .15s, border-color .15s;
}
.dr-btn-ghost { color: var(--dim); background: transparent; border: 1px solid var(--border); }
.dr-btn-ghost:hover { color: var(--text); border-color: var(--dim); }
.dr-btn-primary { color: var(--bg); background: var(--accent); border: 1px solid var(--accent); }
.dr-btn-primary:hover { background: var(--accent2); }
.dr-btn-primary:disabled { opacity: .5; cursor: not-allowed; }

/* Touch targets ≥ 44px on mobile (UI-SPEC §9). */
@media (max-width: 768px) {
  .dr-preset, .dr-compare, .dr-btn { min-height: 44px; }
  .dr-cal-day { min-height: 40px; }
}
`;
