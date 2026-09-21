# Changelog

## [unreleased]

### Restored

- The server side of the OAuth front door, reverting the v0.12.0 removal: the
  authorization server (`app/oauth_as/`), `/api/internal/front-key`, the Go Envoy
  `ext_authz` service (`authz/`, image and CI job), the chart's `authServer`,
  `authz` and `istio` blocks and every `AS_*` / `INTERNAL_TOKEN` setting.
  Token issuance and the gateway check live here again.

### Removed

- The OpenCode auth plugin and its `GET /public/opencode-auth` route: the
  authorization server (ACH) serves it now, at `/platform/opencode-auth` on
  the API host. Source moved to `ackstorm/ach` (`internal/platformapi/opencodeauth`).

### Fixed

- authz: LiteLLM's own UI and admin surfaces on the API host work again. Only
  `/v1`, `/gemini`, `/mcp` and `/a2a` require a credential; every other path is
  forwarded untouched when nothing is presented. An `Authorization` header that
  is not this AS's own token (LiteLLM's UI bearer, an `sk-` in the OpenAI-SDK
  shape) is forwarded untouched everywhere and LiteLLM authenticates it. The
  `authz.legacyPassthrough` value and `AUTHZ_LEGACY_PASSTHROUGH` are gone (ported
  from ach `1abb5f7`, `d091c08`, `e26ec26`).
- `ackstorm-token`: finds the authorization server from the API host
  (`ACKSTORM_API`, default `https://api.ackstorm.ai`; RFC 9728 → RFC 8414)
  instead of a fixed issuer that no longer serves one; the loopback listener
  answers only `/callback` with the expected `state`, so a stray hit no longer
  ends the login; refreshes 10 minutes before expiry (callers cache the printed
  token); no network when the token is still fresh. The unused `scope` is gone.
- AS: every `refresh_token` grant is re-validated at the identity provider. Login
  requests `offline_access`; the Dex refresh token is kept ONCE per user (newest
  login wins — Dex keeps one per user and client) and replayed at Dex before the
  AS rotates its own token. A Dex refusal ends every session of that user
  (`invalid_grant`, the client goes back to login); Dex unreachable is a 503 and
  the presented token stays valid; a login Dex answers without a refresh token
  fails loud. Ported from ach `3194271`, `46a2101`.

## [0.12.0] - 2026-09-19

### Removed

- The server side of the OAuth front door (v0.8.0–v0.8.4): the authorization
  server (`app/oauth_as/` — RFC 8414/9728 metadata, DCR, PKCE authorize/token,
  JWKS, MCP scope grants and broker chaining), the `/api/internal/front-key`
  endpoint, the Go Envoy `ext_authz` service (`authz/`, its image and CI job) and
  the chart's `authServer`, `authz` and `istio` blocks with their templates. A
  separate service owns token issuance and the gateway check now. Settings
  `AS_ENABLED`, `AS_ISSUER_URL`, `AS_AUDIENCE`, `AS_SIGNING_KEY_PEM`,
  `AS_ACCESS_TTL_SECONDS`, `AS_REFRESH_TTL_SECONDS`, `AS_KEY_ENCRYPTION_KEY`,
  `AS_SERVICES`, `AS_MCP_REDIS_URL` and `INTERNAL_TOKEN` are gone; `AS_REDIS_URL`
  stays as the OpenWork Den's store (`app/store.py`). The OpenCode auth plugin,
  `ackstorm-token` and the OpenWork Den are unchanged.

## [0.11.2] - 2026-09-19

### Changed

- OpenCode auth plugin shows "SSO (browser)" and generic sign-in text; no
  organization name in the plugin (the provider id `ackstorm` stays: it is the
  catalog key, not branding). Package renamed `alitellm-opencode-auth`.

## [0.11.1] - 2026-09-19

### Fixed

- OpenCode auth plugin (0.1.1), from an external review: a request that read
  stale credentials right after a refresh no longer spends the already-rotated
  refresh token (re-read inside the shared refresh); a refresh never registers a
  new DCR client (it asks for a login instead); the loopback listener validates
  `state` before answering and survives a stray hit; a failed discovery is
  retried instead of poisoning the process; registration happens before the
  listener opens; HTTP calls time out after 15 s; the AS `issuer` is checked
  (RFC 8414 §3.3). `make test-plugin` pins the three reproduced bugs.

## [0.11.0] - 2026-09-19

### Added

- OpenWork Connect: `POST /v1/mcp/token` mints a 7-day MCP token and
  `/api/den/mcp/agent` speaks just enough Streamable-HTTP MCP (initialize,
  tools/list with `search_capabilities` + `execute_capability`, resources with an
  empty skill/automation index) for the desktop's Connect badge to turn green.
  The catalog is empty; `connectEnabled` is now advertised `true`. Contract and
  verified traps: `docs/references/openwork-connect.md`.

## [0.10.1] - 2026-09-19

### Fixed

- OpenWork brand logo is theme-neutral (green shield, slate wordmark): OpenWork
  renders one `brandLogoUrl` on both light and dark sidebars, and the previous
  near-white wordmark vanished on light.
- The Den catch-all answers every method with the Den `404 not_implemented`
  envelope; a `POST /v1/mcp/token` (cloud MCP, not served) got FastAPI's 405
  `{"detail"}`, unreadable in the desktop.

## [0.10.0] - 2026-09-19

### Changed

- OpenWork handoff page redesigned as the console's dark terminal card (green
  accent, shield-check lockup, primary "Open in OpenWork" button, mono link box
  with Copy, single-use/expiry footer). It shows `OPENWORK_BRAND_APP_NAME` and,
  when set, `OPENWORK_BRAND_LOGO_URL`.
- OpenWork brand defaults are now "AliteLLM Auth" / slug `alitellm-auth`, and the
  served marks (`/openwork/brand/{logo,icon}.svg`) are the console's shield-check.
  Customize with `openwork.brandAppName` / `brandLogoUrl` / `brandIconUrl` /
  `orgName` / `orgSlug` in the chart.
- The reference Den rig moved to `test/openwork-den/` (`den.mjs`, `smoke.sh`).

## [0.9.1] - 2026-09-19

### Fixed

- OpenWork's Settings input keeps only the origin of the organization server URL,
  so a desktop configured by hand called `<origin>/api/den` and opened
  `<origin>/?desktopAuth=1` (which the gateway sends to `/ui/`), never reaching
  `/openwork`. The Den API is now served at both `/api/den` and `/openwork/api/den`,
  and an origin-only sign-in URL landing on `/`, `/ui` or `/ui/` is redirected to the
  handoff page with its query intact.

## [0.9.0] - 2026-09-18

### Added

- OpenWork organization server ("Den") at `/openwork`, off unless `OPENWORK_ENABLED`
  (docs/plans/2026-09-18-openwork-den.md). The desktop signs in with the existing
  Dex session through a single-use, 5-minute handoff grant exchanged for a 30-day
  bearer token (AS store; `AS_REDIS_URL` required), then receives enforced desktop
  policy (`OPENWORK_BLOCKED_COMMANDS`, `OPENWORK_BLOCK_BROWSER_UPLOADS`) and ACKstorm
  branding (`/openwork/brand/{logo,icon}.svg`). Empty-but-well-formed catalogs for
  everything the desktop fetches at boot; a sign-out that revokes the token. No
  cloud MCP agent (the Connect badge stays "needs attention"). Chart block `openwork:`.
