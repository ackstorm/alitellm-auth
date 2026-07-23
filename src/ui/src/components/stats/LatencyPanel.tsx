// LatencyPanel.tsx — request-latency figures for the #/stats page (new panel).
//
// Sourced from GET /api/session/latency (LiteLLM /spend/logs, fixed 7-day window).
// PURE presentational leaf — no fetch: the container passes the LatencyResponse
// slice + an isError flag and renders one of three states:
//   • unavailable — available === false (scoping unverified / fetch failed) OR isError
//   • empty       — available but no rows in the window
//   • ready       — headline (Throughput · Latency p50 · Error rate · TTFT) + the
//                   per-model split (with its own Lat / p95 columns)
//
// The headline leads with the figures that matter at a glance; the tail
// percentiles (p95) live only in the per-model table.
//
// Latency is SUPPLEMENTARY: it never throws the whole page. All figures are
// null-guarded (D-08 null-vs-0) and render an em-dash when absent.

import type { LatencyByModel, LatencyResponse } from '@/lib/api-types';
import { formatInt } from '@/lib/format';
import { StatTile } from './chart-common';

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

// Failed / total across the outcome buckets (any non-"success" status = failed).
// Null when there are no outcome rows (→ em-dash).
function errorRate(outcomes: LatencyResponse['outcomes']): number | null {
  if (!Array.isArray(outcomes) || outcomes.length === 0) return null;
  let total = 0;
  let failed = 0;
  for (const o of outcomes) {
    const c = Number(o?.count) || 0;
    total += c;
    if (o?.status !== 'success') failed += c;
  }
  return total > 0 ? failed / total : null;
}

function formatPct(fraction: number | null): string {
  if (fraction === null || !Number.isFinite(fraction)) return EM_DASH;
  return `${(fraction * 100).toFixed(1)}%`;
}

// A calm centered state (unavailable / empty) sized to roughly match the chart body.
function StatePanel({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-40 flex-col items-center justify-center gap-2 text-center">
      <div className="font-sans text-sm text-text-secondary">{children}</div>
    </div>
  );
}

// Shared grid template so the header row and the data rows line up column-for-
// column (fixed numeric widths, right-aligned — model name takes the rest).
const MODEL_GRID =
  'grid grid-cols-[1fr_2.75rem_4rem_4rem_3.25rem] items-center gap-2';
const MODEL_HEAD_CELL =
  'font-mono text-[10px] font-semibold uppercase tracking-wider text-text-secondary';

function ModelHeader() {
  return (
    <div className={`${MODEL_GRID} border-b border-border/60 pb-1`}>
      <span className={MODEL_HEAD_CELL}>Model</span>
      <span className={`${MODEL_HEAD_CELL} text-right`}>Req</span>
      <span className={`${MODEL_HEAD_CELL} text-right`}>Lat</span>
      <span className={`${MODEL_HEAD_CELL} text-right`}>p95</span>
      <span className={`${MODEL_HEAD_CELL} text-right`}>Err</span>
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
    <li title={m.model} className={`${MODEL_GRID} py-1`}>
      <span className="max-w-full truncate justify-self-start font-mono text-xs text-text-primary">
        {stripped}
      </span>
      <span className="text-right font-mono text-xs text-text-secondary tabular-nums">
        {formatInt(m.requests)}
      </span>
      <span className="text-right font-mono text-xs text-text-secondary tabular-nums">
        {formatMs(m.p50_ms)}
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
  const err = errorRate(data.outcomes);
  return (
    <div className="flex flex-col gap-4">
      {/* Headline: the at-a-glance figures — throughput, typical latency, error
          rate, TTFT. (Request volume lives in the Request Outcomes panel; the tail
          percentiles are demoted to the per-model table's p95 column.) */}
      <div className="flex flex-wrap justify-between gap-3">
        <StatTile
          label="THROUGHPUT"
          title="Output tokens per second (p50)"
          value={formatTps(l.tokens_per_sec_p50)}
        />
        <StatTile
          label="LATENCY"
          title="Median request latency (p50)"
          value={formatMs(l.p50_ms)}
        />
        <StatTile
          label="ERROR RATE"
          value={formatPct(err)}
          tone={err !== null && err > 0 ? 'bad' : 'default'}
        />
        <StatTile
          label="TTFT"
          title="Time to first token (p50)"
          value={formatMs(l.ttft_p50_ms)}
        />
      </div>

      {/* Per-model latency + error split (headed table, aligned columns). Extra
          top padding sets it apart from the headline summary (no divider line). */}
      {data.by_model.length > 0 ? (
        <div className="flex flex-col pt-2">
          <ModelHeader />
          <ul className="flex flex-col divide-y divide-border/60">
            {data.by_model.map((m) => (
              <ModelRow key={m.model} m={m} />
            ))}
          </ul>
        </div>
      ) : null}

      {/* REQUESTS is now a headline stat, so the footer only carries the
          sample-truncation caveat when the row cap kicked in. */}
      {data.sampled ? (
        <div className="font-mono text-[10px] text-text-tertiary">
          {formatInt(data.row_count)} requests · sampled
        </div>
      ) : null}
    </div>
  );
}
