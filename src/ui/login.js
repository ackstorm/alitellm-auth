// login.js — the two-column sign-in landing for the alitellm-auth SPA
// (Preact + htm tagged templates, no JSX, no TypeScript per 09-CONTEXT D-04).
//
// Rendered ONLY on a cold-load /me 401 (UI-SPEC §C, §F "401 cold load"): a
// sign-in CARD on the LEFT (brand lockup + READY status + sub copy + the
// `sign in with sso` CTA + provider meta-grid + footer hint) and a VALUE-PROPS
// column on the RIGHT (the "After you sign in, you can:" heading, three locked
// value props, and a clearly-illustrative `OVERVIEW · sample` teaser).
//
// Brand stays `alitellm-auth` (the `-auth` segment in --accent2). The
// reference images' alternate vendor branding is intentionally NOT adopted
// (D-05) — only their layout/composition direction is.
//
// SECURITY INVARIANTS (threat register 09-06):
//   • T-09-17 (open-redirect): the `sign in with sso` CTA is the ONLY redirect
//     trigger and assigns window.location.href to the FIXED literal
//     /api/oauth/login?action=ui — it is NEVER built from a prop/query/next/hash.
//   • T-09-18 (pre-auth data leak): the RIGHT column renders NO live data — this
//     component performs no fetch and references no /api/session/* endpoint. The
//     OVERVIEW teaser shows only hardcoded illustrative placeholders.
//   • T-09-19 (XSS): all copy is static literals; rendering is via Preact text
//     children (htm escapes) — no raw-HTML injection sinks are used.
import { h } from "preact";
import { useCallback } from "preact/hooks";
import htm from "htm";

const html = htm.bind(h);

// The OIDC sign-in entrypoint. The ?action=ui param (added server-side in Plan
// 09-03) makes the callback eager-create the LiteLLM user WITHOUT minting a key
// (D-13). FIXED string literal — do NOT construct from any prop/query/next/hash
// (T-09-17 open-redirect). This is the SOLE redirect trigger.
const SSO_LOGIN_URL = "/api/oauth/login?action=ui";

// ── Component stylesheet — two-column login layout (UI-SPEC §C) ────────────────
// The shared primitives (.brand-lockup, .btn, .meta-grid, .lock-icon, .provider,
// .status-row/.status-label/.pulse-dot, .sub, .card) live in base.css /
// app.js's SHELL_CSS and are reused here verbatim — only the login-specific
// two-column scaffolding + value-prop / overview-sample styles live below. Uses
// only var(--*) tokens; caption-role text stays 11px (no 10px).
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

/* Small illustrative provider marks below the meta-grid (NOT live auth state). */
.provider-marks { display: flex; align-items: center; gap: var(--space-md); margin-top: var(--space-md); }
.provider-marks svg { width: 18px; height: 18px; opacity: .5; }
.provider-marks .mark-google { fill: var(--text); stroke: none; }
.provider-marks .mark-line { fill: none; stroke: var(--dim); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }

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
.sample-tiles { display: grid; grid-template-columns: repeat(2, 1fr); gap: var(--space-sm); }
.sample-tile { background: var(--bg); border: 1px solid var(--border); border-radius: 8px; padding: var(--space-sm) var(--space-md); }
.sample-tile .tile-label { font-family: var(--mono); font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--dim); }
.sample-tile .tile-value { font-family: var(--sans); font-size: 24px; font-weight: 600; color: var(--bright); line-height: 1.3; }
.sample-row { display: flex; align-items: center; justify-content: space-between; margin-top: var(--space-md); padding-top: var(--space-md); border-top: 1px solid var(--border); }
.sample-row .row-key { font-family: var(--mono); font-size: 12px; color: var(--dim); }
.sample-row .row-pill { font-family: var(--mono); font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 1px; color: var(--accent); }
`;

// ── TwoColumnLogin ─────────────────────────────────────────────────────────────
// `endpoint` (optional) is illustrative only — it is the public API base label
// passed through from app.js; it is NOT fetched here and may be blank. NO live
// user metric is ever rendered (T-09-18).
export function TwoColumnLogin({ endpoint }) {
  // The ONLY redirect trigger (T-09-17). Fixed literal — never from a prop/query.
  const onSignIn = useCallback((e) => {
    e.preventDefault();
    window.location.href = SSO_LOGIN_URL;
  }, []);

  return html`
    <div class="login" data-state="signin">
      <main class="card login-card">
        <div class="card-header">
          <div class="status-row">
            <div class="pulse-dot"></div>
            <div class="status-label">READY</div>
          </div>
          <div class="brand-lockup">
            <svg viewBox="0 0 24 24"><path d="M12 2 4 6v6c0 4.5 3.4 7.3 8 10 4.6-2.7 8-5.5 8-10V6z"/><path d="m9 12 2 2 4-4"/></svg>
            <div class="name">alitellm<span>-auth</span></div>
          </div>
          <div class="sub">Self-service LLM virtual keys. Sign in to view, create, and revoke your keys.</div>
        </div>
        <div class="card-body">
          <a class="btn" href=${SSO_LOGIN_URL} onClick=${onSignIn}>
            <svg viewBox="0 0 24 24"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><path d="M10 17l5-5-5-5"/><path d="M15 12H3"/></svg>
            sign in with sso
          </a>
          <div class="meta-grid">
            <div class="label">provider</div><div class="value accent">dex · oidc</div>
            ${endpoint
              ? html`<div class="label">endpoint</div><div class="value">${endpoint}</div>`
              : null}
          </div>
          <div class="provider-marks" aria-hidden="true">
            <svg viewBox="0 0 24 24"><path class="mark-google" d="M21.35 11.1h-9.18v2.92h5.27c-.23 1.42-1.66 4.16-5.27 4.16a5.96 5.96 0 0 1 0-11.92c1.7 0 2.84.72 3.49 1.34l2.38-2.3A9.3 9.3 0 0 0 12.17 3a9.18 9.18 0 1 0 0 18.35c5.3 0 8.81-3.73 8.81-8.98 0-.6-.07-1.06-.18-1.52z"/></svg>
            <svg viewBox="0 0 24 24"><circle class="mark-line" cx="12" cy="12" r="9"/><path class="mark-line" d="M3 12h18"/><path class="mark-line" d="M12 3a14 14 0 0 1 0 18 14 14 0 0 1 0-18z"/></svg>
            <svg viewBox="0 0 24 24"><path class="mark-line" d="M7 8a5 5 0 0 0 0 8h2"/><path class="mark-line" d="M17 8a5 5 0 0 1 0 8h-2"/><path class="mark-line" d="M9 12h6"/></svg>
          </div>
        </div>
        <div class="card-footer">
          <div class="lock-icon">
            <svg viewBox="0 0 24 24"><rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0110 0v4"/></svg>
            no password stored here
          </div>
          <div class="provider">redirects to <b>dex</b></div>
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
            <div class="sample-tile"><div class="tile-label">Active keys</div><div class="tile-value">3</div></div>
            <div class="sample-tile"><div class="tile-label">Spend MTD</div><div class="tile-value">$12</div></div>
          </div>
          <div class="sample-row">
            <span class="row-key">key-•••• sample</span>
            <span class="row-pill">Active</span>
          </div>
        </div>
      </section>
    </div>
  `;
}
