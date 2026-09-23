# alitellm-auth

FastAPI service that authenticates users via an OIDC provider (Dex/Keycloak) and lets each user create LiteLLM virtual keys (`sk-...`) from a React web console served at `/ui`. Sign-in is UI-only — the OIDC flow eager-creates the LiteLLM user and redirects to the console; keys are created/listed/deleted via the `/api/session/*` API. No OIDC-redirect endpoint hands back a key.

Companion to alitellm-operator (Go), which owns model/team discovery but not Users or VirtualKeys — Users and VirtualKeys are exclusively managed by this service.

**Stack (API)**: Python 3.12, FastAPI, Authlib (OIDC), httpx (LiteLLM), Jinja2, Starlette SessionMiddleware, uv, Docker/Kubernetes.

**Stack (UI console)**: React 19 + Vite 6 + TypeScript (strict) + Tailwind CSS 4 + shadcn/ui (Radix) + TanStack Query 5 + Zustand 5 + react-router 7 (hash) + Recharts + Vitest. A single-page app in `src/ui/` (rebuilt from the prior Preact SPA, 2026-06), built to `src/ui/dist` (`base: '/ui/'`) and served by FastAPI at `/ui` via the Dockerfile `ui-builder` stage. npm runs ONLY inside the devtools container: `make build-ui` (build → dist), `make test-ui` (vitest), `make dev-ui` (Vite HMR on :5173). **Dep bumps**: the container's npm 10.9 crashes with `Cannot read properties of null (reading 'edgesOut')` resolving jsdom's optional `canvas` peer — regenerate the lock with `npx -y npm@11 install` (NOT `--legacy-peer-deps`, that drops peers and breaks `npm ci`); `npm ci` on npm 10 then works. Full live dev stack (UI + API + mock OIDC + mock LiteLLM): `docker-compose -f docker-compose.dev.yml up` → http://localhost:5173/ui/.

---

## Architecture

`app/oauth_as/` is a port of `mcp-oauth/auth/broker.py` (sibling repo). Fix trust-path bugs in both.

```
Browser
  │
  ▼
GET /api/oauth/login              (SPA sign-in CTA + silent mid-session expiry redirect)
  │  authorize_redirect (authlib)
  ▼
OIDC Provider (Dex / Keycloak)
  │  redirects with ?code=
  ▼
GET /api/oauth/callback
  ├─▶ exchange code → id_token (email, name)
  ├─▶ POST /team/new  → LiteLLM  (idempotent, 409 = already exists)
  ├─▶ POST /user/new  → LiteLLM  (idempotent, user_id=email) — eager-create, NO key minted
  └─▶ 302 redirect → /ui  (or render error.html on failure)

Key lifecycle (create / list / delete) lives entirely in the /ui console via the
session API — POST/GET/DELETE /api/session/keys. There is NO OIDC-redirect route
that mints or reveals an sk-.

GET /api/oauth/whoami             (header-authed key → identity resolver, non-UI)
  ├─▶ validate x-alitellm-auth-api-key against LiteLLM
  └─▶ JSON response (key metadata + nested litellm_user)

GET /api/users (+ /{email}, DELETE /{email})
  ├─▶ master-key authz (x-alitellm-auth-api-key == LITELLM_MASTER_KEY)
  ├─▶ GET /user/list → LiteLLM  (list users)
  └─▶ JSON response
```

**Key files:**

| File | Responsibility |
|------|----------------|
| `src/api/app/config.py` | Pydantic-settings — all env vars |
| `src/api/app/auth.py` | OIDC routes + `oauth` module-level instance |
| `src/api/app/litellm_client.py` | `generate_litellm_key()`, `ensure_litellm_user()`, `get/list/delete_litellm_user()` |
| `src/api/app/admin.py` | GET/DELETE `/api/users` CRUD, master-key authz |
| `src/api/app/main.py` | `create_app()` factory + SessionMiddleware |
| `src/api/app/templates/` | `error.html` (dark terminal card; rendered on OIDC/callback failure) |
| `deploy/helm/` | Helm chart (deployment, service, ingress, configmap, secret) — the only install path |
| `src/api/app/openwork.py` | OpenWork desktop "Den" contract at `/openwork` (SSO handoff, policy, branding). Off unless `OPENWORK_ENABLED`. **MUST read `docs/plans/2026-09-18-openwork-den.md` §3 (protocol traps) before touching** — error shape, CORS reflection, single-use grant, catch-all order |

---

## API Endpoints

### `GET /api/oauth/whoami` — Resolve key → user identity

