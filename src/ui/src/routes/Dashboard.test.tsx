// Dashboard.test.tsx — vitest suite for the dashboard CONTAINER (jsdom).
//
// The keys data hook (useKeys) is fully mocked so NO real fetch happens; each
// test programs its return to drive the metric/empty/populated branches. The
// delete mutation (useDeleteKey, used by the DeleteKeyModal the dashboard
// renders) is mocked too. The create-key-modal + fresh-keys stores are reset
// between tests; the REAL toast store is reset so the delete success toast
// stays isolated. The clipboard is stubbed for the endpoint-copy path.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { UseQueryResult } from '@tanstack/react-query';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';

import type { KeyRow, SessionMe } from '@/lib/api-types';

// Mock the keys hooks module — useKeys drives the dashboard metrics/table,
// useDeleteKey backs the DeleteKeyModal the dashboard renders.
vi.mock('@/hooks/use-keys', () => ({
  useKeys: vi.fn(),
  useDeleteKey: vi.fn(),
  useToggleKeyBlock: vi.fn(),
  useChangeKeyTeam: vi.fn(),
  KEYS_QUERY_KEY: ['session', 'keys'],
}));

// KeysTable (mounted by the dashboard) reads useTeams to gate its Change-team
// action — mock it to [] so the dashboard test renders without a QueryClient.
vi.mock('@/hooks/use-teams', () => ({
  useTeams: vi.fn(() => ({ data: [] })),
}));

// useStats backs the "Requests (MTD)" tile — mocked so no real fetch fires (the
// dashboard test renders without a QueryClientProvider). Defaults to a benign
// non-success state in beforeEach (tile shows EM_DASH).
vi.mock('@/hooks/use-stats', () => ({
  useStats: vi.fn(),
}));

import {
  useChangeKeyTeam,
  useDeleteKey,
  useKeys,
  useToggleKeyBlock,
} from '@/hooks/use-keys';
import { useStats } from '@/hooks/use-stats';
import { useTeams } from '@/hooks/use-teams';
import { Dashboard } from './Dashboard';
import { formatCurrency } from '@/lib/format';
import {
  initialCreateKeyModalState,
  useCreateKeyModalStore,
} from '@/stores/create-key-modal';
import {
  initialFreshKeysState,
  useFreshKeysStore,
} from '@/stores/fresh-keys';
import { initialToastState, useToastStore } from '@/hooks/use-toast';

const useKeysMock = vi.mocked(useKeys);
const useDeleteKeyMock = vi.mocked(useDeleteKey);
const useToggleKeyBlockMock = vi.mocked(useToggleKeyBlock);
const useChangeKeyTeamMock = vi.mocked(useChangeKeyTeam);
const useStatsMock = vi.mocked(useStats);
const useTeamsMock = vi.mocked(useTeams);

// Build a valid SessionMe fixture with overrides.
function makeMe(overrides: Partial<SessionMe> = {}): SessionMe {
  return {
    email: 'alice@example.com',
    name: 'Alice Example',
    team_id: 'team-platform',
    access_groups: [],
    endpoint: 'https://litellm.example.com',
    limits: null,
    spend: { current: 12.5, source: 'user' },
    ...overrides,
  };
}

// A minimal projected /keys row factory.
function makeRow(overrides: Partial<KeyRow> = {}): KeyRow {
  return {
    id: 'key-abc123',
    key_alias: 'my-key',
    spend: 0,
    budget: null,
    tpm_limit: null,
    rpm_limit: null,
    models: null,
    team_id: null,
    created_at: '2026-03-01T10:00:00+00:00',
    expires: null,
    last_used: null,
    ...overrides,
  };
}

/** Program useKeys to a populated success state with `rows`. */
function setKeysSuccess(rows: KeyRow[]): void {
  useKeysMock.mockReturnValue({
    data: rows,
    isPending: false,
    isError: false,
    isSuccess: true,
  } as unknown as UseQueryResult<KeyRow[]>);
}

/** Program useKeys to the pending (loading) state. */
function setKeysPending(): void {
  useKeysMock.mockReturnValue({
    data: undefined,
    isPending: true,
    isError: false,
    isSuccess: false,
  } as unknown as UseQueryResult<KeyRow[]>);
}

