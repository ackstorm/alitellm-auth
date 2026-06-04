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
// §Copywriting Contract. The authenticated content slot at #/ now mounts the
// Phase 10 Dashboard (DASH-01..06, dashboard.js), which owns the keys data,
// the in-memory fresh-key map, and the create/delete modals.
import { h, render } from "preact";
import { useState, useEffect, useCallback, useRef } from "preact/hooks";
import htm from "htm";
import { resolveState } from "./state.js";
import { apiFetch, getJson, getHasLoaded, setHasLoaded } from "./api.js";
import { useHashRoute } from "./router.js";
import { RightSidebar } from "./sidebar.js";
import { SiteFooter, FOOTER_CSS } from "./footer.js";
import { TwoColumnLogin, LOGIN_CSS } from "./login.js";
import { Dashboard, DASHBOARD_CSS } from "./dashboard.js";
import { KEYS_TABLE_CSS } from "./keys-table.js";
import { CREATE_KEY_CSS } from "./create-key.js";
import { DELETE_MODAL_CSS } from "./delete-modal.js";
// The Phase-13 #/stats page (StatsView) + every new component stylesheet. The
// container (stats.js) imports the leaves for behavior but does NOT re-export
// their CSS, so app.js pulls each *_CSS in directly to feed injectShellStyles.
import { StatsView, STATS_CSS } from "./stats.js";
import { SKELETON_CSS } from "./skeleton.js";
import { TOAST_CSS } from "./toast.js";
import { CHARTS_CSS } from "./charts.js";
import { STATS_KPIS_CSS } from "./stats-kpis.js";
import { STATS_DONUT_CSS } from "./stats-donut.js";
import { STATS_BUDGET_CSS } from "./stats-budget.js";
import { STATS_MODEL_TABLE_CSS } from "./stats-model-table.js";
import { STATS_TOP_KEYS_CSS } from "./stats-top-keys.js";
import { STATS_RAIL_CSS } from "./stats-rail.js";
import { DATE_RANGE_CSS } from "./date-range.js";

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

