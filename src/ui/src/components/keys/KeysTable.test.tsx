// KeysTable.test.tsx — vitest suite for the keys data-table view (jsdom).
//
// The data hook (useKeys) is fully mocked so NO real fetch happens; each test
// programs its return to drive the loading/error/empty/populated branches. The
// table renders no secret material and no reveal/copy actions (those were
// removed — the sk- is shown once, at mint time, in the create-key modal); the
// only per-row action is Revoke.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { UseQueryResult, UseMutationResult } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';

import type { BlockKeyResponse, KeyRow } from '@/lib/api-types';
import { relativeTime } from '@/lib/relative-time';

// Mock the data hook — each test sets useKeys's return value.
vi.mock('@/hooks/use-keys', () => ({
  useKeys: vi.fn(),
  useToggleKeyBlock: vi.fn(),
  KEYS_QUERY_KEY: ['session', 'keys'],
}));

import {
  useKeys,
  useToggleKeyBlock,
} from '@/hooks/use-keys';
import { KeysTable } from './KeysTable';

const useKeysMock = vi.mocked(useKeys);
const useToggleKeyBlockMock = vi.mocked(useToggleKeyBlock);


// Reusable mutation stubs; reset per test via beforeEach.
let toggleBlockMutate: ReturnType<typeof vi.fn>;
beforeEach(() => {
  toggleBlockMutate = vi.fn();
  useToggleKeyBlockMock.mockReturnValue({
    mutate: toggleBlockMutate,
  } as unknown as UseMutationResult<BlockKeyResponse, Error, { id: string; blocked: boolean }>);
});

// A minimal projected /keys row factory (mirrors the api-types KeyRow contract).
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

/** Program useKeys to return a populated success state with `rows`. */
function setRows(rows: KeyRow[]): void {
  useKeysMock.mockReturnValue({
    data: rows,
    isPending: false,
    isError: false,
  } as unknown as UseQueryResult<KeyRow[]>);
}

afterEach(() => {
  vi.clearAllMocks();
});

describe('KeysTable — state branches', () => {
  it('loading state shows "Loading your keys…"', () => {
    useKeysMock.mockReturnValue({
      data: undefined,
      isPending: true,
      isError: false,
    } as unknown as UseQueryResult<KeyRow[]>);

    render(<KeysTable onDelete={vi.fn()} />);
    expect(screen.getByText('Loading your keys…')).toBeInTheDocument();
  });

  it('error state shows the exact error copy', () => {
    useKeysMock.mockReturnValue({
      data: undefined,
      isPending: false,
      isError: true,
    } as unknown as UseQueryResult<KeyRow[]>);

    render(<KeysTable onDelete={vi.fn()} />);
    expect(
      screen.getByText("Couldn't load your keys. Refresh the page to try again.")
    ).toBeInTheDocument();
  });

  it('empty state shows "No API Keys" + body copy and renders no data rows', () => {
    setRows([]);
    render(<KeysTable onDelete={vi.fn()} />);

    expect(screen.getByText('No API Keys')).toBeInTheDocument();
    expect(
      screen.getByText('You have no virtual keys yet. Create one to get started.')
    ).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Revoke' })).not.toBeInTheDocument();
  });
});

