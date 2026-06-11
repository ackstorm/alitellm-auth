# Changelog

## [unreleased]

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
