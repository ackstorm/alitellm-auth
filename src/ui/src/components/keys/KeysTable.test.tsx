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

import type { KeyRow, MakeDefaultResponse } from '@/lib/api-types';

// Mock the data hook — each test sets useKeys's return value.
vi.mock('@/hooks/use-keys', () => ({
  useKeys: vi.fn(),
  useMakeDefault: vi.fn(),
  KEYS_QUERY_KEY: ['session', 'keys'],
}));

import { useKeys, useMakeDefault } from '@/hooks/use-keys';
import { KeysTable } from './KeysTable';

const useKeysMock = vi.mocked(useKeys);
const useMakeDefaultMock = vi.mocked(useMakeDefault);

// A reusable mutation stub; reset per test via beforeEach.
let makeDefaultMutate: ReturnType<typeof vi.fn>;
beforeEach(() => {
  makeDefaultMutate = vi.fn();
  useMakeDefaultMock.mockReturnValue({
    mutate: makeDefaultMutate,
  } as unknown as UseMutationResult<MakeDefaultResponse, Error, string>);
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
    created_at: '2026-03-01T10:00:00+00:00',
    expires: null,
    is_default: false,
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
  it('renders neither a Reveal nor a Copy action — Revoke is the only per-row button', () => {
    setRows([makeRow({ id: 'key-public', key_alias: 'old-key' })]);
    render(<KeysTable onDelete={vi.fn()} />);

    expect(screen.queryByRole('button', { name: 'Reveal' })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Copy' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Revoke' })).toBeInTheDocument();
  });

  it('truncates a long id to 16 chars + ellipsis — never the full id', () => {
    setRows([makeRow({ id: 'key-0123456789abcdef', key_alias: null })]);
    render(<KeysTable onDelete={vi.fn()} />);

    expect(screen.getByText('key-0123456789ab…')).toBeInTheDocument();
    expect(screen.queryByText('key-0123456789abcdef')).not.toBeInTheDocument();
  });
});

describe('KeysTable — delete action', () => {
  it('clicking Revoke calls onDelete with that row', () => {
    const onDelete = vi.fn();
    const row = makeRow({ id: 'key-del' });
    setRows([row]);

    render(<KeysTable onDelete={onDelete} />);
    fireEvent.click(screen.getByRole('button', { name: 'Revoke' }));

    expect(onDelete).toHaveBeenCalledTimes(1);
    expect(onDelete).toHaveBeenCalledWith(row);
  });
});

describe('KeysTable — default key', () => {
  it('shows a DEFAULT badge on the default key only', () => {
    setRows([
      makeRow({ id: 'key-default', key_alias: 'default-key', is_default: true }),
      makeRow({ id: 'key-other', key_alias: 'other-key', is_default: false }),
    ]);
    render(<KeysTable onDelete={vi.fn()} />);
    expect(screen.getAllByText('DEFAULT')).toHaveLength(1);
  });

  it('a non-default key exposes an enabled "Make default" control', () => {
    setRows([makeRow({ id: 'key-other', is_default: false })]);
    render(<KeysTable onDelete={vi.fn()} />);
    const btn = screen.getByRole('button', { name: 'Make default' });
    expect(btn).toBeEnabled();
  });

  it('clicking "Make default" fires the mutation with the row id', () => {
    setRows([makeRow({ id: 'key-other', is_default: false })]);
    render(<KeysTable onDelete={vi.fn()} />);
    fireEvent.click(screen.getByRole('button', { name: 'Make default' }));
    expect(makeDefaultMutate).toHaveBeenCalledWith('key-other');
  });

  it('the default key has no "Make default" control and a disabled Revoke', () => {
    setRows([makeRow({ id: 'key-default', is_default: true })]);
    render(<KeysTable onDelete={vi.fn()} />);
    expect(screen.queryByRole('button', { name: 'Make default' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Revoke' })).toBeDisabled();
  });
});
