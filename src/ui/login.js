// login.js — the two-column sign-in landing for the alitellm-auth SPA
// (Preact + htm tagged templates, no JSX, no TypeScript per 09-CONTEXT D-04).
//
// Re-composed in Phase 14 (FID-01) to match `ref-login.png`: a config-aware
// `.topbar` (brand lockup + tagline + public-host label + Docs/Status/Support
// nav) ABOVE the two-column body; a LEFT centered Sign-in card that leads with a
// `Sign in` heading, the config-aware sub copy, the `Continue with SSO` accent
// CTA, a reassurance line, and a labeled `BACKED BY` Google/Dex/OIDC chips row;
// a RIGHT value-props column + an enriched clearly-illustrative
// `OVERVIEW · sample` card (3 metric tiles + a Recent API keys mini-table); and
// the shared `SiteFooter` (Plan 01) rendered below the body.
//
// All brand/tagline/link/provider strings come from the `config` prop threaded
// by app.js (defaulted defensively so a missing prop never crashes). The
// Overview + BACKED BY chips + recent-keys rows are 100% hardcoded illustrative
// content (T-09-18). The SSO CTA stays the fixed literal (T-09-17).
//
// SECURITY INVARIANTS (threat register 09-06 / 14):
//   • T-09-17 (open-redirect): the `Continue with SSO` CTA is the ONLY redirect
//     trigger and assigns window.location.href to the FIXED literal
//     /api/oauth/login?action=ui — it is NEVER built from a prop/query/next/hash.
//     Config-driven Docs/Status/Support links use server-sourced allow-list
//     `href`s only (a missing target DROPS the link, never interpolates).
//   • T-09-18 (pre-auth data leak): the RIGHT column renders NO live data — this
//     component performs no fetch and references no /api/session/* endpoint. The
//     OVERVIEW teaser + BACKED BY chips show only hardcoded illustrative content.
//   • T-10-14 (XSS): all brand/tagline/link/provider strings render via Preact
//     text children (htm escapes); `href` attributes come only from config.links.
import { h } from "preact";
import { useCallback } from "preact/hooks";
import htm from "htm";
import { SiteFooter } from "./footer.js";

const html = htm.bind(h);

// The OIDC sign-in entrypoint. The ?action=ui param (added server-side in Plan
// 09-03) makes the callback eager-create the LiteLLM user WITHOUT minting a key
// (D-13). FIXED string literal — do NOT construct from any prop/query/next/hash
// (T-09-17 open-redirect). This is the SOLE redirect trigger.
const SSO_LOGIN_URL = "/api/oauth/login?action=ui";

// Defensive default config shape — a missing `config` prop (or a partial one)
// never crashes the render. Mirrors app.js DEFAULT_CONFIG; brand/tagline/links/
// providers all default to neutral alitellm-auth values.
const DEFAULT_CONFIG = {
  brand: "alitellm-auth",
  brand_short: "LiteLLM",
  tagline: "",
  accent_segment: "-auth",
  provider_label: "dex",
  public_host: "",
  providers: [{ label: "Google" }, { label: "Dex" }, { label: "OIDC" }],
  links: {},
};