- `test/fake-den/`: the zero-dependency Node reference Den the contract was verified
  against with the real desktop.

## [0.8.4] - 2026-09-18

### Fixed

- Every token the AS signs carries a `jti`; a broker (mcp-oauth ≥ b9b7638) spends a
  `login_hint` by it on first use, so a hint kept by an access log or a browser
  history cannot start a second ceremony in the user's name.

## [0.8.3] - 2026-09-18

### Fixed

- The broker chain names the grant owner. `_chain_next` now sends the broker a
  `login_hint`: an RS256 JWT signed by the AS, `sub` the user, `aud` the broker's
  store name, 10 min. A broker built on mcp-oauth ≥ b4d9d6c with
  `AUTH_BROKER_HINT_ISSUER` keys the grant by it instead of by the account chosen at
  the provider, which Zoho never names (`an account the provider did not name`) and
  which need not be the platform's email at GitLab or Slack.

## [0.8.2] - 2026-09-17

### Added

- OpenCode auth plugin served by the API at `GET /public/opencode-auth` as an npm
  tarball (baked from `clients/opencode` at image build):
  `opencode plugin https://platform.ackstorm.ai/public/opencode-auth -g`, then
  `opencode auth login -p ackstorm`. The plugin has no configuration: it takes the
  provider's API URL from opencode and discovers the authorization server through
  RFC 9728 / RFC 8414.
- README "Clients" section: OpenCode plugin, `ackstorm-token` wiring for Claude Code
  (`apiKeyHelper`) and Codex (`auth.command`).

## [0.8.1] - 2026-09-17

### Fixed

- `/oauth/token` answered 500 in the published image: `python-multipart`, which
  Starlette needs to parse the form body every OAuth token request carries, was
  only a dev dependency. Now a runtime dependency.

### Security

- Clear all 16 open Dependabot alerts (8 high, 8 moderate). UI: `react-router`
  7.16→7.18.4, `vitest` 3→4.1.11 (only patched line), transitive `browserslist`,
  `baseline-browser-mapping`, `postcss`, `nanoid`, `form-data`. Docs:
  `mkdocs-material` 9.5.49→9.7.7. None were reachable at runtime except the
  react-router `<Link>` open-redirect bypass; the rest are build/test/docs-time.

### Fixed

- `python-multipart` was missing from the runtime dependencies, so
  `POST /oauth/token` (`request.form()`) returned 500 in the v0.8.0 image and
  in CI with a fresh resolve (starlette ≥ 1.6 asserts on it). Added to
  `pyproject.toml`.

### Added

- `scripts/release-check.sh`: `release.yml` and `make release-cut` now fail when
  `Chart.yaml`, `values.yaml` `image.tag`, `pyproject.toml` or `main.py` are not
  at the version being released (guards against cutting without `release-bump`).

## [0.8.0] - 2026-09-17

### Added

- **OAuth front door for `api.*`.** An Envoy ext_authz service (`authz/`, Go) in
  front of LiteLLM and an OAuth 2.1 authorization server in the API
  (`/oauth/*`, `/.well-known/oauth-authorization-server`, RFC 7591 DCR, PKCE
  S256, RS256 tokens, refresh rotation with a LiteLLM re-check). The authz maps
  a platform credential — a LiteLLM key or a front-door JWT, in `x-genai-api-key`
  or `x-api-key`, or the JWT in `Authorization` — to the caller's LiteLLM key in
  `x-litellm-api-key`; any other `Authorization` belongs to the upstream provider
  and is left alone. Anonymous requests get a 401 with `resource_metadata`.
- **Every RFC 9728 protected-resource document is ours**, root and one per
  `/mcp/<svc>`, on `api.*` (gitops route prefix). LiteLLM composes none.
- **MCP grants as token scopes.** The token's `scope` lists the MCP services the
  user holds a grant for, read from the MCP pods' Redis projection
  (`AS_SERVICES`, `AS_MCP_REDIS_URL`). On `/mcp/<svc>` a user token without
  scope `<svc>` gets a 403 `insufficient_scope` pointing at that service's
  document; the `/authorize` ceremony chains to the service's mcp-oauth broker
  for the missing consent, one browser round, no tool call.
- Chart: `authz.*`, `authServer.services`, `authServer.mcpRedisUrl`; the Istio
  `AuthorizationPolicy` template documents the gitops-side prerequisites.

## [0.7.3] - 2026-09-17

## [0.7.1] - 2026-08-22

### Fixed

- **`GET /api/session/stats` under-reported older days in a window as heavy usage
  grew.** `user_daily_activity`'s pagination page count tracks request *volume*, not
  days-in-range — LiteLLM splits a single busy day's rows across as many pages as
  its volume needs (confirmed live: a 7-day window needed 15 pages, one day alone
  spanning 6 of them). The old `max_pages=12` (sized for "days in a 366-day range")
  silently dropped the oldest pages once volume grew past that, which read in the
  dashboard as spend/requests having all happened on the last day or two instead of
  spread across the window. `max_pages` is now a generous safety ceiling (500), not
  a days-based estimate.

## [0.7.0] - 2026-08-15

## [0.6.1] - 2026-07-26

### Removed

- **BREAKING (deploy): the Kustomize base and overlay are gone.** `deploy/kustomize/` duplicated the Helm chart's Deployment/Service/Ingress/ConfigMap and had to be version-bumped in lockstep with it. The Helm chart (`deploy/helm/alitellm-auth/`, also published as an OCI artifact) is now the only install path. Users of `kubectl apply -k deploy/kustomize/...` must switch to `helm install` (see `deploy/README.md`) or vendor the last-released manifests. `make kustomize-build` is removed and `make release-bump` no longer rewrites an overlay tag.
- `PROVIDER_LABEL` setting and its `provider_label` key in `GET /api/config` — plumbed end to end but rendered nowhere (the sign-in provider chips are driven by `providers[]`).
- One-shot budget-migration CLI `scripts/backfill_user_budgets.py` — the D-16 lazy backfill in `ensure_team_and_user()` covers it on every login.
- Unimported shadcn primitives `components/ui/scroll-area.tsx` and `components/ui/separator.tsx`.
- Unwired `tests/playwright/` screenshot harness (no Make target, no workflow).
- `python-multipart` dependency — the API defines no `Form`/`File`/`UploadFile` route.
- `docker-compose.dev.override.yml` — a per-machine port remap; now gitignored.
- `formatTokens()` — a re-export of `abbreviate()`; call sites use `abbreviate` directly.

## [0.6.0] - 2026-07-23

### Added

- **STATS — sortable LATENCY per-model table.** The per-model latency table now sorts by column (Model/Req/Lat/p95/Err), reusing the same `SortIndicator`/`sortRows` infra as TOP API KEYS so it behaves identically; default sort is Req desc.

### Changed

- **KEYS header now matches STATS.** The KEYS tab (Dashboard) header replaces its bespoke 4-tile sparkline row with the STATS `KpiRow` — TOTAL REQUESTS · TOTAL TOKENS · SPEND (deltas + failed/output sub-notes over MTD) — plus a custom keys/teams tile, and adopts the same translucent sparkline treatment as STATS.

### Fixed

