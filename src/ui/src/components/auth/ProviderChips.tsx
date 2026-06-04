// ProviderChips.tsx — the "BACKED BY" identity-provider chip row, ported from
// src/ui/login.js TwoColumnLogin's `.backed-by` + `.backed-by-row`.
//
// Renders one rounded chip per `config.providers` entry (a shield icon tile + the
// provider label, e.g. Google / Dex / OIDC). The chips are STATIC illustrative
// content naming which IdPs back the SSO button — NOT live auth state (T-09-18 is
// about *live* data). They are the only on-screen indication of which identity
// providers are wired.
//
// a11y (WR-04): the chips are NOT aria-hidden — they carry non-redundant text and
// must stay in the accessibility tree. Only the decorative shield SVG inside each
// chip is aria-hidden. All labels render as React text children (T-10-14 XSS).

import type { ConfigProvider } from '@/lib/api-types';

export interface ProviderChipsProps {
  providers: ConfigProvider[];
}

export function ProviderChips({ providers }: ProviderChipsProps) {
  return (
    <div>
      {/* 11px mono caption label — letter-spaced + uppercase (login.js .backed-by). */}
      <div className="mt-6 mb-2 font-mono text-[11px] font-semibold uppercase tracking-[2px] text-text-secondary">
        BACKED BY
      </div>
      {/* WR-04: no aria-hidden — these chips stay in the a11y tree. */}
      <div className="flex flex-wrap items-center gap-2">
        {providers.map((p, i) => (
          <span
            // Labels can repeat in principle; index keeps the key stable.
            key={`${p.label}-${i}`}
            className="inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1"
          >
            <span className="inline-flex size-7 shrink-0 items-center justify-center rounded-lg border border-border bg-accent">
              <svg
                viewBox="0 0 24 24"
                aria-hidden="true"
                className="size-[15px] fill-none stroke-primary"
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M12 2 4 6v6c0 4.5 3.4 7.3 8 10 4.6-2.7 8-5.5 8-10V6z" />
              </svg>
            </span>
            <span className="font-sans text-[13px] font-semibold text-text-primary">
              {p.label}
            </span>
          </span>
        ))}
      </div>
    </div>
  );
}