Validates a LiteLLM virtual key and returns the associated user metadata as JSON.

**Header:** `x-alitellm-auth-api-key: sk-...`

```bash
# plain key
curl -s https://platform.ackstorm.ai/api/oauth/whoami \
  -H "x-alitellm-auth-api-key: sk-XXXXXXXXXXXXXXXXXXXX" | jq .

# Bearer prefix also accepted
curl -s https://platform.ackstorm.ai/api/oauth/whoami \
  -H "x-alitellm-auth-api-key: Bearer sk-XXXXXXXXXXXXXXXXXXXX" | jq .
```

**Success response (`200`):**
```json
{
  "id": "key-XXXXXXXXXXXXXXXXXXXX",
  "user_id": "alice@example.com",
  "email": "alice@example.com",
  "name": "Alice Example",
  "team_id": "team-platform",
  "models": ["all-team-models"],
  "created_at": "2026-03-01T10:00:00+00:00",
  "expires": null,
  "spend": 0.0,
  "max_budget": 50.0,
  "budget_duration": "24h",
  "tpm_limit": 1000000,
  "rpm_limit": 100,
  "last_active": "2026-03-03T05:35:44.827000+00:00",
  "litellm_user": {
    "user_id": "alice@example.com",
    "email": "alice@example.com",
    "role": "internal_user",
    "spend": 0.0,
    "max_budget": 10.0,
    "teams": ["platform"]
  }
}
```

The flat `"user"` field was removed; user identity is now `user_id` plus the
nested `litellm_user` enrichment block. A valid key whose metadata lacks an
`email` is returned unenriched (no `litellm_user`).

**Error responses:**
| Status | Meaning |
|--------|---------|
| `401` | Missing header, or key not found / invalid |
| `502` | LiteLLM backend unreachable or returned 5xx |

### `GET /api/oauth/login` — Sign in (UI-only)

Starts the OIDC flow. On callback it eager-creates the LiteLLM user (idempotent,
`user_id = email`) and `302`-redirects to `/ui`. It **never** mints a key. The SPA
uses this route for both the sign-in CTA and the silent mid-session expiry redirect,
so neither can create a key.

Key create/list/delete is handled inside the console by the session API
(`POST`/`GET`/`DELETE /api/session/keys` — see `src/api/app/session.py`). There is
**no** OIDC-redirect endpoint that mints or reveals an `sk-` (the legacy
`login`-mint / `reveal` / `GET tokens` / `DELETE tokens` routes were removed).

### Admin Endpoints — /api/users (master-key only)

All admin endpoints require: Header `x-alitellm-auth-api-key` equal to `LITELLM_MASTER_KEY`.
Authorization uses `hmac.compare_digest` (constant-time, defends against timing attacks).

- `GET /api/users` — list all LiteLLM users (paginated, up to 10 pages of 100).
- `GET /api/users/{email}` — get a single user by email. Returns `404` when absent, `502` on LiteLLM failure.
- `DELETE /api/users/{email}` — delete a user (and their keys). Returns `{"status":"deleted","user_id":"..."}`.

**WHERE**: `src/api/app/admin.py`

### Public Static Artifacts

`GET /public/<path>` — a `StaticFiles` mount serving files placed in `/app/public`
by a volume, with no authentication at all. Today that is the OpenCode model
catalog alitellm-operator renders from `LiteLLMModelAlias` CRs, at
`/public/opencode/api.json`, consumed via
`OPENCODE_MODELS_URL=https://<host>/public/opencode`.

**This mount is world-readable.** The app has no global auth middleware (only
`SessionMiddleware`), and a `StaticFiles` sub-app carries no
`Depends(require_session_user)`. Mount ONLY non-secret artifacts. It is
registered AFTER every `/api/*` router so it cannot shadow them (T-09-06), and
uses `check_dir=False` because the directory is populated by a projected volume
at runtime, not at image build time.

Enabled by the chart's `publicArtifacts` values. The volume is `projected`, not
a plain `configMap` volume — a configMap volume owns the whole directory, which
would make a second artifact impossible to add — and carries NO `subPath`: a
subPath mount is resolved once at container start and never sees a ConfigMap
update, so the file would freeze at boot forever with no error surfaced.

**WHERE**: `src/api/app/main.py` (mount), `deploy/helm/alitellm-auth/templates/deployment.yaml` (volume)

---

## Critical Commands

