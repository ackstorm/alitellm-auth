// LatencyPanel.test.tsx — vitest suite for the latency figures leaf (jsdom).
// Pure presentational: assert which of the three branches renders + key copy.

import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';

import type { LatencyResponse } from '@/lib/api-types';
import { LatencyPanel } from './LatencyPanel';

function makeLatency(overrides: Partial<LatencyResponse> = {}): LatencyResponse {
  return {
    available: true,
    sampled: false,
    row_count: 280,
    window: { start: '2026-07-05', end: '2026-07-11', days: 7 },
    latency: {
      p50_ms: 3850,
      p95_ms: 8510,
      p99_ms: 8950,
      avg_ms: 4200,
      ttft_p50_ms: 1090,
      ttft_p95_ms: 2830,
      tokens_per_sec_p50: 139,
    },
    outcomes: [
      { status: 'success', count: 260 },
      { status: 'failure', count: 20 },
    ],
    by_model: [
      { model: 'gemini/flash', requests: 140, failed: 0, p50_ms: 3000, p95_ms: 8580 },
    ],
    ...overrides,
  };
}

afterEach(cleanup);

describe('LatencyPanel', () => {
  it('renders the unavailable state when available is false', () => {
    render(<LatencyPanel data={makeLatency({ available: false })} isError={false} />);
    expect(screen.getByText(/not available/i)).toBeInTheDocument();
  });

  it('renders the unavailable state on error', () => {
    render(<LatencyPanel data={undefined} isError />);
    expect(screen.getByText(/not available/i)).toBeInTheDocument();
  });

  it('renders the empty state when no rows in window', () => {
    render(
      <LatencyPanel
        data={makeLatency({ row_count: 0, latency: null })}
        isError={false}
      />,
    );
    expect(screen.getByText(/no requests in this range/i)).toBeInTheDocument();
  });

  it('renders the percentile headline + throughput on the ready path', () => {
    render(<LatencyPanel data={makeLatency()} isError={false} />);
    expect(screen.getByText('p50')).toBeInTheDocument();
    expect(screen.getByText('3.85 s')).toBeInTheDocument(); // p50 formatted
    expect(screen.getByText('139 tok/s')).toBeInTheDocument();
    expect(screen.getByText(/280 requests/)).toBeInTheDocument();
  });

  it('formats sub-second latency as ms', () => {
    render(
      <LatencyPanel
        data={makeLatency({
          latency: {
            p50_ms: 812,
            p95_ms: 950,
            p99_ms: 990,
            avg_ms: 800,
            ttft_p50_ms: null,
            ttft_p95_ms: null,
            tokens_per_sec_p50: null,
          },
        })}
        isError={false}
      />,
    );
    expect(screen.getByText('812 ms')).toBeInTheDocument();
  });
});
