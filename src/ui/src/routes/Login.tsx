// Login.tsx — the OIDC sign-in landing (Task 2.5).
//
// Ported from src/ui/login.js: a config-aware topbar (brand lockup + tagline +
// Docs/Status/Support nav) ABOVE a single CENTERED Sign-in card, with the shared
// SiteFooter below. The card shows the READY status row, brand shield, "Sign in"
// heading, the config-aware sub copy, the `Continue with SSO` accent CTA, a
// reassurance line, and the labeled "BACKED BY" provider chips. (The former
// right-hand value-props / OVERVIEW teaser column was removed — the card now
// stands alone, centered.)
//
// SECURITY INVARIANTS (parity with login.js / threat register 09-06 / 14):
//   • T-09-17 (open-redirect): the `Continue with SSO` CTA is the ONLY redirect
//     trigger and points at the FIXED literal /api/oauth/login?action=ui — it is
//     NEVER built from a prop/query/next/hash. Docs/Status/Support + footer links
//     come ONLY from the server-sourced config.links allow-list (a missing target
//     DROPS the link, never interpolates).
//   • T-09-18 (pre-auth data leak): this component performs NO fetch and renders
//     NO live data. The BACKED BY chips are hardcoded illustrative content.
//   • T-10-14 (XSS): all brand/tagline/link/provider strings render as React text
//     children (auto-escaped); href values come only from config.links.

import type { AppConfig } from '@/lib/api-types';
import { Button } from '@/components/ui/button';
import { BrandLockup } from '@/components/layout/BrandLockup';
import { SiteFooter } from '@/components/layout/SiteFooter';
import { ProviderChips } from '@/components/auth/ProviderChips';

// The SOLE redirect trigger (T-09-17). FIXED literal — the ?action=ui param makes
// the callback eager-create the LiteLLM user WITHOUT minting a key (D-13). Never
// construct this from any prop/query/next/hash.
const SSO_LOGIN_URL = '/api/oauth/login?action=ui';

export interface LoginProps {
  config: AppConfig;
}

export function Login({ config }: LoginProps) {
  const links = config.links ?? {};
  const brandShort = config.brand_short || 'LiteLLM';
  const providerLabel = config.provider_label || 'dex';
  const tagline = config.tagline || '';
  const providers =
    Array.isArray(config.providers) && config.providers.length
      ? config.providers
      : [];

  return (
    <div
      data-state="signin"
      className="flex min-h-screen flex-col bg-background [background-image:radial-gradient(ellipse_80%_50%_at_50%_-20%,var(--accent),transparent),radial-gradient(circle_at_80%_80%,rgba(74,222,128,0.03),transparent)]"
    >
      {/* ── Topbar — full-width bar (mirrors the authed shell): brand lockup +
          tagline on the left, real-links nav on the right. ──────────────────── */}
      <header className="flex h-14 shrink-0 items-center gap-4 border-b border-border bg-surface px-6">
        <div className="inline-flex flex-col gap-px">
          <BrandLockup config={config} className="text-sm" />
          {tagline ? (
            <span className="font-sans text-[11px] text-text-secondary">
              {tagline}
            </span>
          ) : null}
        </div>

        <nav
          aria-label="Resources"
          className="ml-auto flex items-center gap-6 font-mono text-[11px] font-semibold uppercase tracking-wider"
        >
          {links.docs ? (
            <a
              href={links.docs}
              target="_blank"
              rel="noopener noreferrer"
              className="text-text-secondary transition-colors hover:text-text-primary"
            >
              Docs
            </a>
          ) : null}
          {links.status ? (
            <a
              href={links.status}
              target="_blank"
              rel="noopener noreferrer"
              className="text-text-secondary transition-colors hover:text-text-primary"
            >
              Status
            </a>
          ) : null}
          {links.support ? (
            <a
              href={links.support}
              target="_blank"
              rel="noopener noreferrer"
              className="text-text-secondary transition-colors hover:text-text-primary"
            >
              Support
            </a>
          ) : null}
        </nav>
      </header>

      {/* ── Body — a single, centered Sign-in card ─────────────────────────────── */}
      <div className="flex flex-1 items-center justify-center px-6 py-12">
        <main className="w-full max-w-[480px] rounded-xl border border-border bg-card shadow-sm">
          <div className="border-b border-border px-8 pt-8 pb-6">
            <div className="mb-4 flex items-center gap-2.5">
              <span
                aria-hidden="true"
                className="size-2 animate-pulse rounded-full bg-primary shadow-[0_0_8px_var(--primary)]"
              />
              <span className="font-mono text-xs font-semibold tracking-widest text-primary">
                READY
              </span>
            </div>
            <BrandLockup
              config={config}
              className="text-2xl tracking-tight"
              iconClassName="size-[26px]"
            />
            <h1 className="mt-4 text-2xl font-semibold leading-tight text-text-primary">
              Sign in
            </h1>
            <p className="mt-4 text-sm text-text-secondary">
              Authenticate with your organization account to manage your{' '}
              {brandShort} API keys.
            </p>
          </div>

          <div className="px-8 py-7">
            <Button asChild className="w-full">
              <a href={SSO_LOGIN_URL}>
                <svg
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                  className="fill-none"
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4" />
                  <path d="M10 17l5-5-5-5" />
                  <path d="M15 12H3" />
                </svg>
                Continue with SSO
              </a>
            </Button>

            <p className="mt-4 text-sm text-text-secondary">
              Secure, seamless access powered by your identity provider.
            </p>

            <ProviderChips providers={providers} />
          </div>

          <div className="flex items-center gap-4 border-t border-border px-8 py-5 font-mono text-[11px] text-text-secondary">
            <span className="inline-flex items-center gap-2">
              <svg
                viewBox="0 0 24 24"
                aria-hidden="true"
                className="size-[15px] fill-none stroke-text-secondary"
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <rect x="3" y="11" width="18" height="11" rx="2" />
                <path d="M7 11V7a5 5 0 0110 0v4" />
              </svg>
              no password stored here
            </span>
            <span className="ml-auto">
              redirects to <b className="text-text-primary">{providerLabel}</b>
            </span>
          </div>
        </main>
      </div>

      {/* ── Shared footer — the SAME transversal SiteFooter as the authed pages,
          so login and the inner pages stay coherent (full-width bar, © line +
          real-links-only Privacy/Terms). ───────────────────────────────────── */}
      <SiteFooter config={config} />
    </div>
  );
}