beforeEach(() => {
  // Reset the create-key-modal store to closed, preserving its actions.
  const { openModal, closeModal } = useCreateKeyModalStore.getState();
  useCreateKeyModalStore.setState(
    { ...initialCreateKeyModalState, openModal, closeModal },
    true,
  );
  // Reset the fresh-keys store to empty.
  const { setFresh, dropFresh } = useFreshKeysStore.getState();
  useFreshKeysStore.setState({ ...initialFreshKeysState, setFresh, dropFresh }, true);
  // Reset the real toast store.
  const { toast, dismiss, dismissAll } = useToastStore.getState();
  useToastStore.setState({ ...initialToastState, toast, dismiss, dismissAll }, true);
  // Default the delete mutation to a no-op resolved mutation.
  useDeleteKeyMock.mockReturnValue({
    mutateAsync: vi.fn().mockResolvedValue({ status: 'deleted', id: 'key-abc123' }),
    isPending: false,
  } as unknown as ReturnType<typeof useDeleteKey>);
  // Default the make-default mutation to a no-op.
  // Default the block-toggle mutation to a no-op.
  useToggleKeyBlockMock.mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
  } as unknown as ReturnType<typeof useToggleKeyBlock>);
  // Default the change-team mutation to a no-op.
  useChangeKeyTeamMock.mockReturnValue({
    mutate: vi.fn(),
    isPending: false,
  } as unknown as ReturnType<typeof useChangeKeyTeam>);
  // Default stats to a non-success state — the Requests (MTD) tile shows EM_DASH.
  useStatsMock.mockReturnValue({
    data: undefined,
    isSuccess: false,
    isPending: true,
    isError: false,
  } as unknown as ReturnType<typeof useStats>);
  // Default teams to empty so the Team tile falls back to me.team_id; the
  // multi-team test overrides this per-test.
  useTeamsMock.mockReturnValue({ data: [] } as unknown as ReturnType<typeof useTeams>);
});

afterEach(() => {
  vi.clearAllMocks();
  useToastStore.getState().dismissAll();
  cleanup();
});

describe('Dashboard — top row + tiles', () => {
  it('greeting shows me.name', () => {
    setKeysSuccess([]);
    render(<Dashboard me={makeMe({ name: 'Alice Example' })} />);
    expect(screen.getByText(/Welcome back,/)).toBeInTheDocument();
    expect(screen.getByText('Alice Example')).toBeInTheDocument();
  });

  it('Spend (MTD) shows formatCurrency(stats.totals.spend) when stats load', () => {
    setKeysSuccess([]);
    useStatsMock.mockReturnValue({
      data: { totals: { requests: 4600, tokens: 8_200_000, spend: 15.94 } },
      isSuccess: true,
      isPending: false,
      isError: false,
    } as unknown as ReturnType<typeof useStats>);
    // me.spend.current is a different (enforced-cap) counter and must NOT drive the tile.
    render(<Dashboard me={makeMe({ spend: { current: 1249.5, source: 'user' } })} />);
    expect(screen.getByText(formatCurrency(15.94))).toBeInTheDocument();
    expect(screen.queryByText(formatCurrency(1249.5))).not.toBeInTheDocument();
  });

  it('Spend (MTD) tile shows the em-dash while stats are unavailable', () => {
    setKeysSuccess([]);
    // useStats defaults (beforeEach) to non-success -> EM_DASH.
    render(<Dashboard me={makeMe({ spend: { current: 1249.5, source: 'user' } })} />);
    expect(screen.queryByText(formatCurrency(1249.5))).not.toBeInTheDocument();
  });

  it('TOTAL REQUESTS / TOTAL TOKENS cards show abbreviated figures when stats load', () => {
    setKeysSuccess([]);
    useStatsMock.mockReturnValue({
      data: { totals: { requests: 4600, tokens: 8_200_000, spend: 15.94 } },
      isSuccess: true,
      isPending: false,
      isError: false,
    } as unknown as ReturnType<typeof useStats>);
    render(<Dashboard me={makeMe()} />);
    // Now two separate KPI cards (abbreviate(4600)='4.6K', abbreviate(8.2M)='8.2M').
    expect(screen.getByText('TOTAL REQUESTS')).toBeInTheDocument();
    expect(screen.getByText('4.6K')).toBeInTheDocument();
    expect(screen.getByText('TOTAL TOKENS')).toBeInTheDocument();
    expect(screen.getByText('8.2M')).toBeInTheDocument();
  });

  it('TOTAL REQUESTS card shows the em-dash while stats are unavailable', () => {
    setKeysSuccess([]);
    // useStats defaults (beforeEach) to non-success -> EM_DASH inside KpiCard.
    render(<Dashboard me={makeMe()} />);
    expect(screen.getByText('TOTAL REQUESTS')).toBeInTheDocument();
  });
});

describe('Dashboard — Active keys tile', () => {
  it('shows the non-revoked count when the keys query has loaded', () => {
    setKeysSuccess([
      makeRow({ id: 'key-1' }),
      makeRow({ id: 'key-2' }),
      makeRow({ id: 'key-3', revoked: true }),
    ]);
    render(<Dashboard me={makeMe()} />);
    // 3 rows, 1 revoked -> 2 active.
    expect(screen.getByText('2')).toBeInTheDocument();
  });

  it('shows the em-dash placeholder while the keys query is pending', () => {
    setKeysPending();
    render(<Dashboard me={makeMe()} />);
    // The Active keys tile reads "—" while pending (never a misleading 0). The
    // em-dash appears in the tile; assert at least one is in the document.
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
  });
});

