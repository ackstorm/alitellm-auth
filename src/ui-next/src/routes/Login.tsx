// Login.tsx — the full two-column OIDC sign-in landing (Task 2.5).
//
// Ported from src/ui/login.js TwoColumnLogin: a config-aware topbar (brand
// lockup + tagline + public-host label + Docs/Status/Support nav) ABOVE a
// two-column body, and the shared SiteFooter below. The LEFT column is the
// centered Sign-in card (READY status row, brand shield, "Sign in" heading, the
// config-aware sub copy, the `Continue with SSO` accent CTA, a reassurance line,
// and the labeled "BACKED BY" provider chips). The RIGHT column is the
// value-props list + a clearly-illustrative `OVERVIEW · sample` teaser.
//
// SECURITY INVARIANTS (parity with login.js / threat register 09-06 / 14):
//   • T-09-17 (open-redirect): the `Continue with SSO` CTA is the ONLY redirect
//     trigger and points at the FIXED literal /api/oauth/login?action=ui — it is
//     NEVER built from a prop/query/next/hash. Docs/Status/Support + footer links
//     come ONLY from the server-sourced config.links allow-list (a missing target
//     DROPS the link, never interpolates).
//   • T-09-18 (pre-auth data leak): this component performs NO fetch and renders
//     NO live data. The OVERVIEW teaser + BACKED BY chips are hardcoded
//     illustrative content.
//   • T-10-14 (XSS): all brand/tagline/link/provider strings render as React text
//     children (auto-escaped); href values come only from config.links.

