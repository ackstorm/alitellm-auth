// BudgetPanel.test.tsx — jsdom smoke/contract suite for the STATS-08 budget panel.
//
// Asserts the locked copy + a representative value, the no-budget state, and the
// over-budget color switch (mirrors the dashboard BudgetBar logic).

import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';

import type { StatsBudget } from '@/lib/api-types';
import { BudgetPanel } from './BudgetPanel';

describe('BudgetPanel', () => {
  it('renders the section label + the "of" figure when a budget is set', () => {
    const budget: StatsBudget = {
      current: 12.5,
      max_budget: 50,
      source: 'user',
      pct: 25,
      has_budget: true,
    };
    const { getByText, container } = render(<BudgetPanel budget={budget} />);
    expect(getByText('BUDGET STATUS')).toBeInTheDocument();
    expect(getByText('$12.50 of $50.00')).toBeInTheDocument();
    // Under budget -> primary fill, not destructive.
    const fill = container.querySelector('[data-slot="budget-fill"]');
    expect(fill?.className).toContain('bg-primary');
    expect(container.querySelector('[data-slot="budget-panel"]')).toHaveAttribute(
      'data-state',
      'ok'
    );
  });

  it('renders the no-budget state when has_budget is false', () => {
    const budget: StatsBudget = {
      current: 8,
      max_budget: null,
      source: 'unknown',
      pct: null,
      has_budget: false,
    };
    const { getByText, container } = render(<BudgetPanel budget={budget} />);
    expect(getByText('BUDGET STATUS')).toBeInTheDocument();
    expect(getByText('$8.00 spent · no budget set')).toBeInTheDocument();
    // No bar in the no-budget state.
    expect(container.querySelector('[data-slot="budget-fill"]')).toBeNull();
    expect(container.querySelector('[data-slot="budget-panel"]')).toHaveAttribute(
      'data-state',
      'none'
    );
  });

  it('switches the fill to destructive when over budget', () => {
    const budget: StatsBudget = {
      current: 120,
      max_budget: 50,
      source: 'user',
      pct: 240,
      has_budget: true,
    };
    const { container } = render(<BudgetPanel budget={budget} />);
    const fill = container.querySelector('[data-slot="budget-fill"]');
    expect(fill?.className).toContain('bg-destructive');
    // Width clamped to 100% (240% pct clamps to 100).
    expect((fill as HTMLElement).style.width).toBe('100%');
  });

  it('renders the no-budget state for a null budget prop', () => {
    const { getByText } = render(<BudgetPanel budget={null} />);
    expect(getByText(/no budget set/)).toBeInTheDocument();
  });
});