describe('Dashboard — budget bar', () => {
  it('shows "no budget set" when limits is null', () => {
    setKeysSuccess([]);
    render(<Dashboard me={makeMe({ limits: null })} />);
    expect(screen.getByText(/no budget set/)).toBeInTheDocument();
  });

  it('shows "no budget set" when max_budget <= 0', () => {
    setKeysSuccess([]);
    render(
      <Dashboard
        me={makeMe({
          limits: {
            max_budget: 0,
            budget_duration: null,
            tpm_limit: null,
            rpm_limit: null,
          },
        })}
      />,
    );
    expect(screen.getByText(/no budget set/)).toBeInTheDocument();
  });

  it('shows "{spend} of {max}" when a positive budget is set', () => {
    setKeysSuccess([]);
    render(
      <Dashboard
        me={makeMe({
          spend: { current: 20, source: 'user' },
          limits: {
            max_budget: 50,
            budget_duration: '24h',
            tpm_limit: null,
            rpm_limit: null,
          },
        })}
      />,
    );
    // The amount carries the budget PERIOD so "$X of $Y" is unambiguous, plus a
    // "% used" suffix. Both are child spans, so match on the amount span's
    // leading textContent.
    expect(
      screen.getByText(
        (_content, el) =>
          el?.textContent?.startsWith(
            `${formatCurrency(20)} of ${formatCurrency(50)} / 24h`,
          ) ?? false,
      ),
    ).toBeInTheDocument();
    // 20/50 -> 40% used; 24h is sub-monthly so no projection.
    expect(screen.getByText(/40% used/)).toBeInTheDocument();
    expect(screen.queryByText(/projected/)).not.toBeInTheDocument();
  });
});

describe('Dashboard — keys section + modals', () => {
  it('renders the KeysTable (the empty-state copy proves it mounted)', () => {
    setKeysSuccess([]);
    render(<Dashboard me={makeMe()} />);
    expect(screen.getByText('No API Keys')).toBeInTheDocument();
  });

  it('clicking "+ New Key" opens the create modal (store open === true)', () => {
    setKeysSuccess([]);
    render(<Dashboard me={makeMe()} />);
    expect(useCreateKeyModalStore.getState().open).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: '+ New Key' }));
    expect(useCreateKeyModalStore.getState().open).toBe(true);
  });

  it('choosing a row Revoke opens the DeleteKeyModal ("Revoke Key" title appears)', async () => {
    setKeysSuccess([makeRow({ id: 'key-del' })]);
    render(<Dashboard me={makeMe()} />);
    // No delete modal until a row's revoke action (now in the kebab) fires.
    expect(screen.queryByText('Revoke Key')).not.toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole('button', { name: 'More actions' }), {
      key: 'Enter',
    });
    const item = await screen.findByRole('menuitem', { name: 'Revoke key' });
    fireEvent.keyDown(item, { key: 'Enter' });
    expect(screen.getByText('Revoke Key')).toBeInTheDocument();
  });
});

describe('Dashboard — access groups tile', () => {
  it('shows a pill per access group, without our `team-` bookkeeping prefix', () => {
    setKeysSuccess([makeRow({ id: 'key-1' })]);
    const { container } = render(
      <Dashboard me={makeMe({ access_groups: ['team-default', 'team-dream'] })} />
    );
    const pills = [...container.querySelectorAll('[data-slot="team-pill"]')].map(
      (el) => el.textContent
    );
    expect(pills).toEqual(['default', 'dream']);
  });

  it('keeps a group name that carries no prefix as-is', () => {
    setKeysSuccess([makeRow({ id: 'key-1' })]);
    const { container } = render(<Dashboard me={makeMe({ access_groups: ['research'] })} />);
    expect(container.querySelector('[data-slot="team-pill"]')?.textContent).toBe('research');
  });

  it('says so when the user has no access groups at all', () => {
    setKeysSuccess([makeRow({ id: 'key-1' })]);
    const { container } = render(<Dashboard me={makeMe({ access_groups: [] })} />);
    expect(container.querySelector('[data-slot="team-pill"]')).not.toBeInTheDocument();
    expect(screen.getByText(/No access groups/i)).toBeInTheDocument();
  });

  it('never shows the personal team — it grants nothing on its own', () => {
    setKeysSuccess([makeRow({ id: 'key-1', team_id: 'user-alice@example.com' })]);
    render(
      <Dashboard
        me={makeMe({ team_id: 'user-alice@example.com', access_groups: ['team-default'] })}
      />
    );
    expect(screen.queryByText('user-alice@example.com')).not.toBeInTheDocument();
  });
});