/* Responsive: below 1024px the sidebar stacks below the main content. */
@media (max-width: 1024px) {
  .content { flex-direction: column; padding: var(--space-xl) var(--space-lg) 0; }
  .sidebar { width: 100%; flex: 1 1 auto; }
}
`;

// The cold-load sign-in CTA (?action=ui, the ONLY OIDC redirect trigger) now
// lives in login.js's TwoColumnLogin — app.js no longer owns that literal.
// Mid-session expiry redirects to the bare login (no landing card, UI-SPEC).
const EXPIRED_REDIRECT_URL = "/api/oauth/login";

// Built-in default presentation config (D-01). The SPA renders fully from these
// defaults even if the boot GET /api/config never resolves (never-throw,
// never-block-render — mirrors the `me`-degradation discipline, threat T-14-01).
// A successful fetch is merged OVER these defaults; a missing `links` stays {} so
// the real-links-only rule (D-02/D-03) drops every nav/footer anchor by default.
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

// The cold-load sign-in landing is the two-column <TwoColumnLogin/> (UI-SPEC §C),
// implemented in login.js. The old single-column SignInLanding was removed in
// 09-06; there is now ONE sign-in implementation.

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
// slot: #/ -> the Dashboard (DASH-01..06, dashboard.js), #/stats -> the Usage &
// Spend page (StatsView, stats.js — Phase 13). The stats page owns its own
// full-width grid + left rail + page right column, so the shell's 320px
// RightSidebar is HIDDEN on #/stats (CONTEXT D-08); the #/ route is untouched.
//
// The Dashboard OWNS the create-modal open-state; it hands its opener up via
// `registerCreateOpener` so the sidebar `Create key` shortcut opens the SAME
// modal as the main `+ New Key` CTA. The opener is held in a ref so it does not
// re-trigger renders, and the sidebar calls it without ever touching a /keys
// endpoint itself (threat T-09-15).
function AuthedShell({ me, config }) {
  const route = useHashRoute();
  const cfg = config || DEFAULT_CONFIG;
  const links = cfg.links || {};
  const email = (me && me.email) || "";
  // User-menu trigger prefers the display name, falling back to email (UI-SPEC
  // copy table). Rendered as a Preact text child only — never raw HTML (T-10-14).
  const menuLabel = (me && me.name) || email;
  // Config-aware two-tone brand lockup. When accent_segment is non-empty the
  // wordmark splits base + accent; when empty (e.g. ACKStorm) the full brand
  // renders in --bright with no accent span. Both render as text children only.
  const accent = cfg.accent_segment || "";
  const base =
    accent && cfg.brand && cfg.brand.endsWith(accent)
      ? cfg.brand.slice(0, cfg.brand.length - accent.length)
      : cfg.brand;
  const createOpenerRef = useRef(null);
  const registerCreateOpener = useCallback((opener) => {
    createOpenerRef.current = opener;
  }, []);
  const onCreateKey = useCallback(() => {
    if (createOpenerRef.current) createOpenerRef.current();
  }, []);
  const onStats = useCallback((e) => {
    e.preventDefault();
    window.location.hash = "#/stats";
  }, []);
  return html`
    <header class="topbar">
      <div class="brand">
        <svg viewBox="0 0 24 24"><path d="M12 2 4 6v6c0 4.5 3.4 7.3 8 10 4.6-2.7 8-5.5 8-10V6z"/><path d="m9 12 2 2 4-4"/></svg>
        ${accent ? html`${base}<span>${accent}</span>` : cfg.brand}
      </div>
      <nav class="topbar-nav">
        <a
          href="#/stats"
          class=${route === "stats" ? "active" : ""}
          onClick=${onStats}
        >Stats</a>
        ${links.status
          ? html`<a href=${links.status} target="_blank" rel="noopener noreferrer">Status</a>`
          : html`<span class="connected"><span class="pulse-dot"></span>Status</span>`}
      </nav>
      <div class="topbar-meta">
        <span class="email">${menuLabel} ▾</span>
        <a class="signout" href="/api/oauth/logout">sign out</a>
      </div>
    </header>
    <div class="content">
      <main class="main-region">
        ${route === "stats"
          ? html`<${StatsView} me=${me} />`
          : html`<div class="main-slot">
              <${Dashboard} me=${me} registerCreateOpener=${registerCreateOpener} />
              <${SiteFooter} config=${cfg} />
            </div>`}
      </main>
      ${route !== "stats"
        ? html`<${RightSidebar} onCreateKey=${onCreateKey} config=${cfg} />`
        : null}
    </div>
  `;
}

// ── Shell driver ───────────────────────────────────────────────────────────────

export function App() {
  // status === null -> loading card rendered before the first /me response
  // resolves, so there is no white flash (UI-SPEC §Loading Sequence step 1).
  const [status, setStatus] = useState(null);
  const [me, setMe] = useState(null);
  // Presentation config (D-01). Starts from the built-in defaults so the SPA
  // renders correctly before (and if) the boot fetch resolves.
  const [config, setConfig] = useState(DEFAULT_CONFIG);

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

  // ONE boot fetch of the public presentation config (UI-SPEC §A). On success
  // merge it OVER the defaults; on any failure keep the built-in defaults — the
  // never-throw getJson contract guarantees this never blocks render (T-14-01).
  useEffect(() => {
    let active = true;
    (async () => {
      const { status: s, data } = await getJson("/api/config");
      if (active && s === 200 && data) {
        setConfig({ ...DEFAULT_CONFIG, ...data });
      }
    })();
    return () => {
      active = false;
    };
  }, []);

  const view = resolveState(status, getHasLoaded());

  // Mid-session expiry: silent redirect, no card. Done as an effect so render
  // stays a pure function of state.
  useEffect(() => {
    if (view === "expired") {
      window.location.href = EXPIRED_REDIRECT_URL;
    }
  }, [view]);

  if (view === "authed") {
    return html`<${AuthedShell} me=${me} config=${config} />`;
  }
  if (view === "signin") {
    return html`<${TwoColumnLogin} endpoint=${me && me.endpoint} config=${config} />`;
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
  // SHELL_CSS owns the shell-state cards + wide authed layout; LOGIN_CSS owns
  // the two-column sign-in landing (login.js); the four DASH-* strings own the
  // dashboard container, keys table, and the create/delete modals (Phase 10).
  // The Phase-13 STATS_* strings own the #/stats page: the container grid
  // (STATS_CSS), the Wave-1 primitives (skeleton/toast/charts), and every
  // Wave-2 leaf (KPIs, donut, budget, model table, top keys, rail, date range).
  // All use only var(--*) tokens.
  style.textContent =
    SHELL_CSS + LOGIN_CSS + DASHBOARD_CSS + KEYS_TABLE_CSS + CREATE_KEY_CSS + DELETE_MODAL_CSS +
    STATS_CSS + SKELETON_CSS + TOAST_CSS + CHARTS_CSS + STATS_KPIS_CSS + STATS_DONUT_CSS +
    STATS_BUDGET_CSS + STATS_MODEL_TABLE_CSS + STATS_TOP_KEYS_CSS + STATS_RAIL_CSS + DATE_RANGE_CSS +
    FOOTER_CSS;
  d.head.appendChild(style);
}

export { render };
