# Changelog

## [unreleased]

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