describe('KeysTable — populated table', () => {
  it('renders the column headers in order', () => {
    setRows([makeRow()]);
    render(<KeysTable onDelete={vi.fn()} />);

    for (const label of ['Key ID', 'Created', 'Last used', 'Expires', 'Status']) {
      expect(screen.getByRole('columnheader', { name: label })).toBeInTheDocument();
    }
  });

  it('shows the key_alias when present', () => {
    setRows([makeRow({ key_alias: 'production-key' })]);
    render(<KeysTable onDelete={vi.fn()} />);
    expect(screen.getByText('production-key')).toBeInTheDocument();
  });

  it('shows the id verbatim (<= 16 chars) when key_alias is null', () => {
    setRows([makeRow({ key_alias: null, id: 'key-abc123' })]);
    render(<KeysTable onDelete={vi.fn()} />);
    // 'key-abc123' is 10 chars (<= 16) -> shown in full, no ellipsis.
    expect(screen.getByText('key-abc123')).toBeInTheDocument();
  });

  it('renders a relative Last used cell (recent = not stale)', () => {
    // 2h ago — deterministic relative to the test clock and well under the
    // 30-day stale threshold, so the non-stale variant renders.
    const lastUsed = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
    setRows([makeRow({ last_used: lastUsed })]);
    render(<KeysTable onDelete={vi.fn()} />);
    expect(screen.getByText(relativeTime(lastUsed))).toBeInTheDocument();
    expect(screen.getByTestId('key-lastused')).toBeInTheDocument();
  });

  it('renders relative last-used and marks stale keys', () => {
    // One never-used row (null) and one used long ago — both are stale.
    setRows([
      makeRow({ id: 'key-never', last_used: null }),
      makeRow({ id: 'key-old', last_used: '2020-01-01T00:00:00+00:00' }),
    ]);
    render(<KeysTable onDelete={vi.fn()} />);
    expect(screen.getByText('Never used')).toBeInTheDocument();
    expect(screen.getAllByTestId('key-lastused-stale')).toHaveLength(2);
  });

  it('shows the truncated id (16 chars + ellipsis) beneath the alias, prefixed "id:"', () => {
    setRows([makeRow({ key_alias: 'production-key', id: 'key-0123456789abcdef' })]);
    render(<KeysTable onDelete={vi.fn()} />);
    // 'key-0123456789abcdef' is 20 chars -> first 16 + ellipsis = 'key-0123456789ab…'.
    expect(screen.getByText('id:key-0123456789ab…')).toBeInTheDocument();
  });

  it('status pill honors Revoked > Expired > Active precedence', () => {
    const past = '2000-01-01T00:00:00+00:00';
    setRows([
      makeRow({ id: 'key-revoked', revoked: true, expires: past }),
      makeRow({ id: 'key-expired', expires: past }),
      makeRow({ id: 'key-active' }),
    ]);
    render(<KeysTable onDelete={vi.fn()} />);

    expect(screen.getByText('Revoked')).toBeInTheDocument();
    expect(screen.getByText('Expired')).toBeInTheDocument();
    expect(screen.getByText('Active')).toBeInTheDocument();
  });

  it('renders a rate-limit column (em-dash when a limit is unset)', () => {
    setRows([makeRow({ id: 'key-lim', tpm_limit: 1000, rpm_limit: null })]);
    render(<KeysTable onDelete={vi.fn()} />);
    expect(
      screen.getByText(
        (_content, el) => el?.textContent === '1,000 / —' && el.tagName === 'SPAN',
      ),
    ).toBeInTheDocument();
  });

  it('renders "Never" for a null expiry and a formatted date otherwise', () => {
    setRows([
      makeRow({ id: 'key-never', expires: null }),
      makeRow({ id: 'key-dated', expires: '2027-06-15T00:00:00+00:00' }),
    ]);
    render(<KeysTable onDelete={vi.fn()} />);

    expect(screen.getByText('Never')).toBeInTheDocument();
    expect(screen.getByText('Jun 15, 2027')).toBeInTheDocument();
  });
});

