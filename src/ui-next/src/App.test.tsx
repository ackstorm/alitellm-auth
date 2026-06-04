// App.test.tsx — smoke tests for the 5-state shell driver (Task 2.4).
//
// Strategy: drive the driver by setting the Zustand stores DIRECTLY via
// setState (no real fetch). The boot effect's loadSession/loadConfig are
// replaced with vi.fn() spies so mounting App does NOT hit the network and we
// can assert the error-retry calls loadSession. resolveState maps:
//
//   status null              -> loading  -> LoadingCard
//   401 & !hasLoaded         -> signin   -> Login (CTA -> /api/oauth/login?action=ui)
//   0 / 5xx                  -> error    -> ErrorCard (retry calls loadSession; disabled when status===null)
//   200 & me                 -> authed   -> AppShell (brand + email + sign out -> /api/oauth/logout)
//   200 & me === null        -> authed   -> ErrorCard (C2 fall-through)
//
// Each test resets BOTH stores to a known state in beforeEach so they stay
// deterministic and isolated.

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen, fireEvent, waitFor } from '@testing-library/react';
import { App } from './App';
import { useSessionStore, initialSessionState } from './stores/session';
import { useConfigStore, initialConfigState, DEFAULT_CONFIG } from './stores/config';
import type { SessionMe } from './lib/api-types';

const ME: SessionMe = {
  email: 'alice@example.com',
  name: 'Alice Example',
  team_id: 'team-platform',
  endpoint: 'https://litellm.example.com',
  limits: null,
  spend: { current: 0, source: 'user' },
};

// Spies stand in for the store boot actions so mounting App never fetches.
let loadSessionSpy: ReturnType<typeof vi.fn>;
let loadConfigSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  loadSessionSpy = vi.fn();
  loadConfigSpy = vi.fn();
  // Replace whole state, re-supplying the (spied) actions.
  useSessionStore.setState(
    { ...initialSessionState, loadSession: loadSessionSpy },
    true,
  );
  useConfigStore.setState(
    { ...initialConfigState, loadConfig: loadConfigSpy },
    true,
  );
});

afterEach(() => {
  cleanup();
  // Reset the hash so hash-router tests stay isolated (a leftover #/garbage or
  // #/stats would leak into the next render).
  window.location.hash = '';
});

describe('App driver — boot', () => {
  it('calls loadSession and loadConfig once on mount', () => {
    render(<App />);
    expect(loadSessionSpy).toHaveBeenCalledTimes(1);
    expect(loadConfigSpy).toHaveBeenCalledTimes(1);
  });
});

describe('App driver — loading', () => {
  it('status null -> LoadingCard with locked copy', () => {
    render(<App />); // initial status is null
    expect(screen.getByText('INITIALIZING')).toBeInTheDocument();
    expect(screen.getByText('Connecting to alitellm-auth...')).toBeInTheDocument();
  });
});

describe('App driver — signin', () => {
  it('cold-load 401 -> Login with CTA pointing at /api/oauth/login?action=ui', () => {
    useSessionStore.setState({ status: 401, hasLoaded: false, me: null });
    render(<App />);
    const cta = screen.getByRole('link', { name: 'Sign in' });
    expect(cta).toHaveAttribute('href', '/api/oauth/login?action=ui');
  });
});

describe('App driver — error', () => {
  it('network failure (status 0) -> ErrorCard, retry calls loadSession', () => {
    useSessionStore.setState({ status: 0, hasLoaded: false, me: null });
    render(<App />);
    expect(screen.getByText('Service Unavailable')).toBeInTheDocument();

    const retry = screen.getByRole('button', { name: 'retry' });
    // status is 0 (not null) -> not retrying -> button enabled.
    expect(retry).not.toBeDisabled();

    loadSessionSpy.mockClear(); // ignore the boot-effect call
    fireEvent.click(retry);
    expect(loadSessionSpy).toHaveBeenCalledTimes(1);
  });

  it('5xx -> ErrorCard, retry enabled (status !== null)', () => {
    useSessionStore.setState({ status: 503, hasLoaded: false, me: null });
    render(<App />);
    const retry = screen.getByRole('button', { name: 'retry' });
    expect(retry).not.toBeDisabled(); // status 503 !== null
  });
});

describe('App driver — authed', () => {
  it('200 + me -> AppShell shows brand, email and sign-out link', () => {
    useSessionStore.setState({ status: 200, hasLoaded: true, me: ME });
    render(<App />);
    // Two-tone brand: base "alitellm" + accent "-auth" -> the full string is
    // present split across spans; assert the base + accent pieces.
    expect(screen.getByText('alitellm')).toBeInTheDocument();
    expect(screen.getByText('-auth')).toBeInTheDocument();
    // User-menu label prefers name.
    expect(screen.getByText(ME.name)).toBeInTheDocument();
    const signOut = screen.getByRole('link', { name: 'sign out' });
    expect(signOut).toHaveAttribute('href', '/api/oauth/logout');
    // Dashboard stub mounts in the content slot.
    expect(screen.getByText('Keys — coming in Phase 3')).toBeInTheDocument();
  });

  it('C2: 200 but me === null -> ErrorCard (never renders the shell)', () => {
    useSessionStore.setState({ status: 200, hasLoaded: true, me: null });
    render(<App />);
    expect(screen.getByText('Service Unavailable')).toBeInTheDocument();
    // The shell must NOT have mounted (no sign-out link).
    expect(screen.queryByRole('link', { name: 'sign out' })).toBeNull();
  });

  it('unknown hash (#/garbage) redirects to the index Dashboard', async () => {
    // Regression for the `*` route: an unknown hash must Navigate to "/" so the
    // index Dashboard renders, not an empty <Outlet/> with a blank main region.
    window.location.hash = '#/garbage';
    useSessionStore.setState({ status: 200, hasLoaded: true, me: ME });
    render(<App />);
    // The Navigate redirect is a client-side navigation; wait for the index
    // Dashboard stub to mount in the content slot (proves we landed on "/").
    await waitFor(() =>
      expect(screen.getByText('Keys — coming in Phase 3')).toBeInTheDocument(),
    );
  });
});

describe('App driver — active nav (aria-current)', () => {
  it('Stats NavLink has aria-current="page" at /stats, not at /', () => {
    // At the index route the Stats link is NOT current.
    useSessionStore.setState({ status: 200, hasLoaded: true, me: ME });
    const { unmount } = render(<App />);
    expect(screen.getByRole('link', { name: 'Stats' })).not.toHaveAttribute(
      'aria-current',
    );
    unmount();
    cleanup();

    // At #/stats react-router v7 sets aria-current="page" on the active NavLink.
    window.location.hash = '#/stats';
    useSessionStore.setState({ status: 200, hasLoaded: true, me: ME });
    render(<App />);
    expect(screen.getByRole('link', { name: 'Stats' })).toHaveAttribute(
      'aria-current',
      'page',
    );
  });
});

describe('App driver — brand lockup (empty accent_segment)', () => {
  it('empty accent_segment renders the whole brand with no accent span', () => {
    useSessionStore.setState({ status: 200, hasLoaded: true, me: ME });
    useConfigStore.setState({
      config: { ...DEFAULT_CONFIG, brand: 'ACKStorm', accent_segment: '' },
    });
    render(<App />);
    // Whole brand renders as one string; no "-auth" accent span.
    expect(screen.getByText('ACKStorm')).toBeInTheDocument();
    expect(screen.queryByText('-auth')).toBeNull();
  });
});
