// SiteFooter.tsx — the shared site footer, ported from src/ui/footer.js
// (Preact + htm -> React + Tailwind tokens).
//
// Renders the © line ALWAYS, plus optional Privacy Policy / Terms of Service
// anchors on the right. Each anchor is rendered ONLY when its target is set in
// config.links (real-links-only D-03 — a missing/empty target DROPS the anchor,
// never a dead/404 link). When neither link exists the © line renders alone.
// `href` values come ONLY from config.links (server-controlled allow-list),
// never user input (threat T-09-17). All copy renders as React text children
// (auto-escaped — never raw HTML, threat T-10-14).

import type { AppConfig } from '@/lib/api-types';

export interface SiteFooterProps {
  config: AppConfig;
}

export function SiteFooter({ config }: SiteFooterProps) {
  const brand = config.brand || 'alitellm-auth';
  const links = config.links ?? {};
  const year = new Date().getFullYear();
  const privacy = links.privacy || null;
  const terms = links.terms || null;

  return (
    <footer className="mt-8 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-4 font-sans text-sm text-text-secondary">
      <span className="text-text-secondary">
        © {year} {brand}. All rights reserved.
      </span>
      {privacy || terms ? (
        <span className="ml-auto inline-flex items-center gap-4">
          {privacy ? (
            <a
              href={privacy}
              target="_blank"
              rel="noopener noreferrer"
              className="text-text-secondary transition-colors hover:text-text-primary"
            >
              Privacy Policy
            </a>
          ) : null}
          {terms ? (
            <a
              href={terms}
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
  );
}
