// app.js — Preact shell for the alitellm-auth SPA (htm tagged templates, no JSX).
//
// On mount the shell shows the loading card IMMEDIATELY (no white flash —
// UI-SPEC §Loading Sequence step 1), THEN calls GET /api/session/me via
// apiFetch and feeds {status, hasLoaded} through the pure resolveState() to
// pick which of the five states to render:
//
//   loading | signin | authed | error | expired
//
// Cold-load 401 -> sign-in landing (NO auto-redirect; the CTA is the only
// redirect trigger). Mid-session 401 (after a 200 render set hasLoaded) ->
// silent redirect to /api/oauth/login. All copy is LOCKED per UI-SPEC
// §Copywriting Contract. The authenticated content slot is intentionally EMPTY
// this phase — Phase 10 fills it with the DASH-* panels (Phase 10 boundary,
// threat T-09-03: no key material rendered here).
import { h, render } from "preact";
import { useState, useEffect, useCallback } from "preact/hooks";
import htm from "htm";
import { resolveState } from "./state.js";
import { apiFetch, getHasLoaded, setHasLoaded } from "./api.js";
import { useHashRoute } from "./router.js";
import { RightSidebar } from "./sidebar.js";

const html = htm.bind(h);

// ── Shell component stylesheet ────────────────────────────────────────────────
// base.css owns the design tokens, slideUp/pulse keyframes and the .header /
// .main / .card / .status-label / .pulse-dot primitives. The card-interior
// component classes below (lifted verbatim from 09-login-mockup.html, using
// only var(--*) tokens) live with the component that renders them.
const SHELL_CSS = `
.shell-page {
  flex: 1 1 auto;
  display: flex; align-items: center; justify-content: center;
  padding: var(--space-lg);
  background-image:
    radial-gradient(ellipse 80% 50% at 50% -20%, var(--glow2), transparent),
    radial-gradient(circle at 80% 80%, rgba(74,222,128,0.03), transparent);
}
.shell-page[data-state="error"] {
  background-image:
    radial-gradient(ellipse 80% 50% at 50% -20%, var(--glow2-err), transparent),
    radial-gradient(circle at 80% 80%, rgba(248,113,113,0.03), transparent);
}
.shell-card { max-width: 620px; }
.shell-page[data-state="error"] .shell-card { box-shadow: 0 0 80px -20px rgba(239,68,68,0.06); }

.card-header { padding: 32px 32px 24px; border-bottom: 1px solid var(--border); }
.status-row { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; }
.shell-page[data-state="error"] .pulse-dot {
  background: var(--destructive); box-shadow: 0 0 8px var(--destructive); animation: none;
}
.shell-page[data-state="error"] .status-label { color: var(--destructive); }

.brand-lockup { display: flex; align-items: center; gap: 12px; margin-bottom: 4px; }
.brand-lockup svg { width: 26px; height: 26px; stroke: var(--accent); fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.brand-lockup .name { font-size: 24px; font-weight: 600; color: var(--bright); letter-spacing: -.3px; }
.brand-lockup .name span { color: var(--accent2); }

.heading { font-size: 24px; font-weight: 600; color: var(--bright); line-height: 1.3; }
.sub { margin-top: 6px; font-size: 14px; color: var(--dim); }
.card-body { padding: 28px 32px; }

.loader { font-family: var(--mono); font-size: 12px; font-weight: 400; color: var(--dim); letter-spacing: 1px; display: inline-flex; align-items: center; }
.loader::after { content: ""; animation: ellipsis 1.4s steps(4, end) infinite; }
@keyframes ellipsis { 0% { content: ""; } 25% { content: "."; } 50% { content: ".."; } 75% { content: "..."; } }

.meta-grid { display: grid; grid-template-columns: auto 1fr; gap: 6px 16px; font-size: 12px; margin-top: 20px; }
.meta-grid .label { font-family: var(--mono); color: var(--dim); white-space: nowrap; }
.meta-grid .value { font-family: var(--mono); color: var(--text); }
.meta-grid .value.accent { color: var(--accent2); }

.btn {
  display: inline-flex; align-items: center; gap: 10px;
  font-family: var(--mono); font-size: 13px; font-weight: 600;
  text-transform: lowercase; letter-spacing: .5px;
  color: #04140a; background: var(--accent);
  border: 1px solid var(--accent); border-radius: 8px;
  padding: 12px 20px; cursor: pointer;
  box-shadow: 0 0 24px -6px var(--accent);
  transition: background .15s, box-shadow .15s, transform .05s;
  text-decoration: none;
}
.btn:hover { background: var(--accent2); box-shadow: 0 0 32px -4px var(--accent); }
.btn:active { transform: translateY(1px); }
.btn svg { width: 15px; height: 15px; stroke: #04140a; fill: none; stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; }
.btn.retry { color: #1a0606; background: var(--destructive); border-color: var(--destructive); box-shadow: 0 0 24px -6px var(--destructive); }
.btn.retry:hover { background: var(--destructive2); }
.btn.retry svg { stroke: #1a0606; }

.card-footer { padding: 16px 32px; border-top: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; font-size: 12px; flex-wrap: wrap; gap: 8px; }
.lock-icon { display: inline-flex; align-items: center; gap: 6px; color: var(--dim); font-family: var(--mono); font-size: 11px; }
.lock-icon svg { width: 12px; height: 12px; fill: none; stroke: var(--dim); stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
.provider { font-family: var(--mono); font-size: 11px; color: var(--dim); }
.provider b { color: var(--accent); font-weight: 600; }

.shell-header-meta { margin-left: auto; display: flex; align-items: center; gap: var(--space-md); font-family: var(--mono); font-size: 11px; }
.shell-header-meta .email { color: var(--text); }
.shell-header-meta .signout { color: var(--dim); text-decoration: none; }
.shell-header-meta .signout:hover { color: var(--text); }
.shell-header-meta .connected { display: inline-flex; align-items: center; gap: 6px; color: var(--accent); text-transform: uppercase; letter-spacing: 1px; }

/* ── Wide authenticated shell (UI-SPEC §B — re-spec'd multi-panel layout) ──────── */
/* The structural primitives (.topbar 56px, .content 1200px + 2xl gap, .sidebar
 * 320px, .panel 16px) live in base.css; the component-detail styles below
 * (nav, panel actions, stats placeholder, responsive stacking) live here with
 * the AuthedShell that renders them. */

.topbar .brand {
  display: inline-flex; align-items: center; gap: var(--space-sm);
  font-family: var(--sans); font-size: 14px; font-weight: 600; color: var(--bright);
}
.topbar .brand span { color: var(--accent2); }
.topbar .brand svg { width: 18px; height: 18px; stroke: var(--accent); fill: none; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }

/* Topbar nav — caption-role 11px mono labels; the active route is marked with --accent. */
.topbar-nav { display: flex; align-items: center; gap: var(--space-lg); }
.topbar-nav a {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 1px; color: var(--dim);
  text-decoration: none; padding: 4px 0; border-bottom: 2px solid transparent;
  cursor: pointer;
}
.topbar-nav a:hover { color: var(--text); }
.topbar-nav a.active { color: var(--accent); border-bottom-color: var(--accent); }

.topbar-meta { margin-left: auto; display: flex; align-items: center; gap: var(--space-md); font-family: var(--mono); font-size: 11px; }
.topbar-meta .connected { display: inline-flex; align-items: center; gap: 6px; color: var(--accent); text-transform: uppercase; letter-spacing: 1px; }
.topbar-meta .email { color: var(--text); }
.topbar-meta .signout { color: var(--dim); text-decoration: none; }
.topbar-meta .signout:hover { color: var(--text); }

/* The empty #/ dashboard slot keeps the card entrance animation. */
.main-slot { animation: slideUp .5s ease-out; }

/* .sidebar (320px) is declared in base.css; stack its panels vertically here. */
.sidebar { display: flex; flex-direction: column; gap: var(--space-lg); }

/* .panel shape (16px radius, surface, lg padding) is declared in base.css. */
.panel-label {
  font-family: var(--mono); font-size: 11px; font-weight: 600;
  text-transform: uppercase; letter-spacing: 2px; color: var(--dim);
  margin-bottom: var(--space-md);
}
.panel-primary { box-shadow: 0 0 40px -24px var(--accent); }
.panel-action {
  display: block; width: 100%; text-align: left;
  font-family: var(--mono); font-size: 12px; font-weight: 600;
  color: var(--text); background: transparent;
  border: 1px solid var(--border); border-radius: 8px;
  padding: 12px var(--space-md); margin-top: var(--space-sm); cursor: pointer;
  transition: border-color .15s, color .15s;
}
.panel-action:first-of-type { margin-top: 0; }
.panel-action:hover { border-color: var(--accent); color: var(--bright); }
.panel-action-primary { color: var(--accent); border-color: var(--accent); }
.panel-action-primary:hover { background: var(--glow); }
/* Security / Need-help: visually subordinate (smaller, dimmer) to Quick actions. */
.panel-minimal .panel-body { font-family: var(--sans); font-size: 12px; color: var(--dim); line-height: 1.5; }

/* Reserved Stats route placeholder (Phase 12, D-10). */
.stats-placeholder {
  background: var(--surface); border: 1px solid var(--border); border-radius: 16px;
  padding: var(--space-3xl) var(--space-xl); text-align: center; animation: slideUp .5s ease-out;
}
.stats-placeholder .heading { font-size: 24px; font-weight: 600; color: var(--bright); }
.stats-placeholder .sub { margin-top: var(--space-sm); font-size: 14px; color: var(--dim); }

/* Responsive: below 1024px the sidebar stacks below the main content. */
@media (max-width: 1024px) {
  .content { flex-direction: column; padding: var(--space-xl) var(--space-lg) 0; }
  .sidebar { width: 100%; flex: 1 1 auto; }
}
`;

