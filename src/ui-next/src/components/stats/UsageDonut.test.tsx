// UsageDonut.test.tsx — jsdom smoke/contract suite for the STATS-05 token-split
// donut (recharts).
//
// Recharts' ResponsiveContainer measures its parent (0x0 under jsdom) and
// renders nothing, so the populated branch never paints. We mock it the same way
// the chart tests do (SpendChart.test.tsx) to inject a fixed size into its single
// child so the real donut renders. Branches are asserted by capability + data.

import { cloneElement, isValidElement } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { render } from '@testing-library/react';

import type { StatsCapabilities } from '@/lib/api-types';

vi.mock('recharts', async (importOriginal) => {
  const actual = await importOriginal<typeof import('recharts')>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: React.ReactNode }) =>
      isValidElement(children)
        ? cloneElement(
            children as React.ReactElement<{ width?: number; height?: number }>,
            { width: 600, height: 160 }
          )
        : children,
  };
});

import { UsageDonut } from './UsageDonut';

const CAPS: StatsCapabilities = {
  token_split: true,
  per_model_last_used: true,
  deltas: true,
  per_key_spend: true,
};

const MODELS = [
  { input_tokens: 600_000, output_tokens: 400_000 },
  { input_tokens: 0, output_tokens: 0 },
];

describe('UsageDonut', () => {
  it('renders the ready donut (TOTAL caption + legend) for populated data', () => {
    const { container, getByText } = render(
      <UsageDonut
        totals={null}
        models={MODELS}
        capabilities={CAPS}
      />
    );
    expect(getByText('TOTAL')).toBeInTheDocument();
    expect(getByText('Input')).toBeInTheDocument();
    expect(getByText('Output')).toBeInTheDocument();
    // A recharts SVG surface exists (mocked ResponsiveContainer renders it).
    const surface =
      container.querySelector('.recharts-surface') ?? container.querySelector('svg');
    expect(surface).not.toBeNull();
  });

  it('renders the empty copy when token_split is on but there is no data', () => {
    const { getByText, container } = render(
      <UsageDonut
        totals={null}
        models={[{ input_tokens: 0, output_tokens: 0 }]}
        capabilities={CAPS}
      />
    );
    expect(getByText('No usage in this range')).toBeInTheDocument();
    expect(container.querySelector('svg')).toBeNull();
  });

  it('renders the coming-soon copy when token_split capability is false', () => {
    const caps: StatsCapabilities = { ...CAPS, token_split: false };
    const { getByText, container } = render(
      <UsageDonut totals={null} models={MODELS} capabilities={caps} />
    );
    expect(getByText('Coming soon')).toBeInTheDocument();
    // The coming-soon panel still shows the TOTAL caption + an em-dash total.
    expect(getByText('TOTAL')).toBeInTheDocument();
    expect(container.querySelector('svg')).toBeNull();
  });
});
