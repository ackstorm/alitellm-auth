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
  failed_requests: 3,
  cache_read_tokens: 124_000,
  cache_hit_pct: 0.124,
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

  it('renders a neutral "no previous info" chip when pct is null but current > 0', () => {
    // Prior baseline empty (e.g. prior window had 0 tokens) -> no % to compute and
    // no up/down to judge: a NEUTRAL grey note, never green/red.
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
    const chips = container.querySelectorAll('[data-slot="kpi-delta"]');
    expect(chips).toHaveLength(4);
    chips.forEach((c) => {
      expect(c.textContent).toContain('100%');
      expect(c.textContent).toContain('no previous info');
      // neutral grey — not the good (primary) / bad (destructive) delta colors.
      expect(c.className).toContain('text-text-secondary');
      expect(c.className).not.toContain('text-primary');
      expect(c.className).not.toContain('text-destructive');
    });
  });

  it('renders NO chip when pct is null AND the current value is 0/absent', () => {
    const totals: StatsTotals = {
      ...TOTALS,
      requests: 0,
      tokens: 0,
      spend: 0,
      avg_cost_per_1m_tokens: null,
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

  it('renders a failed-requests sub-line when failed_requests > 0', () => {
    const { getByText } = render(<KpiRow totals={TOTALS} />);
    // 3 failed; 3 / 2_450_000 -> 0.0%.
    expect(getByText(/3 failed/)).toBeInTheDocument();
  });

  it('renders NO failed sub-line when failed_requests is 0', () => {
    const totals: StatsTotals = { ...TOTALS, failed_requests: 0 };
    const { container } = render(<KpiRow totals={totals} />);
    expect(container.querySelector('[data-slot="kpi-failed"]')).toBeNull();
  });

  it('renders a cached-input sub-line when cache_hit_pct > 0', () => {
    const { getByText } = render(<KpiRow totals={TOTALS} />);
    // 0.124 -> "12.4% cached input"
    expect(getByText('12.4% cached input')).toBeInTheDocument();
  });

  it('renders NO cached-input sub-line when cache_hit_pct is null', () => {
    const totals: StatsTotals = { ...TOTALS, cache_hit_pct: null };
    const { container } = render(<KpiRow totals={totals} />);
    expect(container.querySelector('[data-slot="kpi-cache"]')).toBeNull();
  });
});
