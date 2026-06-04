// TopKeys.test.tsx — jsdom smoke/contract suite for the STATS-07 top-keys panel.
//
// Asserts the locked section label + column copy, a representative ranked row
// (alias + masked-id fallback + formatted figures), the empty state, and the
// per_key_spend coming-soon gate.

import { describe, expect, it } from 'vitest';
import { render } from '@testing-library/react';

import type { StatsCapabilities, StatsKeyRow } from '@/lib/api-types';
import { TopKeys } from './TopKeys';

const CAPS: StatsCapabilities = {
  token_split: true,
  per_model_last_used: true,
  deltas: true,
  per_key_spend: true,
};

const KEYS: StatsKeyRow[] = [
  { id: 'key-abc123def456', key_alias: 'prod-key', requests: 1000, spend: 9.5, spend_pct: 0.7 },
  { id: 'key-zzz999yyy888', key_alias: null, requests: 250, spend: 2.5, spend_pct: 0.3 },
];

describe('TopKeys', () => {
  it('renders the section label + column copy', () => {
    const { getByText } = render(<TopKeys keys={KEYS} capabilities={CAPS} />);
    expect(getByText('TOP API KEYS')).toBeInTheDocument();
    expect(getByText('KEY')).toBeInTheDocument();
    expect(getByText('REQUESTS')).toBeInTheDocument();
    expect(getByText('SPEND')).toBeInTheDocument();
    expect(getByText('% OF TOTAL')).toBeInTheDocument();
  });

  it('renders a representative ranked row (alias + figures)', () => {
    const { getByText } = render(<TopKeys keys={KEYS} capabilities={CAPS} />);
    expect(getByText('prod-key')).toBeInTheDocument();
    expect(getByText('$9.50')).toBeInTheDocument();
    expect(getByText('70.0%')).toBeInTheDocument(); // spend_pct 0.7 -> 70.0%
  });

  it('masks the key id when there is no alias (maskKey fallback)', () => {
    const { getByText } = render(<TopKeys keys={KEYS} capabilities={CAPS} />);
    // maskKey("key-zzz999yyy888") -> "key…y888"
    expect(getByText('key…y888')).toBeInTheDocument();
  });

  it('renders the empty copy for no rows', () => {
    const { getByText } = render(<TopKeys keys={[]} capabilities={CAPS} />);
    expect(getByText('No usage in this range')).toBeInTheDocument();
  });

  it('renders the coming-soon copy when per_key_spend is false', () => {
    const caps: StatsCapabilities = { ...CAPS, per_key_spend: false };
    const { getByText } = render(<TopKeys keys={KEYS} capabilities={caps} />);
    expect(getByText('Coming soon')).toBeInTheDocument();
  });
});