describe('KeysTable — no secret material, no reveal/copy actions', () => {
  it('renders neither a Reveal nor a Copy action — Revoke lives in the kebab', async () => {
    setRows([makeRow({ id: 'key-public', key_alias: 'old-key' })]);
    render(<KeysTable onDelete={vi.fn()} />);

    expect(screen.queryByRole('button', { name: 'Reveal' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Copy' })).not.toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole('button', { name: 'More actions' }), {
      key: 'Enter',
    });
    expect(
      await screen.findByRole('menuitem', { name: 'Revoke key' })
    ).toBeInTheDocument();
  });

  it('truncates a long id to 16 chars + ellipsis — never the full id', () => {
    setRows([makeRow({ id: 'key-0123456789abcdef', key_alias: null })]);
    render(<KeysTable onDelete={vi.fn()} />);

    expect(screen.getByText('key-0123456789ab…')).toBeInTheDocument();
    expect(screen.queryByText('key-0123456789abcdef')).not.toBeInTheDocument();
  });
});

describe('KeysTable — delete action', () => {
  it('choosing Revoke in the kebab calls onDelete with that row', async () => {
    const onDelete = vi.fn();
    const row = makeRow({ id: 'key-del' });
    setRows([row]);

    render(<KeysTable onDelete={onDelete} />);
    fireEvent.keyDown(screen.getByRole('button', { name: 'More actions' }), {
      key: 'Enter',
    });
    const item = await screen.findByRole('menuitem', { name: 'Revoke key' });
    fireEvent.keyDown(item, { key: 'Enter' });

    expect(onDelete).toHaveBeenCalledTimes(1);
    expect(onDelete).toHaveBeenCalledWith(row);
  });
});

describe('KeysTable — keys minted elsewhere', () => {
  it('hides external keys by default behind a count toggle', () => {
    setRows([makeRow({ id: 'key-own', key_alias: 'mine' }), makeRow({ id: 'ekid_01', key_alias: 'ach-bot', managed: false })]);
    render(<KeysTable onDelete={vi.fn()} />);
    expect(screen.getByText('mine')).toBeInTheDocument();
    expect(screen.queryByText('ach-bot')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Show external keys (1)' }));
    expect(screen.getByText('ach-bot')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Hide external keys' }));
    expect(screen.queryByText('ach-bot')).not.toBeInTheDocument();
  });

  it('shows no external toggle when the user has no external keys', () => {
    setRows([makeRow({ id: 'key-own' })]);
    const { container } = render(<KeysTable onDelete={vi.fn()} />);
    expect(container.querySelector('[data-slot="keys-external-toggle"]')).toBeNull();
  });

  it('an unmanaged (foreign) key locks its kebab to Disable only', async () => {
    setRows([makeRow({ id: 'ekid_01', managed: false })]);
    render(<KeysTable onDelete={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /Show external keys/ }));
    fireEvent.keyDown(screen.getByRole('button', { name: 'More actions' }), {
      key: 'Enter',
    });
    await screen.findByRole('menuitem', { name: 'Managed externally' });
    // Disable is still allowed; the three management actions are gone.
    expect(screen.getByRole('menuitem', { name: 'Disable key' })).toBeInTheDocument();
    expect(screen.queryByRole('menuitem', { name: /Revoke/ })).not.toBeInTheDocument();
  });

  it('marks a foreign key EXTERNAL so its missing actions are explained', () => {
    setRows([makeRow({ id: 'ekid_01', managed: false })]);
    const { container } = render(<KeysTable onDelete={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: /Show external keys/ }));
    expect(container.querySelector('[data-slot="key-external-badge"]')).toBeInTheDocument();
  });

  it('leaves a key minted here unmarked', () => {
    setRows([makeRow({ id: 'key-abc123', managed: true })]);
    const { container } = render(<KeysTable onDelete={vi.fn()} />);
    expect(container.querySelector('[data-slot="key-external-badge"]')).not.toBeInTheDocument();
  });

  it('shows no Team column — every key a user can act on is in their own team', () => {
    setRows([makeRow({ team_id: 'user-alice@example.com' })]);
    render(<KeysTable onDelete={vi.fn()} />);
    expect(screen.queryByRole('columnheader', { name: /Team/i })).not.toBeInTheDocument();
  });

  it('hides the nudge once a default exists', () => {
    setRows([
      makeRow({ id: 'key-1' }),
      makeRow({ id: 'key-2' }),
    ]);
    render(<KeysTable onDelete={vi.fn()} />);
    expect(screen.queryByText(/No default key set/i)).not.toBeInTheDocument();
  });

  it('shows no nudge in the empty state', () => {
    setRows([]);
    render(<KeysTable onDelete={vi.fn()} />);
    expect(screen.queryByText(/No default key set/i)).not.toBeInTheDocument();
  });
});

describe('KeysTable — disable / enable (LiteLLM block)', () => {
  it('an enabled key offers "Disable key"; choosing it fires toggleBlock(blocked:true)', async () => {
    setRows([makeRow({ id: 'key-x', blocked: false })]);
    render(<KeysTable onDelete={vi.fn()} />);
    fireEvent.keyDown(screen.getByRole('button', { name: 'More actions' }), { key: 'Enter' });
    const item = await screen.findByRole('menuitem', { name: 'Disable key' });
    fireEvent.keyDown(item, { key: 'Enter' });
    expect(toggleBlockMutate).toHaveBeenCalledWith({ id: 'key-x', blocked: true });
  });

  it('dims the disabled key row so it reads as inactive', () => {
    setRows([makeRow({ id: 'key-x', blocked: true })]);
    const { container } = render(<KeysTable onDelete={vi.fn()} />);
    const row = container.querySelector('[data-slot="data-table-row"]');
    expect(row?.className).toContain('opacity-40');
  });

  it('a disabled key shows the "Disabled" status and offers "Enable key"', async () => {
    setRows([makeRow({ id: 'key-x', blocked: true })]);
    render(<KeysTable onDelete={vi.fn()} />);
    expect(screen.getByText('Disabled')).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole('button', { name: 'More actions' }), { key: 'Enter' });
    const item = await screen.findByRole('menuitem', { name: 'Enable key' });
    fireEvent.keyDown(item, { key: 'Enter' });
    expect(toggleBlockMutate).toHaveBeenCalledWith({ id: 'key-x', blocked: false });
  });
});

describe('KeysTable — no team management', () => {
  it('offers no Change team action: a key can only live in its owner\'s team', async () => {
    setRows([makeRow({ id: 'key-x', team_id: 'user-alice@example.com' })]);
    render(<KeysTable onDelete={vi.fn()} />);

    fireEvent.keyDown(screen.getByRole('button', { name: 'More actions' }), {
      key: 'Enter',
    });
    // The menu opened (Disable key is present) but Change team is absent.
    await screen.findByRole('menuitem', { name: 'Disable key' });
    expect(
      screen.queryByRole('menuitem', { name: /Change team/ })
    ).not.toBeInTheDocument();
  });
});
