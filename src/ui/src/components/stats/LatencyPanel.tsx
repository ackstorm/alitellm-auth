// LatencyPanel.tsx — request-latency figures for the #/stats page (new panel).
//
// Sourced from GET /api/session/latency (LiteLLM /spend/logs, fixed 7-day window).
// PURE presentational leaf — no fetch: the container passes the LatencyResponse
// slice + an isError flag and renders one of three states:
//   • unavailable — available === false (scoping unverified / fetch failed) OR isError
//   • empty       — available but no rows in the window
//   • ready       — the p50/p95/p99 headline + TTFT / tok-s sub-line + by-model split
//
// Latency is SUPPLEMENTARY: it never throws the whole page. All figures are
// null-guarded (D-08 null-vs-0) and render an em-dash when absent.

import type { LatencyByModel, LatencyResponse } from '@/lib/api-types';
import { formatInt } from '@/lib/format';

const EM_DASH = '—';

const UNAVAILABLE_COPY = 'Latency data is not available for this deployment.';
const EMPTY_COPY = 'No requests in this range.';

// Format a millisecond figure: <1000 → "812 ms"; else "3.25 s" (2 sig decimals).
function formatMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms)) return EM_DASH;
  if (ms < 1000) return `${Math.round(ms)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

function formatTps(tps: number | null | undefined): string {
  if (tps === null || tps === undefined || !Number.isFinite(tps)) return EM_DASH;
  return `${Math.round(tps)} tok/s`;
}

// One big percentile stat (label above, value below).
function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col gap-0.5">
      <div className="font-mono text-[10px] font-semibold uppercase tracking-wider text-text-secondary">
        {label}
      </div>
      <div className="font-sans text-2xl font-semibold leading-tight text-text-primary tabular-nums">
        {value}
      </div>
    </div>
  );
}

// A calm centered state (unavailable / empty) sized to roughly match the chart body.
function StatePanel({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-40 flex-col items-center justify-center gap-2 text-center">
      <div className="font-sans text-sm text-text-secondary">{children}</div>
    </div>
  );
}

// Cycling pastel highlights for the model-name pills (reference "Top Models" look).
// Fixed dark text so the name stays legible on every pastel in light OR dark theme.
const PILL_COLORS = [
  '#d1fae5', // green
  '#fef3c7', // amber
  '#fed7aa', // orange
  '#e9d5ff', // purple
  '#dbeafe', // blue
  '#fce7f3', // pink
];

// Shared grid template so the header row and the data rows line up column-for-
// column (fixed numeric widths, right-aligned — model name takes the rest).
const MODEL_GRID =
  'grid grid-cols-[1fr_3rem_5rem_3.5rem] items-center gap-3';
const MODEL_HEAD_CELL =
  'font-mono text-[10px] font-semibold uppercase tracking-wider text-text-secondary';

function ModelHeader() {
  return (
    <div className={`${MODEL_GRID} border-b border-border/60 pb-1`}>
      <span className={MODEL_HEAD_CELL}>Model</span>
      <span className={`${MODEL_HEAD_CELL} text-right`}>Req</span>
      <span className={`${MODEL_HEAD_CELL} text-right`}>p95</span>
      <span className={`${MODEL_HEAD_CELL} text-right`}>Err</span>
    </div>
  );
}

function ModelRow({ m, index }: { m: LatencyByModel; index: number }) {
  const errPct =
    m.requests > 0 ? ((m.failed / m.requests) * 100).toFixed(1) : null;
  const stripped = m.model.includes('/')
    ? m.model.slice(m.model.indexOf('/') + 1)
    : m.model;
  const pill = PILL_COLORS[index % PILL_COLORS.length];
  return (
    <li title={m.model} className={`${MODEL_GRID} py-1`}>
      <span
        className="max-w-full truncate justify-self-start rounded px-1.5 py-0.5 font-mono text-xs"
        style={{ backgroundColor: pill, color: '#0f172a' }}
      >
        {stripped}
      </span>
      <span className="text-right font-mono text-xs text-text-secondary tabular-nums">
        {formatInt(m.requests)}
      </span>
      <span className="text-right font-mono text-xs text-text-secondary tabular-nums">
        {formatMs(m.p95_ms)}
      </span>
      <span
        className={`text-right font-mono text-xs tabular-nums ${
          m.failed > 0 ? 'text-destructive' : 'text-text-tertiary'
        }`}
      >
        {errPct === null ? EM_DASH : `${errPct}%`}
      </span>
    </li>
  );
}

export interface LatencyPanelProps {
  data: LatencyResponse | undefined;
  isError: boolean;
}

export function LatencyPanel({
  data,
  isError,
}: LatencyPanelProps): React.ReactElement {
  if (isError || !data || !data.available) {
    return <StatePanel>{UNAVAILABLE_COPY}</StatePanel>;
  }
  if (data.row_count === 0 || !data.latency) {
    return <StatePanel>{EMPTY_COPY}</StatePanel>;
  }

  const l = data.latency;
  return (
    <div className="flex flex-col gap-4">
      {/* p50 / p95 / p99 headline */}
      <div className="grid grid-cols-3 gap-3">
        <Stat label="p50" value={formatMs(l.p50_ms)} />
        <Stat label="p95" value={formatMs(l.p95_ms)} />
        <Stat label="p99" value={formatMs(l.p99_ms)} />
      </div>

      {/* TTFT + throughput sub-line */}
      <div className="flex flex-wrap gap-x-6 gap-y-1 border-t border-border pt-3 font-mono text-xs text-text-secondary">
        <span>
          TTFT p50 <span className="text-text-primary">{formatMs(l.ttft_p50_ms)}</span>
        </span>
        <span>
          TTFT p95 <span className="text-text-primary">{formatMs(l.ttft_p95_ms)}</span>
        </span>
        <span>
          Throughput{' '}
          <span className="text-text-primary">{formatTps(l.tokens_per_sec_p50)}</span>
        </span>
      </div>

      {/* Per-model latency + error split (headed table, aligned columns) */}
      {data.by_model.length > 0 ? (
        <div className="flex flex-col">
          <ModelHeader />
          <ul className="flex flex-col divide-y divide-border/60">
            {data.by_model.map((m, i) => (
              <ModelRow key={m.model} m={m} index={i} />
            ))}
          </ul>
        </div>
      ) : null}

      <div className="font-mono text-[10px] text-text-tertiary">
        {formatInt(data.row_count)} requests
        {data.sampled ? ' · sampled' : ''}
      </div>
    </div>
  );
}