// ── Component stylesheet — two-column login layout (UI-SPEC §C) ────────────────
// The shared primitives (.brand-lockup, .btn, .meta-grid, .lock-icon, .provider,
// .status-row/.status-label/.pulse-dot, .sub, .card, .topbar, .topbar-nav,
// .login two-column shell) live in base.css / app.js's SHELL_CSS and are reused
// here verbatim — only the login-specific detail styles live below. Uses only
// var(--*) tokens; caption-role text stays 11px (no 10px).
export const LOGIN_CSS = `
/* The two-column .login grid (centered flex, 2xl column gap), the 480px
 * .login-card constraint, the .value-props column, and the < 768px stacking
 * media query are the STRUCTURAL primitives — they live in base.css. The rules
 * below are the login-specific DETAIL: the accent background glow and the
 * value-prop / overview-sample component styles. Only var(--*) tokens. */

/* Login-specific accent background glow (matches the shell-page gradient). */
.login {
  background-image:
    radial-gradient(ellipse 80% 50% at 50% -20%, var(--glow2), transparent),
    radial-gradient(circle at 80% 80%, rgba(74,222,128,0.03), transparent);
}

/* ── Login topbar detail (reuses the base.css .topbar 56px primitive) ────────── */
/* Brand lockup + tagline column on the left; the .topbar-nav idiom + the
 * .topbar .brand two-tone wordmark mirror the authed shell (app.js SHELL_CSS). */
.login-topbar { gap: var(--space-md); }
.login-topbar .brand-block { display: inline-flex; flex-direction: column; gap: 1px; }
.login-topbar .brand {
  display: inline-flex; align-items: center; gap: var(--space-sm);
  font-family: var(--sans); font-size: 14px; font-weight: 600; color: var(--bright);
}
.login-topbar .brand span { color: var(--accent2); }
.login-topbar .brand svg { width: 18px; height: 18px; stroke: var(--accent); fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.login-topbar .brand-tagline { font-family: var(--sans); font-size: 11px; color: var(--dim); }
.login-topbar .host-label {
  margin-left: auto; margin-right: auto;
  font-family: var(--mono); font-size: 12px; color: var(--dim);
}
.login-topbar .topbar-nav { margin-left: auto; }

/* ── Sign-in card detail ─────────────────────────────────────────────────────── */
/* The card leads with a Sign in heading; spacing for the reassurance line. */
.login-card .signin-heading {
  font-family: var(--sans); font-size: 24px; font-weight: 600; color: var(--bright);
  line-height: 1.3; margin-top: var(--space-md);
}
.login-card .reassurance {
  font-family: var(--sans); font-size: 14px; color: var(--dim);
  margin-top: var(--space-md);
}

/* BACKED BY — an 11px caption label + a row of icon+label chips. The chips are
 * STATIC decorative content, NOT live auth state (D-14 / T-09-18). The 28px chip
 * + --accent stroke icon idiom mirrors the value-prop .vp-icon. */
.backed-by {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 2px; color: var(--dim);
  margin-top: var(--space-lg); margin-bottom: var(--space-sm);
}
.backed-by-row { display: flex; align-items: center; flex-wrap: wrap; gap: var(--space-sm); }
.backed-chip {
  display: inline-flex; align-items: center; gap: var(--space-sm);
  background: var(--surface); border: 1px solid var(--border); border-radius: 999px;
  padding: var(--space-xs) var(--space-md);
}
.backed-chip .chip-icon {
  flex: 0 0 auto; width: 28px; height: 28px; border-radius: 8px;
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--glow); border: 1px solid var(--border);
}
.backed-chip .chip-icon svg { width: 15px; height: 15px; stroke: var(--accent); fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.backed-chip .chip-label { font-family: var(--sans); font-size: 13px; font-weight: 600; color: var(--text); }

/* RIGHT — value props + illustrative overview (the .value-props column sizing
 * is in base.css; these are the heading / item / teaser detail styles). */
.value-props .vp-heading {
  font-family: var(--sans); font-size: 14px; color: var(--text);
  margin-bottom: var(--space-lg);
}
.value-prop { display: flex; align-items: flex-start; gap: var(--space-md); margin-bottom: var(--space-lg); }
.value-prop .vp-icon {
  flex: 0 0 auto; width: 28px; height: 28px; border-radius: 8px;
  display: inline-flex; align-items: center; justify-content: center;
  background: var(--glow); border: 1px solid var(--border);
}
.value-prop .vp-icon svg { width: 15px; height: 15px; stroke: var(--accent); fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.value-prop .vp-text { min-width: 0; }
.value-prop .vp-label { font-family: var(--sans); font-size: 14px; font-weight: 600; color: var(--bright); }
.value-prop .vp-sub { font-family: var(--sans); font-size: 14px; color: var(--dim); margin-top: 2px; }

/* OVERVIEW · sample — a clearly-illustrative static teaser (NO live data). */
.overview-sample {
  margin-top: var(--space-xl);
  background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
  padding: var(--space-lg);
  position: relative;
}
.overview-sample .sample-label {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 2px; color: var(--dim);
  margin-bottom: var(--space-md);
}
/* The 3 illustrative metric tiles use a responsive 3-column grid (drops to a
 * single column under 360px) — reuses the .sample-tile shape. */
.sample-tiles { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--space-sm); }
.sample-tile { background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: var(--space-sm) var(--space-md); }
.sample-tile .tile-label { font-family: var(--mono); font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--dim); }
.sample-tile .tile-value { font-family: var(--sans); font-size: 24px; font-weight: 600; color: var(--bright); line-height: 1.3; }
@media (max-width: 360px) { .sample-tiles { grid-template-columns: 1fr; } }

/* Recent API keys mini-table — a small caption label + static illustrative rows
 * (masked key label + a status pill). Reuses the canonical .status-pill idiom
 * from keys-table.js; adds the neutral Expired variant (D-08, NOT destructive:
 * --dim text on a --surface/--border tint). */
.recent-keys { margin-top: var(--space-lg); padding-top: var(--space-md); border-top: 1px solid var(--border); }
.recent-keys .recent-label {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 1px; color: var(--dim);
  margin-bottom: var(--space-sm);
}
.recent-row { display: flex; align-items: center; justify-content: space-between; gap: var(--space-md); padding: var(--space-xs) 0; }
.recent-row .row-key { font-family: var(--mono); font-size: 12px; color: var(--dim); }
.recent-row .status-pill {
  display: inline-block;
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 1px;
  border-radius: 999px; padding: var(--space-xs) var(--space-sm);
}
.recent-row .status-pill.is-active {
  color: var(--accent); background: var(--glow); border: 1px solid rgba(34,197,94,0.2);
}
.recent-row .status-pill.is-expired {
  color: var(--dim); background: var(--surface); border: 1px solid var(--border);
}
`;

