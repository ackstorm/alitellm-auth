// AppShell.tsx — the authenticated WIDE shell, ported from app.js AuthedShell.
//
// A ~56px topbar (two-tone brand lockup + Stats/Status nav + connected pulse-dot
// + {name|email} + sign out), a centered ~1200px content region holding the
// matched route via <Outlet/>, and the shared footer. AppShell is just the
// chrome: each ROUTE owns its own content layout (the dashboard composes its own
// right sidebar next to a full-width keys table; /stats renders full width), so
// there is no shell-level sidebar slot to toggle per route.
//
// Real-links-only (D-02/D-03): the Status nav item renders an external anchor
// ONLY when config.links.status is set; otherwise it renders a connected
// pulse-dot label. No nav/footer anchor is built from a non-existent link.
//
// `me` is GUARANTEED non-null here (App.tsx falls through to ErrorCard when
// me === null — carry-forward C2), so the shell never renders against a null me.

import { Outlet, NavLink } from 'react-router';
import type { AppConfig, SessionMe } from '@/lib/api-types';
import { CreateKeyModal } from '@/components/keys/CreateKeyModal';
import { Toaster } from '@/components/ui/toast';
import { BrandLockup } from './BrandLockup';
import { SiteFooter } from './SiteFooter';

export interface AppShellProps {
  me: SessionMe;
  config: AppConfig;
}

export function AppShell({ me, config }: AppShellProps) {
  const links = config.links ?? {};
  // User-menu label prefers the display name, falling back to email (UI-SPEC
  // copy table). Rendered as a text child only — never raw HTML (T-10-14).
  const menuLabel = me.name || me.email;

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="flex h-14 shrink-0 items-center gap-6 border-b border-border bg-surface px-6">
        <BrandLockup config={config} className="text-sm" />

        <nav aria-label="Primary" className="flex items-center gap-6">
          <NavLink
            to="/stats"
            className={({ isActive }) =>
              [
                'border-b-2 py-1 font-mono text-[11px] font-semibold uppercase tracking-wider transition-colors',
                isActive
                  ? 'border-primary text-primary'
                  : 'border-transparent text-text-secondary hover:text-text-primary',
              ].join(' ')
            }
          >
            Stats
          </NavLink>

          {links.status ? (
            <a
              href={links.status}
              target="_blank"
              rel="noopener noreferrer"
              className="border-b-2 border-transparent py-1 font-mono text-[11px] font-semibold uppercase tracking-wider text-text-secondary transition-colors hover:text-text-primary"
            >
              Status
            </a>
          ) : (
            <span
              role="status"
              aria-label="Service status: operational"
              className="inline-flex items-center gap-1.5 font-mono text-[11px] font-semibold uppercase tracking-wider text-primary"
            >
              <span
                aria-hidden="true"
                className="size-2 animate-pulse rounded-full bg-primary shadow-[0_0_8px_var(--primary)]"
              />
              Status
            </span>
          )}
        </nav>

        <div className="ml-auto flex items-center gap-4 font-mono text-[11px]">
          <span className="text-text-primary">{menuLabel}</span>
          <a
            href="/api/oauth/logout"
            className="text-text-secondary transition-colors hover:text-text-primary"
          >
            sign out
          </a>
        </div>
      </header>

      <div className="mx-auto flex w-full max-w-[1200px] flex-1 flex-col px-6 py-8">
        {/* Routes own their own content layout: the dashboard composes its own
            right sidebar alongside a full-width keys table; /stats renders full
            width. AppShell is just the chrome (topbar + footer + overlays). */}
        <main className="min-w-0 flex-1 animate-content-in">
          <Outlet />
        </main>

        {/* Shared footer, on every authed route. */}
        <SiteFooter config={config} />
      </div>

      {/* Store-driven / queue-driven overlays mounted at the authed shell root.
          The CreateKeyModal is mounted HERE (not in the dashboard) so both the
          dashboard `+ New Key` CTA and the sidebar `Create key` shortcut open
          the SAME modal via useCreateKeyModalStore. The Toaster is mounted here
          (not at App root) because toasts only fire in authed flows (create /
          delete) and AppShell is the authed root — this scopes them correctly
          while guaranteeing they render wherever a toast can fire. Both render
          nothing when idle. */}
      <CreateKeyModal />
      <Toaster />
    </div>
  );
}