- **KEYS Spend tile matched to STATS.** The KEYS-tab Spend tile read `me.spend.current` and showed `0.00` while STATS showed the real figure for the same window; it now reads `stats.data.totals.spend` (the source STATS aggregates), degrading to an em-dash while stats are pending/errored.

## [0.5.34] - 2026-07-23

### Changed

- **STATS — panel summary rows span the full widget width.** Reverted the v0.5.33 full-width row reflow (LATENCY and TOP API KEYS are back in their side-by-side pairings). Instead, inside each widget the headline stat row (THROUGHPUT/LATENCY/ERROR RATE/TTFT and ACTIVE KEYS/REQUESTS/SPEND) now uses `flex justify-between` instead of an equal-column grid, so it stretches edge-to-edge instead of stopping at ~80% with a trailing empty column.

## [0.5.33] - 2026-07-23

### Added

- **Foreign keys are shown but management-locked.** Keys not minted by this service (`metadata.source != "token-factory"`, e.g. `ekid_`/`pkid_`) now appear in the console but cannot be deleted, made default, or moved between teams (the backend returns `409`); only disable/enable is allowed. Each key carries a `managed` flag and the UI hides the locked actions.
- **Internal teams are masked.** A key sitting in a team the user does not belong to (e.g. internal `ach-*` teams) shows its team as `(internal)`; the real team id/alias is masked server-side in `/api/session/keys` and never reaches the browser (degrades to the raw id only on a teams-fetch failure).

### Changed

- **STATS layout.** TOP API KEYS and LATENCY each get a full-width row (the usage-by-model and request-outcome donuts pair in one row above them) so long model/key names have room. The Keys table Key ID column is width-capped so long foreign aliases truncate instead of forcing horizontal scroll. The USAGE BREAKDOWN `CACHED IN` column header is renamed to `CACHED`.

## [0.5.32] - 2026-07-20

### Fixed

- **Minted keys no longer join a per-client LiteLLM access group.** Key generation used to create/attach an access group named after `OAUTH_CLIENT_ID` (a DEX-auth concern only) and set it on every key's `access_group_ids`. Because the key-level access group is an **additive** grant that bypasses the team ceiling, this silently granted every user whatever MCP servers / models happened to be attached to the equally-named group — e.g. an ACH `Environment` sharing the client id `platform` leaked its GitLab/Slack/Zoho servers to all users. Keys now carry **only their team**; resources are scoped exclusively via team membership (`team.models`, `team.object_permission`, ACH `authorizedTeams`). Removed `_ensure_access_group` and both call sites. **Backfill**: pre-existing keys still carry the stale `access_group_ids` and must be cleared out-of-band (kubectl / LiteLLM API).

## [0.5.31] - 2026-07-11

### Added

