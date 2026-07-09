import { describe, it, expect } from 'vitest';
import { applyModelFilters } from '@/components/models/ModelFilters';

const row = (over: Partial<Record<string, unknown>>) => ({
  name: 'm', providers: [], mode: 'chat',
  max_input_tokens: null, max_output_tokens: null,
  input_cost_per_token: null, output_cost_per_token: null,
  supports_vision: false, supports_function_calling: false,
  supports_reasoning: false, supports_web_search: false, ...over,
});

describe('applyModelFilters', () => {
  it('keeps only rows matching every active capability', () => {
    const rows = [row({ supports_vision: true }), row({})];
    expect(applyModelFilters(rows as never, new Set(['vision']))).toHaveLength(1);
    expect(applyModelFilters(rows as never, new Set())).toHaveLength(2);
  });

  it('requires ALL active caps (AND semantics)', () => {
    const rows = [
      row({ supports_vision: true, supports_reasoning: true }),
      row({ supports_vision: true }),
    ];
    expect(
      applyModelFilters(rows as never, new Set(['vision', 'reasoning'])),
    ).toHaveLength(1);
  });
});
