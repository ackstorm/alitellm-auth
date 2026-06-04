// footer.js — the shared SiteFooter component (Preact + htm, no JSX).
//
// SINGLE shared footer reused by BOTH the dashboard surface (AuthedShell, this
// phase Plan 01) and the login surface (Plan 02 reuses it) per UI-SPEC §C8
// ("Dashboard footer (D-03)" — "May reuse the login footer component"). Factored
// once here so neither surface duplicates footer markup.
//
// Renders:
//   • ALWAYS the © line: `© {year} {config.brand}. All rights reserved.`
//     where {config.brand} is a Preact TEXT child (htm auto-escapes — never raw
//     HTML, threat T-10-14). Default brand `alitellm-auth`.
//   • On the right, `Privacy Policy` (→ config.links.privacy) and
//     `Terms of Service` (→ config.links.terms) anchors rendered ONLY when their
//     targets exist and are non-empty (real-links-only D-03). A missing/null
//     target DROPS that link entirely (no dead/404 anchor). When neither exists
//     the © line renders alone. `href` values come ONLY from config.links (a
//     server-controlled allow-list), never user input (threat T-09-17).
import { h } from "preact";
import htm from "htm";

const html = htm.bind(h);

// Footer divider = --border; footer copy = Body 14px (UI-SPEC §"Color"). Bottom
// row layout: © left, links right. var(--*) tokens ONLY — no raw hex, no new
// design tokens.
export const FOOTER_CSS = `
.site-footer {
  display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: var(--space-sm);
  margin-top: var(--space-lg);
  padding-top: var(--space-md);
  border-top: 1px solid var(--border);
  font-family: var(--sans); font-size: 14px; color: var(--dim);
}
.site-footer .footer-copy { color: var(--dim); }
.site-footer .footer-links { display: inline-flex; align-items: center; gap: var(--space-md); margin-left: auto; }
.site-footer .footer-links a { color: var(--dim); text-decoration: none; }
.site-footer .footer-links a:hover { color: var(--text); }
`;

// SiteFooter({ config }) — config is defended to a minimal shape so a missing
// prop never crashes (brand falls back to alitellm-auth, links to {}).
export function SiteFooter({ config }) {
  const cfg = config || {};
  const brand = cfg.brand || "alitellm-auth";
  const links = cfg.links || {};
  const year = new Date().getFullYear();
  const hasPrivacy = Boolean(links.privacy);
  const hasTerms = Boolean(links.terms);
  return html`
    <footer class="site-footer">
      <span class="footer-copy">© ${year} ${brand}. All rights reserved.</span>
      ${hasPrivacy || hasTerms
        ? html`<span class="footer-links">
            ${hasPrivacy
              ? html`<a href=${links.privacy} target="_blank" rel="noopener noreferrer">Privacy Policy</a>`
              : null}
            ${hasTerms
              ? html`<a href=${links.terms} target="_blank" rel="noopener noreferrer">Terms of Service</a>`
              : null}
          </span>`
        : null}
    </footer>
  `;
}
