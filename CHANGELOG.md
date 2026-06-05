# Changelog

## [unreleased]

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
