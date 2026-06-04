// RightSidebar.tsx — the authenticated shell's RIGHT SIDEBAR, ported from
// src/ui/sidebar.js (Preact + htm -> React + Tailwind tokens).
//
// Three panels per UI-SPEC §B "Right sidebar panels (D-08 scope)":
//   • QUICK ACTIONS (PRIMARY) — a `Create key` shortcut that opens the SAME
//     store-driven create modal as the dashboard `+ New Key` CTA (via
//     useCreateKeyModalStore.openModal — replaces the old onCreateKey prop
//     indirection; it calls NO /keys endpoint here, threat T-09-15), plus a
//     `View stats` shortcut that navigates to the reserved /stats route via
//     react-router's useNavigate (this renders inside the RouterProvider, so we
//     do NOT poke window.location.hash).
//   • SECURITY (MINIMAL) — static reassurance copy, no interactive controls.
//   • NEED HELP? (MINIMAL) — a single static line; the docs link renders ONLY
//     when config.links.docs is set (real-links-only D-02/C7). Anchors render as
//     React text children (auto-escaped — never raw HTML, threat T-10-14).
//
// Its root IS the <aside> (AppShell renders it directly, no nested aside).
// Width 320px, full-width below the 1024px breakpoint.

import { useNavigate } from 'react-router';

import type { AppConfig } from '@/lib/api-types';
import { useCreateKeyModalStore } from '@/stores/create-key-modal';

export interface RightSidebarProps {
  config: AppConfig;
}

export function RightSidebar({ config }: RightSidebarProps) {
  const navigate = useNavigate();
  const openModal = useCreateKeyModalStore((s) => s.openModal);
  const docs = config.links?.docs || null;

  return (
    <aside className="flex w-[320px] shrink-0 flex-col gap-4 max-[1024px]:w-full">
      {/* QUICK ACTIONS (primary) */}
      <div className="flex flex-col gap-3 rounded-xl border border-border bg-surface p-5">
        <div className="font-mono text-[11px] font-semibold uppercase tracking-widest text-text-secondary">
          QUICK ACTIONS
        </div>
        <button
          type="button"
          onClick={openModal}
          className="inline-flex items-center justify-center rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90"
        >
          Create key
        </button>
        <button
          type="button"
          onClick={() => navigate('/stats')}
          className="inline-flex items-center justify-center rounded-lg border border-border bg-background px-4 py-2 text-sm font-semibold text-text-primary transition-colors hover:border-border-bright"
        >
          View stats
        </button>
      </div>

      {/* SECURITY (minimal) */}
      <div className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-5">
        <div className="font-mono text-[11px] font-semibold uppercase tracking-widest text-text-secondary">
          SECURITY
        </div>
        <p className="text-sm leading-relaxed text-text-secondary">
          Keys are shown once. Store them securely. Rotate any compromised key from
          the table.
        </p>
      </div>

      {/* NEED HELP? (minimal) */}
      <div className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-5">
        <div className="font-mono text-[11px] font-semibold uppercase tracking-widest text-text-secondary">
          NEED HELP?
        </div>
        <p className="text-sm leading-relaxed text-text-secondary">
          {docs ? (
            <>
              See the{' '}
              <a
                href={docs}
                target="_blank"
                rel="noopener noreferrer"
                className="text-primary transition-colors hover:opacity-90"
              >
                endpoint reference and docs
              </a>
              .
            </>
          ) : (
            'See the endpoint reference and docs.'
          )}
        </p>
      </div>
    </aside>
  );
}