```bash
# Virtual env (run from src/api/)
uv venv .venv && uv pip install -e ".[dev]"

# Tests
cd src/api && .venv/bin/pytest tests/ -v

# Run locally (needs .env)
cd src/api && uvicorn app.main:app --reload --port 8080

# Deploy code update to pod (no restart needed)
kubectl exec -n test <pod> -- bash -c "cd /app && git pull"
# uvicorn --reload detects changes automatically

# Create k8s secret
kubectl create secret generic alitellm-auth-secret -n test \
  --from-literal=SESSION_SECRET_KEY=$(openssl rand -hex 32) \
  --from-literal=OAUTH_CLIENT_SECRET=... \
  --from-literal=LITELLM_MASTER_KEY=sk-admin-...
```

---

## Release Process

**A GitHub Actions pipeline owns releases — DO NOT hand-roll one, and NEVER
`git tag` / `git push --tags` by hand** (it races the pipeline's own tag step and
skips GitHub Release creation). To cut a release: `make release-bump VERSION=X.Y.Z`
→ commit → `make release-cut VERSION=X.Y.Z` → `git push origin main`; CI does the
image, chart, tag, and Release. **Full steps, version-file table, and the manual-tag
failure/recovery: [docs/references/release-process.md](docs/references/release-process.md).**

---

## Common Failure Modes

### 1. MismatchingStateError on callback

❌ **WRONG** — `SessionMiddleware` missing or added after routes
```python
app.include_router(auth_router)
app.add_middleware(SessionMiddleware, ...)  # too late
```
✅ **CORRECT** — middleware BEFORE routes in `create_app()`
```python
app.add_middleware(SessionMiddleware, secret_key=settings.session_secret_key)
app.include_router(auth_router)
```
**WHY**: authlib stores OAuth `state`+`nonce` in the session cookie between `/login` and `/callback`. No session = state lost = error.

---

### 2. `SESSION_SECRET_KEY` not shared across replicas

❌ **WRONG** — auto-generate at startup per pod
```python
session_secret_key: str = Field(default_factory=lambda: secrets.token_hex(32))
```
✅ **CORRECT** — required field, set from k8s secret
```python
session_secret_key: str  # in k8s secret, same value on all pods
```
**WHY**: if `/login` hits pod A and `/callback` hits pod B with different keys, cookie verification fails.

---

### 3. LiteLLM team creation failing on second login

❌ **WRONG** — treating 409/400 "already exists" as an error
```python
team_resp.raise_for_status()  # explodes on 409 or 400
```
✅ **CORRECT** — older LiteLLM returns 409, newer returns 400 + "already exists"
```python
team_exists = (
    team_resp.status_code == 409
    or (team_resp.status_code == 400 and "already exists" in team_resp.text)
)
if team_resp.status_code != 200 and not team_exists:
    raise ...
```
**WHERE**: `src/api/app/litellm_client.py` — `generate_litellm_key()`

---

### 4. `TemplateResponse` wrong argument order (Starlette ≥ 0.36)

❌ **WRONG** — old signature
```python
templates.TemplateResponse("error.html", {"request": request, "error": msg})
```
✅ **CORRECT** — new signature (request first, no `request` in context dict)
```python
templates.TemplateResponse(request, "error.html", {"error": msg}, status_code=400)
```

---

### 5. Tests fail because `app = create_app()` runs at import time

❌ **WRONG** — bare module-level app fails without env vars
```python
app = create_app()  # ValidationError if env not set
```
✅ **CORRECT** — guarded with try/except in `main.py`
```python
try:
    app = create_app()
except Exception:
    app = None  # tests use create_app(settings=...) directly
```

---

### 6. `redirect_uri` is `http://` behind TLS ingress → Dex rejects it

❌ **WRONG** — scheme comes from internal pod request (HTTP)
```python
callback_url = request.url_for("auth_callback")  # → http://platform.ackstorm.ai/...
```
✅ **CORRECT** — build from `APP_BASE_URL` which is always `https://`
```python
callback_url = f"{settings.app_base_url}/api/oauth/callback"
```
**WHY**: nginx terminates TLS and forwards plain HTTP to the pod. `request.url_for()` sees `http://` scheme. Dex only has `https://` registered → `Unregistered redirect_uri`.

---

### 8. `make release-cut` without `make release-bump` first

❌ **WRONG** — cutting straight from a clean tree
```bash
make release-cut VERSION=0.7.2   # creates an EMPTY commit and pushes
```
The release tags and publishes with no error, and chart `version` /
`appVersion` are correct — but `values.yaml` still carries the PREVIOUS
`image.tag`, so the chart deploys the old image. Code that shipped in the new
image is simply absent from the cluster with nothing logged anywhere. Observed
on v0.7.2: the `/public` mount was in the image, the volume was mounted
correctly, and `/public/opencode/api.json` still returned 404 because the pod
ran v0.7.1.

