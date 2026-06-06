// KpiRow.test.tsx — jsdom smoke/contract suite for the STATS-02 KPI row.
//
// Asserts the 4 EXACT labels + representative formatted values. The Compare /
// delta-chip surface was removed, so the row renders headline metrics only.

import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';

import type { StatsTotals } from '@/lib/api-types';
import { KpiRow } from './KpiRow';

const TOTALS: StatsTotals = {
  requests: 2_450_000,
  tokens: 1_000_000,
  spend: 1249.5,
  avg_cost_per_1k_req: 0.51,
  deltas: {
    requests_pct: 0.182,
    tokens_pct: -0.05,
    spend_pct: 0.1,
    avg_cost_per_1k_req_pct: 0.2,
  },
};

describe('KpiRow', () => {
  it('renders the four exact labels + representative values', () => {
    const { getByText } = render(<KpiRow totals={TOTALS} />);
    expect(getByText('TOTAL REQUESTS')).toBeInTheDocument();
    expect(getByText('TOTAL TOKENS')).toBeInTheDocument();
    expect(getByText('SPEND')).toBeInTheDocument();
    expect(getByText('AVG COST / 1K REQ')).toBeInTheDocument();
    // abbreviate(2_450_000) -> "2.45M"; formatCurrency(1249.5) -> "$1,249.50"
    expect(getByText('2.45M')).toBeInTheDocument();
    expect(getByText('$1,249.50')).toBeInTheDocument();
  });

  it('renders NO delta chip (Compare removed)', () => {
    const { container, queryByText } = render(<KpiRow totals={TOTALS} />);
    expect(container.querySelector('[data-slot="kpi-delta"]')).toBeNull();
    expect(queryByText(/vs prior/)).toBeNull();
  });
});
