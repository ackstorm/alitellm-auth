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

function ModelRow({ m }: { m: LatencyByModel }) {
  const errPct =
    m.requests > 0 ? ((m.failed / m.requests) * 100).toFixed(1) : null;
  const stripped = m.model.includes('/')
    ? m.model.slice(m.model.indexOf('/') + 1)
    : m.model;
  return (
    <li
      title={m.model}
      className="grid grid-cols-[1fr_auto_auto_auto] items-center gap-3 py-1"
    >
      <span className="truncate font-mono text-xs text-text-primary">
        {stripped}
      </span>
      <span className="font-mono text-xs text-text-secondary tabular-nums">
        {formatInt(m.requests)} req
      </span>
      <span className="font-mono text-xs text-text-secondary tabular-nums">
        p95 {formatMs(m.p95_ms)}
      </span>
      <span
        className={`font-mono text-xs tabular-nums ${
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

      {/* Per-model latency + error split */}
      {data.by_model.length > 0 ? (
        <ul className="flex flex-col divide-y divide-border/60">
          {data.by_model.map((m) => (
            <ModelRow key={m.model} m={m} />
          ))}
        </ul>
      ) : null}

      <div className="font-mono text-[10px] text-text-tertiary">
        {formatInt(data.row_count)} requests
        {data.sampled ? ' · sampled' : ''}
      </div>
    </div>
  );
}
