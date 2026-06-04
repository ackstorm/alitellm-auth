// KpiRow.test.tsx — jsdom smoke/contract suite for the STATS-02 KPI row.
//
// Asserts: the 4 EXACT labels; no delta chip when compareOn=false; a chip +
// `vs prior N days` when compareOn=true AND deltas:true; the bad-up/good-up
// semantic color classes; representative formatted values.

import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';

import type { StatsCapabilities, StatsTotals } from '@/lib/api-types';
import { KpiRow } from './KpiRow';

const CAPS: StatsCapabilities = {
  token_split: true,
  per_model_last_used: true,
  deltas: true,
  per_key_spend: true,
};

const TOTALS: StatsTotals = {
  requests: 2_450_000,
  tokens: 1_000_000,
  spend: 1249.5,
  avg_cost_per_1k_req: 0.51,
  deltas: {
    requests_pct: 0.182, // up -> good (primary)
    tokens_pct: -0.05, // down -> neutral
    spend_pct: 0.1, // neutral both
    avg_cost_per_1k_req_pct: 0.2, // up -> bad (destructive)
  },
};

describe('KpiRow', () => {
  it('renders the four exact labels + representative values', () => {
    const { getByText } = render(
      <KpiRow totals={TOTALS} capabilities={CAPS} compareOn={false} rangeDays={30} />
    );
    expect(getByText('TOTAL REQUESTS')).toBeInTheDocument();
    expect(getByText('TOTAL TOKENS')).toBeInTheDocument();
    expect(getByText('SPEND')).toBeInTheDocument();
    expect(getByText('AVG COST / 1K REQ')).toBeInTheDocument();
    // abbreviate(2_450_000) -> "2.45M"; formatCurrency(1249.5) -> "$1,249.50"
    expect(getByText('2.45M')).toBeInTheDocument();
    expect(getByText('$1,249.50')).toBeInTheDocument();
  });

  it('renders NO delta chip when compareOn is false', () => {
    const { container, queryByText } = render(
      <KpiRow totals={TOTALS} capabilities={CAPS} compareOn={false} rangeDays={30} />
    );
    expect(container.querySelector('[data-slot="kpi-delta"]')).toBeNull();
    expect(queryByText(/vs prior/)).toBeNull();
  });

  it('renders delta chips + "vs prior N days" when compareOn + deltas:true', () => {
    const { container, getByText } = render(
      <KpiRow totals={TOTALS} capabilities={CAPS} compareOn rangeDays={30} />
    );
    const chips = container.querySelectorAll('[data-slot="kpi-delta"]');
    expect(chips.length).toBe(4);
    expect(getByText('vs prior 30 days')).toBeInTheDocument();
  });

  it('does NOT render chips when deltas capability is false (even if compareOn)', () => {
    const caps: StatsCapabilities = { ...CAPS, deltas: false };
    const { container, queryByText } = render(
      <KpiRow totals={TOTALS} capabilities={caps} compareOn rangeDays={30} />
    );
    expect(container.querySelector('[data-slot="kpi-delta"]')).toBeNull();
    expect(queryByText(/vs prior/)).toBeNull();
  });

  it('applies bad-up (destructive) for avg-cost-up and good-up (primary) for requests-up', () => {
    const { container } = render(
      <KpiRow totals={TOTALS} capabilities={CAPS} compareOn rangeDays={30} />
    );
    const chips = Array.from(
      container.querySelectorAll('[data-slot="kpi-delta"]')
    );
    // Card order: requests, tokens, spend, avg_cost.
    const requestsChip = chips[0];
    const avgCostChip = chips[3];
    // requests_pct > 0 with good-up -> primary tint.
    expect(requestsChip.className).toContain('text-primary');
    // avg_cost_per_1k_req_pct > 0 with bad-up -> destructive tint.
    expect(avgCostChip.className).toContain('text-destructive');
  });
});