✅ **RIGHT** — bump, commit, then cut (the order already stated under Release Process)
```bash
make release-bump VERSION=0.7.3        # Chart.yaml, values.yaml image.tag, pyproject.toml, main.py, CHANGELOG
git commit -am 'chore(release): v0.7.3'
git push origin main
```

**WHY IT IS EASY TO GET WRONG**: the sibling repo alitellm-operator has a target
with the SAME name whose `release.yml` runs `release-bump` itself and commits
the result, so an empty release commit is correct *there*. This repo's
`release.yml` does not bump anything — it expects the release commit to arrive
with the manifests already bumped. Verify after any release:
```bash
helm show values oci://ghcr.io/ackstorm/charts/alitellm-auth --version X.Y.Z | grep 'tag:'
```

**GUARDED**: `scripts/release-check.sh X.Y.Z` runs in `make release-cut` (before the
commit) and in `release.yml` (before the image build) and fails loud when any version
file is out of lockstep. It never auto-fixes — a self-healing release would hide the
skipped step.

### 7. OIDC provider registered as wrong name

❌ **WRONG** — provider name doesn't match call site
```python
oauth.register(name="dex", ...)
oauth.dex.authorize_redirect(...)  # works
oauth.oidc.authorize_redirect(...)  # AttributeError
```
✅ **CORRECT** — name is `"oidc"` everywhere
```python
oauth.register(name="oidc", ...)
oauth.oidc.authorize_redirect(...)
```
**WHERE**: `src/api/app/auth.py` — `configure_auth()` and all route handlers.

---

## LiteLLM v1.83 Quirks (hardening notes from ../ach)

**H1 — `/user/info` returns a placeholder instead of 404 for unknown users.**
When LiteLLM does not find a user by `user_id`, `/user/info` returns HTTP `200` with `user_id="default_user_id"` and `user_email=null` — NOT a `404`. The code detects this via `_is_placeholder()` and falls back to `/user/list?user_email=<email>` for an exact match. If the list also returns no match, `LiteLLMUserNotFound` is raised.
**WHERE**: `src/api/app/litellm_client.py` — `get_litellm_user()`

**H2 — `/user/info` returns teams as `[{team_id, team_alias}]` objects, not `[]string`.**
Do NOT decode teams as a list of strings — it will break silently. `_normalize_teams()` handles both formats (objects → alias-preferred strings, plain strings pass through).
**WHERE**: `src/api/app/litellm_client.py` — `_normalize_teams()`

**H3 — Never send `max_budget: null`.**
Sending `"max_budget": null` on `/user/new` can overwrite the deployer's configured default with null. The `ensure_litellm_user()` payload intentionally omits `max_budget` entirely.

**H6 — Always pass email via httpx `params={}`, never string concatenation.**
httpx encodes `@` → `%40` and `+` → `%2B` correctly. Manual f-string concatenation or url-encoding breaks with special chars.

---

## Per-user key scoping (v0.18.0)

Every per-user read — **Models** (`/api/session/models`), **MCPs** (`/api/session/mcp`),
**A2A**, keys and spend — goes to LiteLLM as `x-litellm-api-key: <the caller's own key>`
with **NO master key**, so LiteLLM's native auth scopes each answer by that key's own
team and access groups. The key is resolved from the AS store by
`app/internal.py::resolve_front_key` (the same credential the authz proxy injects) and is
NEVER taken from client input.

This replaced the `sso_key_swapper` impersonation (master key + `x-user-id`), which
failed **OPEN**: where the custom auth was absent, the master key authenticated as full
proxy admin and the "per-user" catalog was silently the global one. A virtual key has no
such mode, so no startup contract probe is needed — and none exists any more.

**Known gap — MCP.** A team's `object_permission.mcp_servers: []` does NOT deny; the
`no-mcp-servers` sentinel is honoured at KEY level only (LiteLLM 1.99.1
`MCPRequestHandler._get_allowed_mcp_servers_for_key`), never on the team path. So a
personal team's deny-all base holds for models (`no-default-models`) and agents (null
UUID) but not for MCP servers, which fall through to proxy-wide visibility governed by
each server's legacy `mcp_access_groups` tag.

---

## Repository-Specific Patterns