// The OIDC sign-in entrypoint. The ?action=ui param (added server-side in Plan
// 03) makes the callback eager-create the LiteLLM user WITHOUT minting a key
// (D-13). The cold-load CTA is the ONLY thing that triggers this redirect.
const SSO_LOGIN_URL = "/api/oauth/login?action=ui";
// Mid-session expiry redirects to the bare login (no landing card, UI-SPEC).
const EXPIRED_REDIRECT_URL = "/api/oauth/login";

// ── State views ───────────────────────────────────────────────────────────────

function LoadingCard() {
  return html`
    <div class="shell-page" data-state="loading">
      <main class="card shell-card">
        <div class="card-header">
          <div class="status-row">
            <div class="pulse-dot"></div>
            <div class="status-label">INITIALIZING</div>
          </div>
          <div class="heading">Connecting to alitellm-auth...</div>
          <div class="sub">Verifying your session, please wait.</div>
        </div>
        <div class="card-body">
          <div class="loader">checking session</div>
        </div>
      </main>
    </div>
  `;
}

function SignInLanding({ endpoint }) {
  const onSignIn = useCallback((e) => {
    e.preventDefault();
    window.location.href = SSO_LOGIN_URL;
  }, []);
  return html`
    <div class="shell-page" data-state="signin">
      <main class="card shell-card">
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
            <div class="label">endpoint</div><div class="value">${endpoint || ""}</div>
            <div class="label">scope</div><div class="value">openid email profile</div>
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
    </div>
  `;
}

