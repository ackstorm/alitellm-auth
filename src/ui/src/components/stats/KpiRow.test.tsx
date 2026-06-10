// KpiRow.test.tsx — jsdom smoke/contract suite for the STATS-02 KPI row.
//
// Asserts the 4 EXACT labels + representative formatted values, plus the
// period-over-period delta chips (rendered from totals.deltas; null pct -> no chip).

import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';

import type { StatsTotals } from '@/lib/api-types';
import { KpiRow } from './KpiRow';

const TOTALS: StatsTotals = {
  requests: 2_450_000,
  tokens: 1_000_000,
  spend: 1249.5,
  avg_cost_per_1m_tokens: 0.51,
  deltas: {
    requests_pct: 0.182,
    tokens_pct: -0.05,
    spend_pct: 0.1,
    avg_cost_per_1m_tokens_pct: 0.2,
  },
};

describe('KpiRow', () => {
  it('renders the four exact labels + representative values', () => {
    const { getByText } = render(<KpiRow totals={TOTALS} />);
    expect(getByText('TOTAL REQUESTS')).toBeInTheDocument();
    expect(getByText('TOTAL TOKENS')).toBeInTheDocument();
    expect(getByText('SPEND')).toBeInTheDocument();
    expect(getByText('AVG COST / 1M TOKENS')).toBeInTheDocument();
    // abbreviate(2_450_000) -> "2.45M"; formatCurrency(1249.5) -> "$1,249.50"
    expect(getByText('2.45M')).toBeInTheDocument();
    expect(getByText('$1,249.50')).toBeInTheDocument();
  });

  it('renders one delta chip per card with signed pct + direction color', () => {
    const { container } = render(<KpiRow totals={TOTALS} />);
    const chips = container.querySelectorAll('[data-slot="kpi-delta"]');
    expect(chips).toHaveLength(4);
    // requests +18.2% up = good -> primary
    expect(chips[0].textContent).toContain('+18.2%');
    expect(chips[0].className).toContain('text-primary');
    // tokens -5.0% down = bad -> destructive
    expect(chips[1].textContent).toContain('-5.0%');
    expect(chips[1].className).toContain('text-destructive');
    // spend +10.0% up = bad (inverted) -> destructive
    expect(chips[2].textContent).toContain('+10.0%');
    expect(chips[2].className).toContain('text-destructive');
  });

  it('renders NO chip when a delta pct is null (degraded prior window)', () => {
    const totals: StatsTotals = {
      ...TOTALS,
      deltas: {
        requests_pct: null,
        tokens_pct: null,
        spend_pct: null,
        avg_cost_per_1m_tokens_pct: null,
      },
    };
    const { container } = render(<KpiRow totals={totals} />);
    expect(container.querySelectorAll('[data-slot="kpi-delta"]')).toHaveLength(0);
  });
});