import type { AppConfig } from '@/lib/api-types';
import { Button } from '@/components/ui/button';
import { BrandLockup } from '@/components/layout/BrandLockup';
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
  const publicHost = config.public_host || '';
  const providers =
    Array.isArray(config.providers) && config.providers.length
      ? config.providers
      : [];
  const year = new Date().getFullYear();
  const hasPrivacy = Boolean(links.privacy);
  const hasTerms = Boolean(links.terms);

  return (
    <div
      data-state="signin"
      className="flex min-h-screen flex-col bg-background px-6 py-4 [background-image:radial-gradient(ellipse_80%_50%_at_50%_-20%,var(--accent),transparent),radial-gradient(circle_at_80%_80%,rgba(74,222,128,0.03),transparent)]"
    >
      {/* ── Topbar — brand lockup + tagline, centered host label, real-links nav ─ */}
      <header className="flex h-14 shrink-0 items-center gap-4 border-b border-border">
        <div className="inline-flex flex-col gap-px">
          <BrandLockup config={config} className="text-sm" />
          {tagline ? (
            <span className="font-sans text-[11px] text-text-secondary">
              {tagline}
            </span>
          ) : null}
        </div>

        {publicHost ? (
          <div className="mx-auto font-mono text-xs text-text-secondary">
            {publicHost}
          </div>
        ) : null}

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

      {/* ── Two-column body — centered, 2xl column gap, stacks under 768px ─────── */}
      <div className="flex flex-1 flex-wrap items-center justify-center gap-16 py-12 max-[768px]:flex-col max-[768px]:items-stretch max-[768px]:gap-10">
        {/* LEFT — the Sign-in card. */}
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

        {/* RIGHT — value props + illustrative OVERVIEW teaser (NO live data). */}
        <section className="w-full max-w-[480px]">
          <h2 className="mb-6 font-sans text-sm text-text-primary">
            After you sign in, you can:
          </h2>

          <ul className="space-y-6">
            <li className="flex items-start gap-4">
              <span className="inline-flex size-7 shrink-0 items-center justify-center rounded-lg border border-border bg-accent">
                <svg
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                  className="size-[15px] fill-none stroke-primary"
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M12 5v14" />
                  <path d="M5 12h14" />
                </svg>
              </span>
              <div className="min-w-0">
                <div className="font-sans text-sm font-semibold text-text-primary">
                  Create &amp; generate API keys
                </div>
                <div className="mt-0.5 font-sans text-sm text-text-secondary">
                  Generate keys scoped to your account in seconds.
                </div>
              </div>
            </li>

            <li className="flex items-start gap-4">
              <span className="inline-flex size-7 shrink-0 items-center justify-center rounded-lg border border-border bg-accent">
                <svg
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                  className="size-[15px] fill-none stroke-primary"
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M3 3v18h18" />
                  <path d="m7 14 3-4 3 2 4-6" />
                </svg>
              </span>
              <div className="min-w-0">
                <div className="font-sans text-sm font-semibold text-text-primary">
                  Review usage &amp; budgets
                </div>
                <div className="mt-0.5 font-sans text-sm text-text-secondary">
                  Monitor spend, limits, and budgets at a glance.
                </div>
              </div>
            </li>

            <li className="flex items-start gap-4">
              <span className="inline-flex size-7 shrink-0 items-center justify-center rounded-lg border border-border bg-accent">
                <svg
                  viewBox="0 0 24 24"
                  aria-hidden="true"
                  className="size-[15px] fill-none stroke-primary"
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                >
                  <path d="M3 6h18" />
                  <path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
                  <path d="m6 6 1 14a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-14" />
                </svg>
              </span>
              <div className="min-w-0">
                <div className="font-sans text-sm font-semibold text-text-primary">
                  Revoke compromised keys
                </div>
                <div className="mt-0.5 font-sans text-sm text-text-secondary">
                  Instantly revoke any key from your systems.
                </div>
              </div>
            </li>
          </ul>

          {/* OVERVIEW · sample — illustrative ONLY. All numbers are hardcoded
              placeholders; this teaser fetches nothing and shows NO live data on
              the unauthenticated screen (T-09-18). The whole teaser is decorative,
              so it is aria-hidden (parity with login.js .overview-sample). */}
          <div
            aria-hidden="true"
            className="mt-10 rounded-2xl border border-border bg-surface p-6"
          >
            <div className="mb-4 font-mono text-[11px] font-semibold uppercase tracking-[2px] text-text-secondary">
              OVERVIEW · sample
            </div>
            <div className="grid grid-cols-3 gap-2 max-[360px]:grid-cols-1">
              <div className="rounded-lg border border-border bg-background px-3 py-2">
                <div className="font-mono text-[11px] uppercase tracking-wider text-text-secondary">
                  Active keys
                </div>
                <div className="font-sans text-2xl font-semibold leading-tight text-text-primary">
                  12
                </div>
              </div>
              <div className="rounded-lg border border-border bg-background px-3 py-2">
                <div className="font-mono text-[11px] uppercase tracking-wider text-text-secondary">
                  Monthly Requests
                </div>
                <div className="font-sans text-2xl font-semibold leading-tight text-text-primary">
                  2.45M
                </div>
              </div>
              <div className="rounded-lg border border-border bg-background px-3 py-2">
                <div className="font-mono text-[11px] uppercase tracking-wider text-text-secondary">
                  Spend MTD
                </div>
                <div className="font-sans text-2xl font-semibold leading-tight text-text-primary">
                  $1,240.50
                </div>
              </div>
            </div>

            <div className="mt-4 border-t border-border pt-3">
              <div className="mb-2 font-mono text-[11px] font-semibold uppercase tracking-wider text-text-secondary">
                Recent API keys
              </div>
              <div className="flex items-center justify-between gap-4 py-1">
                <span className="font-mono text-xs text-text-secondary">
                  key-•••• 7f3a
                </span>
                <span className="inline-block rounded-full border border-primary/20 bg-accent px-2 py-1 font-mono text-[11px] font-semibold uppercase tracking-wider text-primary">
                  Active
                </span>
              </div>
              <div className="flex items-center justify-between gap-4 py-1">
                <span className="font-mono text-xs text-text-secondary">
                  key-•••• c1d8
                </span>
                <span className="inline-block rounded-full border border-primary/20 bg-accent px-2 py-1 font-mono text-[11px] font-semibold uppercase tracking-wider text-primary">
                  Active
                </span>
              </div>
              <div className="flex items-center justify-between gap-4 py-1">
                <span className="font-mono text-xs text-text-secondary">
                  key-•••• 90b2
                </span>
                <span className="inline-block rounded-full border border-border bg-surface px-2 py-1 font-mono text-[11px] font-semibold uppercase tracking-wider text-text-secondary">
                  Expired
                </span>
              </div>
            </div>
          </div>
        </section>
      </div>

      {/* ── Shared footer — © line always; real-links-only Privacy/Terms ──────── */}
      <footer className="mt-4 flex flex-wrap items-center gap-2 border-t border-border pt-4 font-sans text-sm text-text-secondary">
        <span>© {year} {config.brand}. All rights reserved.</span>
        {hasPrivacy || hasTerms ? (
          <span className="ml-auto inline-flex items-center gap-4">
            {hasPrivacy ? (
              <a
                href={links.privacy}
                target="_blank"
                rel="noopener noreferrer"
                className="text-text-secondary transition-colors hover:text-text-primary"
              >
                Privacy Policy
              </a>
            ) : null}
            {hasTerms ? (
              <a
                href={links.terms}
                target="_blank"
                rel="noopener noreferrer"
                className="text-text-secondary transition-colors hover:text-text-primary"
              >
                Terms of Service
              </a>
            ) : null}
          </span>
        ) : null}
      </footer>
    </div>
  );
}