function ErrorCard({ onRetry }) {
  return html`
    <div class="shell-page" data-state="error">
      <main class="card shell-card">
        <div class="card-header">
          <div class="status-row">
            <div class="pulse-dot"></div>
            <div class="status-label">ERROR</div>
          </div>
          <div class="heading">Service Unavailable</div>
          <div class="sub">Unable to reach alitellm-auth. Try refreshing the page.</div>
        </div>
        <div class="card-body">
          <button class="btn retry" type="button" onClick=${onRetry}>
            <svg viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-3-6.7"/><path d="M21 3v5h-5"/></svg>
            retry
          </button>
        </div>
      </main>
    </div>
  `;
}

// Authenticated shell — the WIDE multi-panel layout (UI-SPEC §B, re-spec'd):
// a 56px topbar (brand + Stats/Status nav + connected pulse-dot + {email} +
// sign out), a centered 1200px-max content region, and a fixed 320px right
// sidebar. A client-side hash router (useHashRoute) drives the main content
// slot: #/ -> the EMPTY dashboard slot (Phase 10 fills it), #/stats -> a
// reserved "Coming soon" placeholder (Phase 12, D-10).
//
// The main content slot is LEFT EMPTY at #/: Phase 10 fills it with the DASH-*
// panels. Do NOT render key material here (T-09-15: no sk- values / key table).
function AuthedShell({ email }) {
  const route = useHashRoute();
  const onStats = useCallback((e) => {
    e.preventDefault();
    window.location.hash = "#/stats";
  }, []);
  return html`
    <header class="topbar">
      <div class="brand">
        <svg viewBox="0 0 24 24"><path d="M12 2 4 6v6c0 4.5 3.4 7.3 8 10 4.6-2.7 8-5.5 8-10V6z"/><path d="m9 12 2 2 4-4"/></svg>
        alitellm<span>-auth</span>
      </div>
      <nav class="topbar-nav">
        <a
          href="#/stats"
          class=${route === "stats" ? "active" : ""}
          onClick=${onStats}
        >Stats</a>
        <span class="connected"><span class="pulse-dot"></span>Status</span>
      </nav>
      <div class="topbar-meta">
        <span class="email">${email} ▾</span>
        <a class="signout" href="/api/oauth/logout">sign out</a>
      </div>
    </header>
    <div class="content">
      <main class="main-region">
        ${route === "stats"
          ? html`
            <div class="stats-placeholder">
              <div class="heading">Coming soon</div>
              <div class="sub">Usage analytics arrive in a later release.</div>
            </div>`
          : html`<div class="main-slot"><!-- Phase 10 fills the dashboard slot at #/ --></div>`}
      </main>
      <${RightSidebar} />
    </div>
  `;
}

// ── Shell driver ───────────────────────────────────────────────────────────────

export function App() {
  // status === null -> loading card rendered before the first /me response
  // resolves, so there is no white flash (UI-SPEC §Loading Sequence step 1).
  const [status, setStatus] = useState(null);
  const [me, setMe] = useState(null);

  const loadSession = useCallback(async () => {
    setStatus(null); // show loading immediately on (re)load
    const { status: s, data } = await apiFetch("/api/session/me");
    if (s === 200) {
      setMe(data);
      setHasLoaded(true); // a later 401 now routes to "expired"
    }
    setStatus(s);
  }, []);

  useEffect(() => {
    loadSession();
  }, [loadSession]);

  const view = resolveState(status, getHasLoaded());

  // Mid-session expiry: silent redirect, no card. Done as an effect so render
  // stays a pure function of state.
  useEffect(() => {
    if (view === "expired") {
      window.location.href = EXPIRED_REDIRECT_URL;
    }
  }, [view]);

  if (view === "authed") {
    return html`<${AuthedShell} email=${(me && me.email) || ""} />`;
  }
  if (view === "signin") {
    return html`<${SignInLanding} endpoint=${me && me.endpoint} />`;
  }
  if (view === "error") {
    return html`<${ErrorCard} onRetry=${loadSession} />`;
  }
  // "loading" and "expired" both render the loading card (expired also triggers
  // the redirect effect above, so the card is only a brief placeholder).
  return html`<${LoadingCard} />`;
}

// Inject the shell-component stylesheet once (idempotent).
export function injectShellStyles(doc) {
  const d = doc || document;
  if (d.getElementById("shell-styles")) return;
  const style = d.createElement("style");
  style.id = "shell-styles";
  style.textContent = SHELL_CSS;
  d.head.appendChild(style);
}

export { render };