- **STATS — LATENCY headline restructured.** The panel now leads with the metrics that matter operationally — **Throughput · Latency (p50) · Error rate · TTFT** — as a tile row; the percentiles are de-prioritized to the per-model table (which keeps a **p95** column). The per-model name pills lost their clashing colors and render as plain mono text.
- **STATS — TOP API KEYS summary.** A top summary row (**Active keys · Requests · Spend**) mirroring the LATENCY panel, plus a prettier gradient usage bar.
- **STATS — custom date-range label.** Picking a **Custom** range now shows the resolved `start – end` under the presets (right-aligned with the subtitle); presets already name their own window, so the label is Custom-only.
- **MODELS — mode filter.** A data-driven **Mode** filter row (**Chat / Embeddings / Audio / Image / Video**) sits above the search/capabilities row, showing only the buckets actually present.
- **Team colors.** A stable per-team categorical color (`--cat-1..5`, by position in the shared teams list) so a team reads as the same hue everywhere it appears — the Dashboard **Teams** tile and the Keys table.
- **Budget run-rate projection.** A shared budget meter (used by both the Dashboard budget bar and the Stats BUDGET panel, so they can't drift) draws a translucent "on track to reach here" ghost from current spend to the month-end projection (monthly durations only, when projected > current).

### Changed

- **STATS — KPI cards made uniform.** All four cards share one layout: the value with its optional detail inline beside it (muted parens), and the period-over-period delta chip on its own line below. **TOTAL TOKENS** now shows the **output-token share** (`… out · N%`) instead of the cache-hit rate (which confused more than it helped).
- **STATS — USAGE BY MODEL dominant slice** now uses the active skin's **primary** color instead of a fixed green, so the leading model tracks the theme (matches the `TOTAL` figure) instead of clashing on the non-green skins.
- **MODELS — "WEB" capability chip renamed to "SEARCH."**
- **DASHBOARD — metric / team / budget cards compacted** (tighter padding and sparkline band).
- **Date-range preset pills** get a faint surface fill so the idle frame stays visible on the pastel skin (where the border alone vanished against the gradient).

### Fixed

- **STATS — clicking CUSTOM no longer changes the charts before you pick a range.** Opening the calendar used to immediately refetch a default 30-day window; the range (and the switch to the Custom preset) now commit only on **Apply**.

## [0.5.30] - 2026-07-11

### Added

- **STATS — latency + request-outcome panels.** Two new supplementary panels on the Usage & Spend page, sourced from LiteLLM `/spend/logs/v2` (per-user via `x-user-id` impersonation, bounded by page size — no OOM) over the same date range as the rest of the page: a **LATENCY** panel (p50/p95/p99, TTFT p50/p95, throughput, and a per-model latency table with colored name pills) and a **REQUEST OUTCOMES** success/failure donut. Both degrade to a calm "not available" state and never fail the page. Gated on the user-scoping contract.
- **A2A — table search.** A search box (left of the row) filters agents by name and description, mirroring MCP and Models.
- **MODELS — "All" capability filter.** An **All** chip (selected by default) sits with the Vision/Thinking/Tools/Web toggles and clears any active capability filter on click.

### Changed

- **UI polish across STATS / MODELS / MCP / A2A / DASHBOARD.**
  - **STATS** — tighter vertical rhythm between panels; the **TOTAL TOKENS** card shows the output split + cache-hit rate inline in muted parens (matching TOTAL REQUESTS); the USAGE BREAKDOWN search + CSV export share one row and export is now a compact download **icon** button.
  - **MODELS / MCP / A2A** — the table search now sits on the **left** of the filter row.
  - **DASHBOARD** — the team tile is labelled **"Teams"** (was "Team") and drops the "Your teams" caption.

### Removed

- **STATS** — the `$ / 1M TOK` column from the Usage Breakdown table.
- **MCP** — the "N servers · M tools" summary bar (the counts were redundant with the visible cards).

## [0.5.29] - 2026-07-09

### Added

- **Console UI review improvements across KEYS, MODELS, MCP, STATS, and HOW-TO.** A batch of screen refinements from the design review:
  - **KEYS** — the "Last used" column now shows a relative time ("2h ago", "Never used") with an amber stale marker for keys unused ≥30 days; a new **TPM / RPM** rate-limit column (em-dash when unset).
  - **MODELS** — auto-router aliases show **"Dynamic"** for price/context instead of a misleading `$0.00 / $0.00`; a **capability filter toolbar** (Vision / Thinking / Tools / Web) and a **table search**; a per-row **copy-curl** button that emits a ready-to-run call to the alias (key stays the `sk-...` placeholder).
  - **MCP** — a **summary bar** (server + tool totals), a prominent tool-count chip, a clearer **"server auth"** label (auth is gateway↔server, your access is always key-authed), long tool lists collapse to 6 + "+N more", and a table search.
  - **STATS** — a **failed-requests** trend metric on the requests chart; the "Model Breakdown" is now **"Usage Breakdown"** with a **TYPE** column that splits real models from **MCP Tool** rows (whose token/cost cells blank to em-dash, not `$0.00`); a per-model **Cached-input** column (aggregated `cache_read_input_tokens`); a spend-card **pricing tooltip** and a stacked token split; **% used** and a **projected month-end** figure on both budget bars.
  - **HOW-TO** — Python/TypeScript **quickstart tabs** + an expected-response block; a **Troubleshooting** section (401/404/429/MCP errors); an OpenAI-compat env hint; **client-specific MCP config tabs** (Cursor / Claude Desktop / VS Code / Generic); a **model picker** that personalizes the quickstart snippets.
  - **DASHBOARD** — the multi-team tile is captioned "Your teams".

## [0.5.28] - 2026-07-03

### Removed

- **BREAKING: the legacy browser key endpoints are gone — sign-in is now keyless and UI-only.** `GET /api/oauth/login` and its callback no longer mint a virtual key or render a key card; the callback eager-creates the LiteLLM user (idempotent) and redirects to the `/ui` console. Removed `GET /api/oauth/reveal`, `GET /api/oauth/tokens`, `DELETE /api/oauth/tokens/{id}`, the `action=login` minting path, and the `success.html` template. This fixes an unwanted side effect where the SPA's silent mid-session expiry redirect hit the bare `/api/oauth/login`, which defaulted to the minting flow and created a fresh `sk-` on every session expiry (key proliferation). `GET /api/oauth/whoami` (header-authed key → identity resolver) is kept. Create/list/delete keys from the console via `/api/session/keys`.

### Changed

- **How-to: the OpenCode config now reads the key from the `LITELLM_API_KEY` env var.** Both OpenCode variants (Gemini + OpenAI) use opencode's `{env:LITELLM_API_KEY}` interpolation for `apiKey` instead of a literal `sk-...` placeholder, and the notes tell you to `export LITELLM_API_KEY=…` before running `opencode` — matching the Codex flow.
- **Internal refactor — deduplicated three repeated blocks in the API; no behavior change.** Extracted `_require_team_membership` (the team-membership 403/502 guard shared by key-create and move-team), `_degrading_catalog` (the shared MCP/A2A read-only catalog handler with its 404-degrade path), and `_is_key_dict` (the non-dict `/key/list` row guard). 239 pytest green; net −44 lines.

## [0.5.27] - 2026-07-02

### Changed

- **Internal refactor — deduplicated repeated scaffolding across the API and UI; no behavior change.** Extracted shared helpers for four copy-pasted patterns: `_raise_litellm` (23 identical LiteLLM error-raise blocks, error message format now uniform), `_relist_or_502` (5 identical key-relist error handlers), `_list_catalog` (the models/MCP/A2A catalog scaffold), and `_oidc_redirect` (the login/reveal/tokens OIDC flow start); on the console, a `useKeyMutation` factory backs the five key-lifecycle mutation hooks. Also removed three verified-dead items (an unused admin return value, an unused `CreatedKey` type, and a `'team'` spend-source that the server never emits). All security invariants preserved (the login `?action` whitelist, the `x-user-id` catalog scoping, and the admin constant-time key compare are untouched). Net −123 lines; 257 pytest / 389 vitest green.

## [0.5.26] - 2026-07-02

### Changed

- **How-to: the Claude Code (API) tab now flags that WebSearch won't work through the gateway.** WebSearch is an Anthropic server-side tool, so it errors when Claude Code is pointed at the LiteLLM gateway. The how-to now explains this, shows a copyable `~/.claude/settings.json` snippet that denies the built-in `WebSearch` tool (and notes to add `WebFetch` if it also errors), and points users at an external search MCP server to restore web-search functionality. Several faint how-to notes (per-tool notes, the "swap your key" line, the not-ready placeholder) were also bumped to a more legible text color.

## [0.5.25] - 2026-07-02

### Fixed

- **Expired session now redirects to login instead of a dead error.** When a session cookie expired mid-use, the console stayed on the authenticated shell and every data panel (Models, Stats, Keys, MCPs) showed a generic "couldn't load — check your connection" error with a RETRY button that could never recover. Any `/api/session/*` request that returns 401 after the session has loaded now routes through the existing expired-session path and silently redirects to the OIDC login (`/api/oauth/login`); with a still-valid SSO session this returns the user straight to where they were. A cold-load 401 still lands on the sign-in page as before.

## [0.5.24] - 2026-07-01

## [0.5.23] - 2026-06-27

### Added

- **Per-user multi-team support.** A user who belongs to more than one LiteLLM team can now see all of their teams and place virtual keys in any of them. The dashboard TEAM tile lists every member team as pills, the keys table shows each key's team in a new second column, the create-key modal gains a team picker, and a key's team can be changed after the fact from its per-key `⋯` menu. New endpoint `GET /api/session/teams` lists the signed-in user's teams; `POST /api/session/keys` now accepts an optional `team_id`; `POST /api/session/keys/{id}/team` moves an existing key. Every team choice is validated server-side against the user's real LiteLLM memberships — a key can never be placed in a team the user does not belong to (the email is always the authenticated session identity, never client input). NOTE: the per-user Models/MCP catalog is still scoped to the user's default-key team rather than the per-key team; per-team catalog scoping (an `x-user-id`/`sso_key_swapper` change) is a separate follow-up.

## [0.5.22] - 2026-06-25

### Added

- **TOTAL TOKENS now shows the input/output split.** The card's headline total is dominated by (mostly cached) input tokens, so it was misleading on its own — a single "863M" hid that ~99% was input and most of that was cache reads. The card now spells out the breakdown beneath the total: `856M in · 6.8M out · 93% cached`. The stats API exposes `input_tokens`/`output_tokens` on the window totals (from LiteLLM `total_prompt_tokens`/`total_completion_tokens`).

### Changed

- **Unified the in-page segmented-selector styling.** The Stats date-range presets, the How-to tool/variant tabs, and the MCP section tabs now share one set of active/idle pill tokens (`lib/ui.ts`), so the selected-state treatment no longer drifts per route. KPI tiles also gain leading icons matching the dashboard, plus related Stats/Dashboard/nav polish.

## [0.5.21] - 2026-06-25

### Fixed

- **Stats no longer under-report usage for multi-page windows.** The Usage & Spend totals (requests, tokens, spend) and the dashboard's "Requests (MTD)" tile read the window total from LiteLLM's `/user/daily/activity` response metadata, on the assumption it was aggregated across the whole range. On LiteLLM v1.89.2 that metadata is only a *per-page* partial, so any window large enough to paginate showed the last (oldest) page's slice — e.g. a month-to-date figure surfaced 220 of 10,588 real requests and 5.59M of 850M tokens, while the 7-day figure (which fit one page) was correct. The per-page totals are now summed across every fetched page (boundary days split cleanly across pages, so there is no double-counting).
- **The per-user model catalog is now scoped to the user's team, not the global admin list.** The console's Models page calls LiteLLM with the master key plus an `x-user-id` header; the gateway custom auth impersonates the user's default key. The hand-built impersonation identity omitted `team_models`, so a key whose models are `["all-team-models"]` resolved to *no* restriction and the catalog routes (`/v1/models`, `/model_group/info`) returned the full proxy model list — every user saw the entire admin catalog. The impersonation identity now carries the team's model access, so the catalog matches what the user's own key returns. (Canonical copy of the gateway `auth_user_map` custom auth; the live fix is deployed separately on the LiteLLM proxy.)

## [0.5.20] - 2026-06-19

### Changed

- **The shared LiteLLM team is now named `default`.** Its id and display alias previously came from `OAUTH_CLIENT_ID` (`team-<client_id>`, e.g. `team-platform`). Both are now driven by the new `LITELLM_DEFAULT_TEAM` setting (Helm value `config.litellmDefaultTeam`, Kustomize env), defaulting to `default` and decoupled from the OIDC client. On the next deploy the service points at the new team; pre-existing keys, budgets, and members stay on the old team and are migrated out-of-band (kubectl), not in code.

## [0.5.19] - 2026-06-13

### Fixed

- **The header menus no longer garble the page on mobile.** Opening the hamburger nav or the user menu on a narrow screen reflowed the page content into a collapsed, one-word-per-line column. Both were Radix *modal* dropdowns, which scroll-lock the page while open by mutating `<body>` (`overflow`, `position`, scrollbar-gap padding) — harmless on desktop, but on a phone-width viewport that mutation squeezed the content column. They are pure navigation menus, so they are now non-modal: opening one no longer touches the rest of the page. Desktop layout unchanged.

## [0.5.18] - 2026-06-13

### Fixed

- **Top navigation is now usable on mobile.** The sticky header (0.5.16) overflowed the viewport width on phones: the full nav row made the header wider than the screen, which silently disables `position: sticky`, so it scrolled away instead of staying pinned. On narrow screens the primary nav now collapses into a hamburger menu, and the user menu compacts to just its rounded avatar (the name, chevron, and pill border return at `sm`+). The header fits the viewport again and stays sticky. The desktop layout is unchanged.

## [0.5.17] - 2026-06-13

### Fixed

- **Stats no longer OOM-kills the pod.** The per-model "last used" column on `/api/session/stats` was sourced from `GET /spend/logs?summarize=false`, which ignored its `user_id`/date filters and returned the *entire* spend-logs table (~83 MB even for a single user over 7 days). Parsing that JSON into Python objects on every request — multiplied by concurrent requests — exhausted the pod's memory (OOMKilled) and made the Stats page take ~12 s to load. Last-used is now derived from the daily-activity window the route already fetches (day granularity), so the 83 MB call is gone entirely: no extra HTTP, no large parse. The A2A page and other endpoints that were collateral-slow during the OOM thrash recover with it.

## [0.5.16] - 2026-06-12

### Changed

- The top navigation bar is now **sticky** — it stays pinned to the top of the viewport while scrolling long pages (Stats, How-to) instead of scrolling away.
- Reordered the **How-to → Editors & CLIs** tabs to surface the most-used setups first: OpenCode (Gemini), OpenCode, Claude Code (API), Claude Code (Pro/Max), Gemini CLI, then Codex, GitHub Copilot, Qwen Code. OpenCode (Gemini) is now the default-selected tab.

## [0.5.15] - 2026-06-11

### Changed

- Sortable tables: the **Models** catalog and the dashboard **API Keys** table now carry an explicit default sort (Models by name; API Keys newest-created first), so the active sort column is always marked on load — matching the Stats tables.

### Removed

- Removed the disabled "Memory (soon)" placeholder from the top navigation.

## [0.5.14] - 2026-06-11

### Fixed

- Docker: install uv from the pinned official image (`ghcr.io/astral-sh/uv`) instead of `pip install uv`. On `python:3.14-slim`, an uv release with no cp314 wheel made pip fall back to building uv from source, which fails on the slim image (no C toolchain → `linker cc not found`) and broke the release image build. The prebuilt static binary is reproducible and never compiles.

## [0.5.13] - 2026-06-11

### Added

- Sortable tables: every column header on the **Stats → Model Breakdown** and **Top API Keys** tables, the **Models** catalog, and the dashboard **API Keys** table is now clickable to sort. Numbers sort numerically, text alphabetically, and missing values always sort last; clicking a column toggles ascending/descending with an arrow indicator. The Model Breakdown still defaults to spend-descending.

## [0.5.12] - 2026-06-11

### Changed

- Budget: the per-user cap (`max_budget_in_team`) is now applied only when a user is first created, never overwritten on later logins or key creation. A manually- or GitOps-raised per-user cap now survives re-logins instead of being silently reset to the factory `user.max_budget` default (which would re-block a user who had a higher cap). The factory value seeds new users only; existing users keep their cap until changed explicitly.

## [0.5.11] - 2026-06-11

## [0.5.10] - 2026-06-10

### Changed

- Stats: each KPI card shows its failed/cached figure inline in smaller muted parentheses next to the value (e.g. `77 (5 failed · 6.5%)`), with the period-over-period chip on its own line below; the no-baseline chip reads `▲ 100% (no info)`.

## [0.5.9] - 2026-06-10

### Added

- Stats: period-over-period delta chips on the four KPI cards (green/red by direction; spend deltas inverted). When the prior period had no baseline (e.g. 0 tokens), the chip shows a neutral grey "▲ no previous info" instead of disappearing — so every active metric shows the comparison state.
- Stats: per-model $/1M TOK efficiency column in Model Breakdown.

### Changed

- Stats: TOP API KEYS hides idle (zero-usage) keys by default behind a "Show idle keys (N)" toggle.
- Stats: usage donut legend strips the shared provider/ prefix (full model name on hover).
- Stats: per-day token counts in the series + REQUESTS/TOKENS toggle on the daily chart.
- Stats: failed requests surfaced — destructive sub-line on TOTAL REQUESTS + red failed segment stacked on the daily requests bars.
- Stats: CSV export for the model breakdown.
- Stats: cached-input percentage on the TOTAL TOKENS card.
- Stats & Dashboard: the account budget bar colors by usage — neutral grey under 80%, warning orange from 80%, red from 90% (and over budget) — so it stays legible even in the red theme.

### Fixed

- Stats: charts no longer interpolate across days with no usage — missing days are zero-filled server-side.
- Stats: the AVG COST KPI is now cost per 1M tokens (previously computed per 1K requests).

## [0.5.8] - 2026-06-10

- fix: the **Stats** time-series charts (Daily spend, Requests by day) now plot **oldest → newest left-to-right** (chronological). They previously rendered newest-first, so the x-axis ran backwards.
- change: the **Key created** dialog is reworked for clarity — the one-time notice is now plain professional prose mirroring the upstream LiteLLM dialog (no tinted callout), with the **"you won't be able to view it again."** clause bold inline; the secret key itself is no longer bold and is sized to match the body text.
- change: **HOW-TO → Codex** now documents the `~/.codex/config.toml` provider block (`model_provider` + `base_url` + `env_key`) instead of `OPENAI_*` env vars, with the env-var approach kept as a fallback.

## [0.5.7] - 2026-06-08

- feat: new **A2A** tab — a per-user, read-only catalog of the **Agent-to-Agent** agents registered on the gateway, sourced server-side from LiteLLM `GET /v1/agents` (A2A gateway, beta) and projected to a PUBLIC subset (name, version, endpoint, transport, streaming, skills — never headers/params/credentials). Scoped to the signed-in user through the same gateway custom-auth path as Models/MCPs, and gated on a default key. A calm "not enabled" state covers deployments with no A2A gateway. New endpoint: `GET /api/session/a2a`.
- feat: the topbar **user identity** is now an avatar + name **dropdown menu** (with **Log out**), replacing the inline name + "sign out" link so the identity reads as one affordance. A disabled **MEMORY** nav item (with a small "soon" marker) marks the next surface.
- feat: the console now ships a **favicon** — the shield-check brand mark (inline SVG, theme-green).
- fix: **Stats → Top API keys** now shows each key's **friendly name** instead of the opaque `lk-…` spend-log id. The per-key spend rows are joined to your key list server-side, which also collapses the duplicate zero-usage row the table used to render for the same key.
- change: the ambient **background glow** is anchored to the viewport, so every page renders the same gradient instead of shifting with page height.
- change: the **Key created** dialog gives the one-time warning more weight (icon + callout) and renders the secret key in high-contrast ink/white on a muted slab for easier copy-and-store.

## [0.5.6] - 2026-06-08

- change: the **HOW-TO** MCP servers section is now compact tabs — **MCP Access** (full config), **MCP Group access** (`x-mcp-servers` / `/mcp/<group>` scoping), and **Try with curl** (a no-LLM `tools/list` + `tools/call` smoke test over the MCP REST API).
- feat: **HOW-TO** **OpenCode** gains a second tab — **OpenCode (Gemini)** — wiring its native `google` provider to the gateway's `/gemini/v1beta` passthrough.
- change: **HOW-TO** polish — `codex`/`opencode` tabs renamed **Codex**/**OpenCode**; tab triggers now show a pointer cursor; the **ACKstorm Chat** open-in-new icon is accent-green (vs muted for the not-yet-wired openwork); the openwork badge reads **SOON**.
- change: the topbar **Chat** button is restyled as an accent CTA (tinted accent fill + border + hover lift + an open-in-new-tab icon) so it clearly reads as a clickable external destination, while staying distinct from the selected nav tab.

## [0.5.5] - 2026-06-08

- change: the dashboard **Account budget** now shows the budget **period** (e.g. `$0.17 of $100.00 / 30d`) so the cap is unambiguous.
- change: the **Stats** page **Budget status** panel now shows the same budget **period** (e.g. `$0.17 of $100.00 / 30d`), matching the dashboard.
- change: default factory limits updated — **team** 200 budget / 30d, **user** 100 budget / 30d, both `rpm_limit: 100`, `tpm_limit: 1,000,000` (best-effort throughput). (Helm `values.yaml` + Kustomize configmap; applies to deployments that adopt the defaults.)
- feat: **HOW-TO** adds **GitHub Copilot** (VS Code proxy override) and **Qwen Code** CLI setups, each linking its authoritative LiteLLM guide.
- feat: **HOW-TO** gains an **MCP servers** section — how to point MCP clients at the gateway's `/mcp` endpoint with your virtual key, scope the exposed tools with the `x-mcp-servers` header (servers and/or groups), or target a group directly via the `/mcp/<group>` URL.
- feat: new **`CHAT_PUBLIC_URL`** setting (Helm `config.chatPublicUrl` + Kustomize env) for the hosted-chat link (CHAT nav button + How-to card). When unset the SPA still derives `chat.<domain>` from the gateway host, so this is backward-compatible; set it when chat does not live at `chat.<same-domain-as-api>`. Exposed via `GET /api/config`.

## [0.5.4] - 2026-06-06

- fix: **key names no longer collide between users (or with your own keys).** LiteLLM requires a globally-unique `key_alias`, so two people both naming a key "default" failed ("Key with alias 'default' already exists"). The stored alias is now an opaque `lk-{random}` token while your friendly name is shown in the table — so any number of keys (yours or others') can share a name.
- change: **HOW-TO** editor/CLI setup — **opencode** now ships its real `opencode.json` config (an OpenAI-compatible provider pointed at the gateway) and **codex** is marked ready; **Claude Code** and **opencode** link their authoritative LiteLLM guides.
- change: the **Models** page subtitle no longer wraps early — it uses the full width.

## [0.5.3] - 2026-06-06

- change: the dashboard **API Keys** section now uses a large page-style heading (matching the Models/Stats pages) instead of the small mono caption.
- feat: **disable / enable a key** without deleting it — the `⋯` row menu now offers **Disable key** (and **Enable key** when disabled), backed by LiteLLM `/key/block` + `/key/unblock`. A disabled key shows a **Disabled** status pill, its row is dimmed so it reads as inactive at a glance, and it is excluded from the Active-keys count. Any key may be disabled, including the default (Chat/Models/MCPs stay gated on it, so they pause until it is re-enabled).

## [0.5.2] - 2026-06-06

- fix: virtual keys are no longer route-restricted at creation. Pinning `allowed_routes=["llm_api_routes"]` made the per-user **Models**/**MCPs** catalog fail with a 403 ("Only allowed to call routes: ['llm_api_routes']") once a key was scoped via `x-user-id` — the catalog needs read/info routes like `/model_group/info`. Keys now show "All routes allowed" (still gated by role; management routes remain admin-only) and a deployment can re-restrict via factory `key.allowed_routes`.
- feat: the keys table **Last used** column is now populated from LiteLLM's per-key `last_active` (shows "—" until the key is first used).
- feat: when you have **no default key, the key you just create becomes the default** (a presence check, not positional — so your first key is default, and you are never left without one). When a default already exists it is never reassigned automatically.

## [0.5.1] - 2026-06-06

- feat: a **red** corporate theme — the topbar toggle now cycles dark → light → pastel → red (coral-red primary on white surfaces with deep-navy ink); persisted to localStorage and applied before first paint.
- change: topbar nav restyle — the active tab now carries a strong filled highlight, items are separated by `|`, and **Chat** moves next to the user as a low-contrast pill (no longer reads as the selected tab).
- change: the keys table **DEFAULT** marker is now a neutral grey pill (matching the Models catalog) instead of the green accent badge — it is a property of the key, not a status.
- change: **Stats** now opens on the 7-day window by default (was 30 days), and the **Compare** toggle (with its period-over-period delta chips) has been removed.
- fix: the Stats **budget bar** rendered a tiny sliver regardless of spend — it treated the server's 0..1 `pct` fraction as a percentage. It now fills proportionally to spend ÷ budget.
- change: the **Models** and **MCPs** pages (and their nav links) now require a default key — they are scoped to your account through it. Without a default key the nav items are disabled ("you need a default key") and the pages show a prompt to set one on the Keys tab, instead of failing with an error. With a default key they load normally.
- feat: the service now **verifies the LiteLLM user-scoping contract at startup** — it checks that the `sso_key_swapper` custom auth (which resolves the `x-user-id` header to a user's default key) is installed on LiteLLM. If it is missing (a master-key request is accepted as full admin), a prominent CRITICAL banner is logged because per-user Models/MCPs would silently fall back to the global admin view. This is non-fatal and can be disabled with `LITELLM_USER_SCOPING_CHECK=false`. The custom-auth plugin and install/contract docs are now vendored under `deploy/litellm/`.

## [0.5.0] - 2026-06-05

- feat: a per-user **default key** — promote any key to your default from its `⋯` row menu ("Set as default"); the default carries a DEFAULT badge in the Key ID column and cannot be deleted until another key is promoted. A default is never auto-assigned (explicit only). Backed by a flag in the key's LiteLLM metadata.
- feat: a **Chat** button in the nav (set apart, accent-coloured) linking to `chat.{domain}`, enabled only when you have a default key (otherwise it shows "you need a default key").
- feat: a **pastel** theme — the topbar toggle now cycles dark → light → pastel (lavender/cyan/pink, with a frosted sign-in card and a gradient sign-in button); persisted to localStorage and applied before first paint.
- change: the **Models** and **MCPs** pages are now scoped to the signed-in user — the service sends an `x-user-id` header (with the master key kept server-side) so the catalog reflects that user's access, resolved by the gateway's custom auth.
- change: primary (green) buttons use white text in light mode for legibility; the pastel theme lightens its primary-button ink for readable contrast on the purple.

## [0.4.5] - 2026-06-05

- change: the Models table now renders through the same table component as the Keys table — matching header font/size, cell padding, row borders, and card chrome — so the two surfaces are visually consistent
- change: Models — "Thinking" is now its own column (after Mode) flagging reasoning models; the input/output prices are merged into one `$ / 1M (in / out)` column (mirroring the Context column); capability icons are neutral grey so they no longer look like clickable toggle buttons
- change: HOW-TO — the "No terminal?" section drops the Open WebUI card and adds an `openwork` card (github.com/different-ai/openwork) tagged "SOONER" (gateway support is not available yet)
- change: the deployment readiness probe initial delay drops from 30s to 5s so the pod starts serving sooner (the liveness probe initial delay is unchanged at 60s)

## [0.4.4] - 2026-06-05

- feat: HOW-TO onboarding page (`#/howto`) — a real guide replacing the placeholder: a Quickstart with a copy-paste `curl` to the `ackstorm.fast` alias (auto-personalized with the user's gateway base URL, `x-litellm-api-key: Bearer sk-...` header, `sk-...` placeholder only — never a real key), editor/CLI setup tabs (Claude Code + Gemini CLI with live env exports; opencode + codex are placeholders for now), and no-terminal chat-UI cards (ACKstorm Chat + Open WebUI). Sticky in-page TOC, theme-aware, copy buttons; fully static (no backend)
- feat: Models catalog page (`#/models`) + `GET /api/session/models` — the model aliases available on the gateway with provider(s), mode, context window, per-1M-token pricing, and capability badges (vision / tools / reasoning / web). Server-side master-key call to LiteLLM `/model_group/info` (the safe public group view — no upstream model / api_base / api_key leaks); an explicit field allow-list on the server
- feat: MCP page (`#/mcp`) + `GET /api/session/mcp` — the Model Context Protocol servers wired into the gateway (name, status pill, endpoint, transport, auth type, exposed tools, access groups). Server-side master-key call to LiteLLM `/v1/mcp/server`, projected to a PUBLIC subset (credentials / env / headers stripped); a 404 (no MCP gateway) degrades to a calm "not enabled" state instead of an error
- change: primary nav is now `KEYS · MODELS · MCPS · STATS · HOW-TO`

## [0.4.3] - 2026-06-04

- feat: light/dark theme — a sun/moon toggle in the topbar (and login), persisted to localStorage, defaulting to the OS preference; an inline pre-paint script applies the stored theme before first paint (no flash). The full light palette is authored as token overrides; the green identity is preserved
- feat: the dashboard "Requests (MTD)" tile now shows both requests and tokens for the month-to-date (e.g. `11 req / 10.02K tokens`), sourced from `/api/session/stats`
- change: the service indicator now reads "READY" (login card + inner-page footer, renamed from "STATUS") with an "All systems operational" tooltip; the "Spend MTD" tile label is now "Spend (MTD)" for consistency
- change: the keys table shows the key id as `id:` + the first 16 characters + ellipsis (prefix-truncated) instead of the `prefix…last4` mask
- fix: the STATS "Top API Keys" panel lists the user's keys even when they have no activity in the window (idle keys are padded with zeros and ranked by spend), instead of only the keys that appear in the spend logs
- fix: the STATS "Usage by Model" and "Top API Keys" panels are now equal height (the shorter one stretches to match its sibling)

## [0.4.2] - 2026-06-04

- change: refined the login sign-in card — a richer description (view / mint / revoke; "no password is handled here, sign-in is delegated to your SSO provider"), a decorative `$ sign-in --sso --provider=openid` terminal command line, and the READY status indicator moved from the card top to the bottom status strip (replacing "redirects to dex")
- change: the inner pages (dashboard, stats, how-to) now carry the same subtle green radial gradient as the login screen, for a consistent backdrop

## [0.4.1] - 2026-06-04

- feat: primary nav reworked to a KEYS · STATS · HOW-TO segmented-pill menu (KEYS returns to the dashboard); new placeholder `#/howto` guide page; the service-status indicator moved out of the topbar into the footer (with an "All systems operational" tooltip — still static, no live health check)
- feat: the login "BACKED BY" chips now render the real Google and Dex brand glyphs (matched by provider label), with the green shield as the fallback for other providers (e.g. OIDC)
- change: login is a single centered sign-in card (the right value-props/overview column was removed); its header and footer are now full-width bars matching the inner pages, and the footer © aligns with the brand margin
- change: the keys table exposes only a Revoke action — the per-row copy and reveal controls were removed (the `sk-` is shown once, at creation); the key id renders masked as `id:first4…last4` and the actions column has a visible "ACTION" header
- fix: an expired key never renders as "Active" — expiry parsing now handles naive/space-separated ISO timestamps and epoch values, not just offset-bearing ISO (it previously fell through to Active for those shapes)
- fix: the revoke-confirm dialog names the key by alias (or masked id) and no longer overflows the dialog with the full key hash
- fix: copy buttons show a filled-green "copied!" state for 2s, and all interactive buttons now use a pointer cursor

## [0.4.0] - 2026-06-04

- change: rebuilt the `/ui` console from Preact + htm to React 19 (Vite, TypeScript, Tailwind CSS 4, shadcn/ui, TanStack Query, Zustand, hash router, Recharts) at full feature parity — OIDC login, key management (create with one-time `sk-` reveal, copy, revoke), and the Usage & Spend stats page; the `/ui` static mount and the `/api/session/*` JSON API are unchanged (no backend changes)
- change: the dashboard is now full-width (the right quick-actions sidebar was removed); the keys table shows the key id masked to `prefix…last4` (the full id is still copyable)
- change: the Usage & Spend page renders full-width (no left icon rail, no placeholder "Insights" panel); the spend/requests charts and the per-model usage donut were ported from uPlot to Recharts, themed to the green token set
- build: the SPA test suite (Vitest) is wired into CI as a `test-ui` job (`make test-ui`); the `ui-builder` Docker stage + the FastAPI `/ui` mount contract are unchanged across the rewrite

## [0.3.1] - 2026-06-04

- feat: read-only "Usage & Spend" page at `#/stats` — per-user requests, tokens, models, and spend with period-over-period KPI deltas, spend charts, a Model Breakdown table, a Top API Keys table, and a date-range filter; conflicting v2 extras (Export/PDF/Insights, real Team/Environment filters) render as non-functional "coming soon" placeholders
- feat: session-authenticated `GET /api/session/stats` — a server-shaped usage/spend contract scoped to the logged-in user's keys (sourced from LiteLLM spend logs via the master key, server-side) with per-figure graceful degradation (a `capabilities` map distinguishes "unavailable" from a real zero)
- feat: public `GET /api/config` — non-secret presentation config (brand, tagline, external links, SSO providers) consumed by the SPA so a deployment can re-brand the login and dashboard without a rebuild
- feat: login and dashboard re-skinned to the reference design — login topbar, "BACKED BY" provider chips, a richer overview, and a shared footer; the dashboard keys table is now a 6-column data-table with an expandable per-key detail row, icon actions (reveal/copy/revoke), status pills, and pagination
- fix: the account budget bar no longer renders a full-green 100% bar for a no-budget account (`$0.00 of $0.00`) — it shows a neutral empty track with "no budget set"
- fix: the keys data-table no longer overflows horizontally at standard viewport widths (Name merged into the Key ID cell; usage moved to the expandable detail row)
- change: removed the unused `GET /api/session/usage` passthrough (now `404`); its data source feeds `GET /api/session/stats`

## [0.3.0] - 2026-06-03

- feat: self-service dashboard SPA (Preact + htm + Vite) served same-origin by FastAPI at `/ui` — view identity + account budget, list keys with metadata/usage, reveal + copy a key, create a key, delete a key (with a confirm step); dark-terminal design system, `success.html`/`error.html` restyled to match
- feat: session-authenticated JSON API `/api/session/*` (`GET /me`, `GET/POST/DELETE /keys`, `GET /usage`) that reads the logged-in user from the OIDC session cookie — the browser never handles a master key or `sk-`; key ownership enforced server-side on delete
- feat: per-user budget enforcement via `/team/member_add` `max_budget_in_team`; budget applied at the user level on `/user/new`; key-level budget fields removed (never sends `max_budget: null`)
- security: session cookie hardened — `HttpOnly`, `Secure` (env-gated by `SESSION_HTTPS_ONLY`), `SameSite=Lax`, 8h `max_age`; state-changing `/api/session/keys` writes protected by an exact-origin fail-closed CSRF guard (no token needed for a same-origin SPA); startup guard crashloops an `https` deploy shipping a non-Secure cookie
- build: SPA baked into the runtime image via a Dockerfile `ui-builder` stage (runtime stays non-root, no node); `make build-ui`/`dev-ui`; CI `build-ui` gate
- chore: idempotent one-time budget backfill CLI (`scripts/backfill_user_budgets.py`, dry-run default, `--apply` to write)

## [0.2.0] - 2026-06-02
- BREAKING: rename GET /api/oauth/me → GET /api/oauth/whoami; old path now returns 404
- BREAKING: API header renamed x-ackstorm-api-key → x-alitellm-auth-api-key for /whoami and /api/oauth/tokens/{id}
- feat: create a LiteLLM User (user_id=email) on every login via /user/new before key generation; keys scoped to user_id
- feat: admin CRUD — GET /api/users, GET /api/users/{email}, DELETE /api/users/{email} (master-key authz via hmac.compare_digest)
- fix: harden user lookup for LiteLLM v1.83 — default_user_id placeholder triggers /user/list fallback; teams returned as objects normalized to alias-preferred strings
- fix: treat "already exists" 400/409 on /user/new as idempotent success (mirrors team-creation behavior)
- chore: rename package platform-api → alitellm-auth (version 0.2.0); k8s resources, secret name, configmap name updated accordingly
- docs: Dex/Keycloak OIDC integration guide (docs/dex-integration.md); README rewrite; CLAUDE.md corrected (removed false _email_to_team_id pattern, added real shared-team + User model, v1.83 quirks)
- feat: deploy/ — Helm chart + Kustomize base/overlays (replaces k8s/); chart published as an OCI artifact to ghcr.io/ackstorm/charts/alitellm-auth alongside the image

## [0a57794] - 2026-04-23
- Format pydantic ValidationError startup failures as a friendly list of missing env vars (no traceback) with a hint pointing at the k8s secret

## [b083d4c] - 2026-04-23
- Log traceback when create_app() fails at import time so real startup errors surface in pod logs (was silently setting app=None, causing cryptic "NoneType object is not callable" in uvicorn)

## [7f4fc93] - 2026-03-03
- Remove unrecoverable key hash from /reveal HTML and /tokens JSON response
- success.html: hide "Your API Key" section when key is None
- tokens action: strip "key" field from each token in JSON response

## [1a39192] - 2026-03-03
- Unify all OIDC flows into single /api/oauth/callback via session["oauth_action"]
- Remove /api/oauth/reveal/callback and /api/oauth/tokens/callback routes
- Add 3 new tests for login/reveal/tokens action dispatching (24 tests total)

## [f21333e] - 2026-03-03
- Simplify /api/oauth/me handler: pass-through dict from get_key_info instead of manual field mapping
- Add spend/max_budget/budget_duration/tpm_limit/rpm_limit/last_active to /me response
- Normalize spend default to 0.0 consistently across litellm_client and auth handler
- Remove dead _delete_key_by_alias function (superseded by timestamp-unique aliases)
- Fix get_key_info error message (was incorrectly referencing /key/delete)
- Refactor test_auth.py: shared client fixture, consolidated imports, full field assertions

## [f342a12] - 2026-03-02
- Add GET /api/oauth/me endpoint: validates x-ackstorm-api-key header against LiteLLM and returns user email + metadata as JSON
- Add get_key_info() to litellm_client; extract _admin_headers() helper to remove duplication
- Document endpoint in CLAUDE.md with curl example and response schema

## [87712be] - 2026-03-01
- Fixed access group API endpoint to /v1/access_group (confirmed via OpenAPI spec)

## [ccf551f] - 2026-03-01
- Fixed access group API: endpoint is /access_group, field is access_group_name, list returns array directly

## [a9bf980] - 2026-03-01
- Access group with same name as OAUTH_CLIENT_ID is created idempotently and each generated key is assigned to it via access_group_ids

## [01a7152] - 2026-03-01
- Key metadata now includes name (from OIDC), created_at (UTC ISO timestamp), and key_alias

## [3d1a88b] - 2026-03-01
- models and allowed_routes are now hardcoded defaults (all-team-models, llm_api_routes), overridable via configmap
- configmap: added rpm/tpm limits, max_parallel_requests, budget settings matching test key

## [0c78877] - 2026-03-01
- COPY button is now gray and right-aligned
- Key alias format changed to tf-{timestamp}-{email} — unique per login, no deletion of previous keys
- _delete_key_by_alias helper kept for future use

## [1bdefd0] - 2026-03-01
- Error page now shows the human-readable message from LiteLLM JSON response (error.message) instead of raw JSON

## [45ccd08] - 2026-03-01
- Key rotation on re-login: if alias already exists, old key is deleted and a fresh one is issued

## [dad43e1] - 2026-03-01
- Added factory_config_path to Settings (optional, defaults to None)
- Made platform-factory-config configmap volume optional in deployment.yaml so pod starts without it
- Added configmap.yaml example with user budget defaults
