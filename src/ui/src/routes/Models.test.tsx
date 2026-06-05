// Models.test.tsx — vitest for the #/models catalog page (jsdom).
//
// useModels is fully mocked so NO real fetch happens; each test programs its
// return to drive the loading / error / empty / populated branches. Pragmatic:
// assert which BRANCH renders + the locked copy + key formatting, not pixels.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { UseQueryResult } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

import type { ModelRow, ModelsResponse } from '@/lib/api-types';

vi.mock('@/hooks/use-models', () => ({ useModels: vi.fn() }));

import { useModels } from '@/hooks/use-models';
import { Models } from './Models';

const useModelsMock = vi.mocked(useModels);

function makeModel(over: Partial<ModelRow> = {}): ModelRow {
  return {
    name: 'ackstorm.fast',
    providers: ['openai'],
    mode: 'chat',
    max_input_tokens: 128000,
    max_output_tokens: 16384,
    input_cost_per_token: 1.5e-7,
    output_cost_per_token: 6e-7,
    supports_vision: true,
    supports_function_calling: true,
    supports_reasoning: false,
    supports_web_search: false,
    ...over,
  };
}

function setPending(): void {
  useModelsMock.mockReturnValue({
    data: undefined,
    isPending: true,
    isError: false,
    refetch: vi.fn(),
  } as unknown as UseQueryResult<ModelsResponse>);
}

function setError(): ReturnType<typeof vi.fn> {
  const refetch = vi.fn();
  useModelsMock.mockReturnValue({
    data: undefined,
    isPending: false,
    isError: true,
    refetch,
  } as unknown as UseQueryResult<ModelsResponse>);
  return refetch;
}

function setSuccess(models: ModelRow[]): void {
  useModelsMock.mockReturnValue({
    data: { models },
    isPending: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as UseQueryResult<ModelsResponse>);
}

afterEach(() => {
  vi.clearAllMocks();
  cleanup();
});

describe('Models — loading', () => {
  beforeEach(() => setPending());
  it('renders a skeleton and keeps the title', () => {
    const { container } = render(<Models />);
    expect(
      container.querySelectorAll('[data-slot="skeleton"]').length,
    ).toBeGreaterThan(0);
    expect(screen.getByText('Models')).toBeInTheDocument();
  });
});

describe('Models — error', () => {
  it('shows the locked error heading and retry re-fires the query', () => {
    const refetch = setError();
    render(<Models />);
    expect(screen.getByText("Couldn't load models")).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'retry' }));
    expect(refetch).toHaveBeenCalledTimes(1);
  });
});

describe('Models — empty', () => {
  it('shows the empty state when the catalog is []', () => {
    setSuccess([]);
    render(<Models />);
    expect(screen.getByText('No models yet')).toBeInTheDocument();
  });
});

describe('Models — populated', () => {
  it('renders the alias, provider, per-1M pricing, and capability badges', () => {
    setSuccess([makeModel()]);
    render(<Models />);
    expect(screen.getByText('ackstorm.fast')).toBeInTheDocument();
    expect(screen.getByText('openai')).toBeInTheDocument();
    // Combined price cell: 1.5e-7*1e6=$0.15 (in) / 6e-7*1e6=$0.60 (out).
    expect(screen.getByText(/\$0\.15/)).toBeInTheDocument();
    expect(screen.getByText(/\$0\.60/)).toBeInTheDocument();
    // Context window abbreviated (128K input).
    expect(screen.getByText(/128K/)).toBeInTheDocument();
    // Enabled capabilities surface as labelled badges; disabled ones do not.
    expect(screen.getByLabelText('Vision')).toBeInTheDocument();
    expect(screen.getByLabelText('Function calling / tools')).toBeInTheDocument();
    // Non-reasoning model: no Thinking marker.
    expect(screen.queryByLabelText('Thinking model')).not.toBeInTheDocument();
  });

  it('marks reasoning models in the Thinking column', () => {
    setSuccess([makeModel({ supports_reasoning: true })]);
    render(<Models />);
    // Column header is always present.
    expect(screen.getByText('Thinking')).toBeInTheDocument();
    // Reasoning row carries the labelled badge.
    const badge = screen.getByLabelText('Thinking model');
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveTextContent('Yes');
  });
});
