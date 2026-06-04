// Login.test.tsx — the sign-in placeholder: brand lockup + single CTA pointing
// at the FIXED /api/oauth/login?action=ui literal (the only redirect trigger).

import { afterEach, describe, expect, it } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import { Login } from './Login';
import { DEFAULT_CONFIG } from '@/stores/config';

afterEach(() => cleanup());

describe('Login', () => {
  it('CTA links to /api/oauth/login?action=ui', () => {
    render(<Login config={DEFAULT_CONFIG} />);
    const cta = screen.getByRole('link', { name: 'Sign in' });
    expect(cta).toHaveAttribute('href', '/api/oauth/login?action=ui');
  });

  it('renders the two-tone brand lockup (base + accent)', () => {
    render(<Login config={DEFAULT_CONFIG} />);
    expect(screen.getByText('alitellm')).toBeInTheDocument();
    expect(screen.getByText('-auth')).toBeInTheDocument();
  });
});
