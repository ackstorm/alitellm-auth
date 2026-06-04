// RightSidebar.test.tsx — vitest suite for the authed right sidebar (jsdom).
//
// RightSidebar calls useNavigate(), so it is rendered inside a MemoryRouter.
// The create-key-modal store is the REAL store (reset between tests) so the
// `Create key` click can be asserted via its live `open` flag. The docs link
// renders only when config.links.docs is set (real-links-only).

import { afterEach, beforeEach, describe, expect, it } from 'vitest';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';

import type { AppConfig } from '@/lib/api-types';
import { RightSidebar } from './RightSidebar';
import {
  initialCreateKeyModalState,
  useCreateKeyModalStore,
} from '@/stores/create-key-modal';

// A minimal valid AppConfig with overridable links.
function makeConfig(overrides: Partial<AppConfig> = {}): AppConfig {
  return {
    brand: 'alitellm-auth',
    brand_short: 'LiteLLM',
    tagline: '',
    accent_segment: '-auth',
    provider_label: 'dex',
    public_host: '',
    providers: [],
    links: {},
    ...overrides,
  };
}

function renderSidebar(config: AppConfig) {
  return render(
    <MemoryRouter>
      <RightSidebar config={config} />
    </MemoryRouter>,
  );
}

beforeEach(() => {
  // Reset the create-key-modal store to closed, preserving its actions.
  const { openModal, closeModal } = useCreateKeyModalStore.getState();
  useCreateKeyModalStore.setState(
    { ...initialCreateKeyModalState, openModal, closeModal },
    true,
  );
});

afterEach(() => {
  cleanup();
});

describe('RightSidebar — panels', () => {
  it('renders the three panel labels', () => {
    renderSidebar(makeConfig());
    expect(screen.getByText('QUICK ACTIONS')).toBeInTheDocument();
    expect(screen.getByText('SECURITY')).toBeInTheDocument();
    expect(screen.getByText('NEED HELP?')).toBeInTheDocument();
  });

  it('renders the SECURITY copy verbatim', () => {
    renderSidebar(makeConfig());
    expect(
      screen.getByText(
        'Keys are shown once. Store them securely. Rotate any compromised key from the table.',
      ),
    ).toBeInTheDocument();
  });

  it('renders the NEED HELP? plain copy when no docs link is set', () => {
    renderSidebar(makeConfig({ links: {} }));
    expect(
      screen.getByText('See the endpoint reference and docs.'),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole('link', { name: 'endpoint reference and docs' }),
    ).not.toBeInTheDocument();
  });
});

describe('RightSidebar — quick actions', () => {
  it('clicking "Create key" opens the create-key modal (store open === true)', () => {
    renderSidebar(makeConfig());
    expect(useCreateKeyModalStore.getState().open).toBe(false);
    fireEvent.click(screen.getByRole('button', { name: 'Create key' }));
    expect(useCreateKeyModalStore.getState().open).toBe(true);
  });

  it('renders the "View stats" button', () => {
    renderSidebar(makeConfig());
    expect(
      screen.getByRole('button', { name: 'View stats' }),
    ).toBeInTheDocument();
  });
});

describe('RightSidebar — docs link (real-links-only)', () => {
  it('renders the docs anchor only when config.links.docs is set', () => {
    renderSidebar(makeConfig({ links: { docs: 'https://docs.example.com' } }));
    const docs = screen.getByRole('link', { name: 'endpoint reference and docs' });
    expect(docs).toHaveAttribute('href', 'https://docs.example.com');
    expect(docs).toHaveAttribute('target', '_blank');
    expect(docs).toHaveAttribute('rel', 'noopener noreferrer');
  });
});
