// AppShell.test.tsx — vitest suite for the authed shell's CHAT nav gating.
//
// useKeys is mocked so the shell renders deterministically without a real fetch.
// The CHAT nav item is set apart and gated on the user having a default key:
//   • a default exists -> an external link to chat.<domain>
//   • no default       -> a disabled, non-link span with a "need a default key" hint

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { UseQueryResult } from '@tanstack/react-query';
import { cleanup, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';

// AppShell mounts CreateKeyModal (which calls useCreateKey), so the mock must
// export it too — a benign stub, since the modal is idle/closed in these tests.
vi.mock('@/hooks/use-keys', () => ({
  useKeys: vi.fn(),
  useCreateKey: vi.fn(() => ({
    mutate: vi.fn(),
    mutateAsync: vi.fn(),
    isPending: false,
    reset: vi.fn(),
  })),
  KEYS_QUERY_KEY: ['session', 'keys'],
}));

import { useKeys } from '@/hooks/use-keys';
import type { AppConfig, KeyRow, SessionMe } from '@/lib/api-types';
import { AppShell } from './AppShell';

const useKeysMock = vi.mocked(useKeys);

const ME: SessionMe = {
  email: 'alice@example.com',
  name: 'Alice Example',
  team_id: 'team-platform',
  endpoint: 'https://api.acme.ai',
  limits: null,
  spend: { current: 0, source: 'user' },
};

const CONFIG = { links: {} } as unknown as AppConfig;

function setKeys(rows: KeyRow[] | undefined): void {
  useKeysMock.mockReturnValue({ data: rows } as unknown as UseQueryResult<KeyRow[]>);
}

function makeRow(overrides: Partial<KeyRow> = {}): KeyRow {
  return {
    id: 'key-1',
    key_alias: 'k',
    spend: 0,
    budget: null,
    tpm_limit: null,
    rpm_limit: null,
    models: null,
    created_at: null,
    expires: null,
    is_default: false,
    ...overrides,
  };
}

function renderShell(): void {
  render(
    <MemoryRouter>
      <AppShell me={ME} config={CONFIG} />
    </MemoryRouter>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

beforeEach(() => {
  setKeys([]);
});

describe('AppShell — CHAT nav gating', () => {
  it('with a default key, CHAT is an external link to chat.<domain>', () => {
    setKeys([makeRow({ id: 'key-1', is_default: true })]);
    renderShell();
    const link = screen.getByRole('link', { name: 'Chat' });
    expect(link).toHaveAttribute('href', 'https://chat.acme.ai');
    expect(link).toHaveAttribute('target', '_blank');
  });

  it('without a default key, CHAT is disabled (no link) with a hint', () => {
    setKeys([makeRow({ id: 'key-1', is_default: false })]);
    renderShell();
    expect(screen.queryByRole('link', { name: 'Chat' })).not.toBeInTheDocument();
    const disabled = screen.getByText('Chat');
    expect(disabled).toHaveAttribute('aria-disabled', 'true');
    expect(disabled).not.toHaveAttribute('href');
    expect(disabled.getAttribute('title') ?? '').toMatch(/default key/i);
  });

  it('treats an undefined keys list as no default', () => {
    setKeys(undefined);
    renderShell();
    expect(screen.queryByRole('link', { name: 'Chat' })).not.toBeInTheDocument();
    expect(screen.getByText('Chat')).toHaveAttribute('aria-disabled', 'true');
  });
});