**Shared team — all users go into the same team**
Team id (and display alias) = `LITELLM_DEFAULT_TEAM` (default `"default"`), exposed as `settings.team_id`. There is one team per deployment, not one per user. Decoupled from `OAUTH_CLIENT_ID` (was `"team-{OAUTH_CLIENT_ID}"` before v0.5.20) so the team can be renamed without touching the OIDC client. Changing it points the service at a different team — existing keys/budgets stay on the old team (migrate via kubectl, not in code).
**WHERE**: `src/api/app/config.py` — `team_id` property; `litellm_client.py` — `ensure_team_and_user()` (`team_alias`).

**LiteLLM User model — one User per login email**
`ensure_litellm_user(email, settings, name, team_id)` is called on every login before key generation. `user_id = email` (deterministic, debuggable). Keys are scoped to `user_id` via the `user_id` field on `/key/generate`. The user is created idempotently — `400`/`409` "already exists" is treated as success (mirrors team creation).
**WHERE**: `src/api/app/litellm_client.py` — `ensure_litellm_user()`

**Budget reporting = the ENFORCED per-member cap (RQ-1)**
`/api/session/me` and `/api/session/stats` report the budget that actually
*enforces* for team-scoped keys: the per-member-in-team cap `max_budget_in_team`
plus the member's spend, NOT the user-level `max_budget` (which only reports and
does not enforce). The cap is read back from `GET /team/info` (member matched by
`user_id`, budget under `litellm_budget_table`) — it surfaces even for keyless
eager-created users, and `/key/list` does NOT carry it on v1.87.1. Both routes
fall back to the user-level figures (and `source="user"`/`"unknown"`) only when
no membership budget is readable, and the read degrades independently (never a
502). The budget block shape is unchanged: `{current, max_budget, budget_duration,
source}` with `source="team_member"` on the enforced path.
**WHERE**: `litellm_client.py::get_team_member_budget`, `session.py::_budget_block`
(consumed by `session_me` + `session_stats`).

**OIDC provider is provider-agnostic**
All env vars use `OAUTH_` prefix (not `DEX_`). Works with Dex, Keycloak, or any OIDC-compliant provider. Only `OAUTH_ISSUER_URL`, `OAUTH_CLIENT_ID`, `OAUTH_CLIENT_SECRET` change per provider.

**`settings` travels via `request.app.state`**
Route handlers access settings via `request.app.state.settings` — never call `get_settings()` inside a route.

**Tests always use `create_app(settings=make_test_settings())`**
Never rely on env vars in tests. All test files have a local `make_test_settings()` factory.

---

## Environment Variables

| Variable | Source | Description |
|----------|--------|-------------|
| `APP_BASE_URL` | deployment env | Public URL, e.g. `https://platform.ackstorm.ai` |
| `OAUTH_ISSUER_URL` | deployment env | OIDC issuer, e.g. `https://dex.ackstorm.ai/dex` |
| `OAUTH_CLIENT_ID` | deployment env | OIDC client ID, e.g. `platform` |
| `OAUTH_SCOPES` | deployment env (opt) | Default `openid email profile`. Scopes for BOTH the console login and the AS leg; must include `openid`. Add `groups` to surface Workspace groups (Dex Google connector needs domain-wide delegation, else login FAILS). Helm value: `config.oauthScopes` |
| `LITELLM_URL` | deployment env | LiteLLM base URL |
| `LITELLM_DEFAULT_TEAM` | deployment env (opt) | Default `default`. Shared team id + display alias (one team per deployment). Decoupled from `OAUTH_CLIENT_ID`. Helm value: `config.litellmDefaultTeam` |
| `SESSION_SECRET_KEY` | k8s secret | Cookie signing key — shared across all replicas |
| `OAUTH_CLIENT_SECRET` | k8s secret | OIDC client secret (`${GENAI_OAUTH_MCP_SECRET}` in Dex) |
| `LITELLM_MASTER_KEY` | k8s secret | LiteLLM admin key |
| `OPENWORK_ENABLED` | deployment env (opt) | Default `false`. Serves the OpenWork Den at `/openwork`; requires `AS_REDIS_URL`. Branding/policy knobs: `OPENWORK_*` in `config.py`; chart block `openwork:` |

---

## External References

- **Authlib (OIDC client)**: use Context7 or WebSearch — API changes frequently between minor versions
- **LiteLLM Admin API** (`/team/new`, `/key/generate`): use WebSearch for latest endpoint signatures
- **FastAPI / Starlette**: `TemplateResponse` signature changed in Starlette 0.36 — verify with Context7
