# alitellm-auth

FastAPI service that authenticates users via an OIDC provider (Dex/Keycloak) and provisions a LiteLLM virtual key (`sk-...`) per user, returning a dark-card HTML page with the key.

Companion to alitellm-operator (Go), which owns model/team discovery but not Users or VirtualKeys — Users and VirtualKeys are exclusively managed by this service.

**Stack**: Python 3.12, FastAPI, Authlib (OIDC), httpx (LiteLLM), Jinja2, Starlette SessionMiddleware, uv, Docker/Kubernetes.

---

## Architecture

```
Browser
  │
  ▼
GET /api/oauth/login
  │  authorize_redirect (authlib)
  ▼
OIDC Provider (Dex / Keycloak)
  │  redirects with ?code=
  ▼
GET /api/oauth/callback
  ├─▶ exchange code → id_token (email, name)
  ├─▶ POST /team/new   → LiteLLM  (idempotent, 409 = already exists)
  ├─▶ POST /user/new → LiteLLM  (idempotent, user_id=email)
  ├─▶ POST /key/generate → LiteLLM
  └─▶ render success.html  (or error.html on failure)

GET /api/oauth/reveal
  ├─▶ OIDC Login
  ├─▶ GET /key/list (filtered by email)
  └─▶ render success.html (latest token)

GET /api/oauth/tokens
  ├─▶ OIDC Login
  ├─▶ GET /key/list (filtered by email)
  └─▶ JSON response (all tokens)

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
| `src/api/app/templates/` | `success.html`, `error.html` (dark terminal card) |
| `deploy/helm/`, `deploy/kustomize/` | Helm chart + Kustomize base/overlays (deployment, service, ingress, configmap, secret example) |

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

### `GET /api/oauth/reveal` — Show latest token

OIDC login flow that redirects to the success page showing the most recently created LiteLLM key for the user, without creating a new one.

### `GET /api/oauth/tokens` — List all user tokens

OIDC login flow that returns a JSON list of all LiteLLM keys associated with the user's email.

**Success response (`200`):**
```json
{
  "email": "alice@example.com",
  "tokens": [
    {
      "id": "key-XXXXXXXXXXXXXXXXXXXX",
      "key": "sk-...",
      "created_at": "2026-03-01T10:00:00+00:00",
      "expires": null,
      "models": ["all-team-models"]
    }
  ]
}
```

### `DELETE /api/oauth/tokens/{id}` — Delete a token

Deletes a specific LiteLLM virtual key. Requires authentication via header.

**Header:** `x-alitellm-auth-api-key: sk-...`

**Path parameter:** `id` (the identifier returned by `/tokens` or `/whoami`)

```bash
curl -X DELETE https://platform.ackstorm.ai/api/oauth/tokens/key-XXXXXXXXXXXXXXXXXXXX \
  -H "x-alitellm-auth-api-key: sk-YYYYYYYYYYYYYYYYYYYY"
```

### Admin Endpoints — /api/users (master-key only)

All admin endpoints require: Header `x-alitellm-auth-api-key` equal to `LITELLM_MASTER_KEY`.
Authorization uses `hmac.compare_digest` (constant-time, defends against timing attacks).

- `GET /api/users` — list all LiteLLM users (paginated, up to 10 pages of 100).
- `GET /api/users/{email}` — get a single user by email. Returns `404` when absent, `502` on LiteLLM failure.
- `DELETE /api/users/{email}` — delete a user (and their keys). Returns `{"status":"deleted","user_id":"..."}`.

**WHERE**: `src/api/app/admin.py`

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

## Repository-Specific Patterns

**Shared team — all users go into the same team**
Team ID = `"team-{OAUTH_CLIENT_ID}"` (e.g. `"team-platform"`). There is one team per deployment, not one per user. The team ID is derived from `settings.oauth_client_id` in `generate_litellm_key()`. Do NOT rename `OAUTH_CLIENT_ID` — it drives the live LiteLLM team name.
**WHERE**: `src/api/app/litellm_client.py` — `generate_litellm_key()`

**LiteLLM User model — one User per login email**
`ensure_litellm_user(email, settings, name, team_id)` is called on every login before key generation. `user_id = email` (deterministic, debuggable). Keys are scoped to `user_id` via the `user_id` field on `/key/generate`. The user is created idempotently — `400`/`409` "already exists" is treated as success (mirrors team creation).
**WHERE**: `src/api/app/litellm_client.py` — `ensure_litellm_user()`

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
| `LITELLM_URL` | deployment env | LiteLLM base URL |
| `SESSION_SECRET_KEY` | k8s secret | Cookie signing key — shared across all replicas |
| `OAUTH_CLIENT_SECRET` | k8s secret | OIDC client secret (`${GENAI_OAUTH_MCP_SECRET}` in Dex) |
| `LITELLM_MASTER_KEY` | k8s secret | LiteLLM admin key |

---

## External References

- **Authlib (OIDC client)**: use Context7 or WebSearch — API changes frequently between minor versions
- **LiteLLM Admin API** (`/team/new`, `/key/generate`): use WebSearch for latest endpoint signatures
- **FastAPI / Starlette**: `TemplateResponse` signature changed in Starlette 0.36 — verify with Context7