// ── TwoColumnLogin ─────────────────────────────────────────────────────────────
// `endpoint` (optional) is illustrative only — the public API base label passed
// through from app.js; it is NOT fetched here and may be blank. `config` carries
// the public presentation config (brand/tagline/links/providers) threaded by
// app.js. NO live user metric is ever rendered (T-09-18); this component fetches
// nothing.
export function TwoColumnLogin({ endpoint, config }) {
  const cfg = config || DEFAULT_CONFIG;
  const links = cfg.links || {};
  const brand = cfg.brand || "alitellm-auth";
  const brandShort = cfg.brand_short || "LiteLLM";
  const providerLabel = cfg.provider_label || "dex";
  const tagline = cfg.tagline || "";
  const publicHost = cfg.public_host || "";
  const providers =
    Array.isArray(cfg.providers) && cfg.providers.length
      ? cfg.providers
      : DEFAULT_CONFIG.providers;

  // Config-aware two-tone brand lockup. When accent_segment is non-empty and the
  // brand ends with it, the wordmark splits base + accent span; otherwise the
  // full brand renders in --bright. Both render as text children only (T-10-14).
  const accent = cfg.accent_segment || "";
  const base =
    accent && brand.endsWith(accent)
      ? brand.slice(0, brand.length - accent.length)
      : brand;

  // The ONLY redirect trigger (T-09-17). Fixed literal — never from a prop/query.
  const onSignIn = useCallback((e) => {
    e.preventDefault();
    window.location.href = SSO_LOGIN_URL;
  }, []);

  return html`
    <div class="login-surface" data-state="signin">
      <header class="topbar login-topbar">
        <div class="brand-block">
          <div class="brand">
            <svg viewBox="0 0 24 24"><path d="M12 2 4 6v6c0 4.5 3.4 7.3 8 10 4.6-2.7 8-5.5 8-10V6z"/><path d="m9 12 2 2 4-4"/></svg>
            ${accent && brand.endsWith(accent)
              ? html`${base}<span>${accent}</span>`
              : brand}
          </div>
          ${tagline ? html`<div class="brand-tagline">${tagline}</div>` : null}
        </div>
        ${publicHost ? html`<div class="host-label">${publicHost}</div>` : null}
        <nav class="topbar-nav">
          ${links.docs
            ? html`<a href=${links.docs} target="_blank" rel="noopener noreferrer">Docs</a>`
            : null}
          ${links.status
            ? html`<a href=${links.status} target="_blank" rel="noopener noreferrer">Status</a>`
            : null}
          ${links.support
            ? html`<a href=${links.support} target="_blank" rel="noopener noreferrer">Support</a>`
            : null}
        </nav>
      </header>

      <div class="login" data-state="signin">
        <main class="card login-card">
          <div class="card-header">
            <div class="status-row">
              <div class="pulse-dot"></div>
              <div class="status-label">READY</div>
            </div>
            <div class="brand-lockup">
              <svg viewBox="0 0 24 24"><path d="M12 2 4 6v6c0 4.5 3.4 7.3 8 10 4.6-2.7 8-5.5 8-10V6z"/><path d="m9 12 2 2 4-4"/></svg>
            </div>
            <div class="signin-heading">Sign in</div>
            <div class="sub">Authenticate with your organization account to manage your ${brandShort} API keys.</div>
          </div>
          <div class="card-body">
            <a class="btn" href=${SSO_LOGIN_URL} onClick=${onSignIn}>
              <svg viewBox="0 0 24 24"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><path d="M10 17l5-5-5-5"/><path d="M15 12H3"/></svg>
              Continue with SSO
            </a>
            <div class="reassurance">Secure, seamless access powered by your identity provider.</div>
            <div class="backed-by">BACKED BY</div>
            <!-- No aria-hidden: the provider chips are static, non-redundant text
                 naming the identity providers (Google / Dex / OIDC) that back the
                 SSO button — the only on-screen indication of which IdPs are wired.
                 The T-09-18 concern is about *live* data; these are not (WR-04). -->
            <div class="backed-by-row">
              ${providers.map(
                (p) => html`
                  <span class="backed-chip">
                    <span class="chip-icon">
                      <svg viewBox="0 0 24 24"><path d="M12 2 4 6v6c0 4.5 3.4 7.3 8 10 4.6-2.7 8-5.5 8-10V6z"/></svg>
                    </span>
                    <span class="chip-label">${p && p.label ? p.label : ""}</span>
                  </span>`,
              )}
            </div>
          </div>
          <div class="card-footer">
            <div class="lock-icon">
              <svg viewBox="0 0 24 24"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>
              no password stored here
            </div>
            <div class="provider">redirects to <b>${providerLabel}</b></div>
          </div>
        </main>

        <section class="value-props">
          <div class="vp-heading">After you sign in, you can:</div>

          <div class="value-prop">
            <span class="vp-icon"><svg viewBox="0 0 24 24"><path d="M12 5v14"/><path d="M5 12h14"/></svg></span>
            <div class="vp-text">
              <div class="vp-label">Create & generate API keys</div>
              <div class="vp-sub">Generate keys scoped to your account in seconds.</div>
            </div>
          </div>

          <div class="value-prop">
            <span class="vp-icon"><svg viewBox="0 0 24 24"><path d="M3 3v18h18"/><path d="m7 14 3-4 3 2 4-6"/></svg></span>
            <div class="vp-text">
              <div class="vp-label">Review usage & budgets</div>
              <div class="vp-sub">Monitor spend, limits, and budgets at a glance.</div>
            </div>
          </div>

          <div class="value-prop">
            <span class="vp-icon"><svg viewBox="0 0 24 24"><path d="M3 6h18"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/><path d="m6 6 1 14a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-14"/></svg></span>
            <div class="vp-text">
              <div class="vp-label">Revoke compromised keys</div>
              <div class="vp-sub">Instantly revoke any key from your systems.</div>
            </div>
          </div>

          <!-- OVERVIEW · sample — illustrative ONLY. All numbers are hardcoded
               placeholders; this teaser fetches nothing and shows NO live data
               on the unauthenticated screen (UI-SPEC §C ⚠, T-09-18). -->
          <div class="overview-sample" aria-hidden="true">
            <div class="sample-label">OVERVIEW · sample</div>
            <div class="sample-tiles">
              <div class="sample-tile"><div class="tile-label">Active keys</div><div class="tile-value">12</div></div>
              <div class="sample-tile"><div class="tile-label">Monthly Requests</div><div class="tile-value">2.45M</div></div>
              <div class="sample-tile"><div class="tile-label">Spend MTD</div><div class="tile-value">$1,240.50</div></div>
            </div>
            <div class="recent-keys">
              <div class="recent-label">Recent API keys</div>
              <div class="recent-row">
                <span class="row-key">key-•••• 7f3a</span>
                <span class="status-pill is-active">Active</span>
              </div>
              <div class="recent-row">
                <span class="row-key">key-•••• c1d8</span>
                <span class="status-pill is-active">Active</span>
              </div>
              <div class="recent-row">
                <span class="row-key">key-•••• 90b2</span>
                <span class="status-pill is-expired">Expired</span>
              </div>
            </div>
          </div>
        </section>
      </div>

      <${SiteFooter} config=${cfg} />
    </div>
  `;
}
