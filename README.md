# alitellm-auth

FastAPI service that authenticates users via an OIDC provider (Dex / Keycloak) and provisions a LiteLLM virtual key (`sk-...`) per user. It creates a first-class LiteLLM User on every login (`user_id = email`), scopes the key to that user, and exposes admin CRUD endpoints for user management. Companion to alitellm-operator, which owns model/team discovery but not Users or VirtualKeys.

## API Endpoints

### User Endpoints

- `GET /api/oauth/login` — Start OIDC flow; creates a new LiteLLM key on return.
- `GET /api/oauth/reveal` — OIDC login; shows the most recently created key.
- `GET /api/oauth/tokens` — OIDC login; returns JSON list of all user keys.
- `DELETE /api/oauth/tokens/{id}` — Delete a specific key. Header: `x-alitellm-auth-api-key: sk-...`
- `GET /api/oauth/whoami` — Validate a key and return user identity + LiteLLM user metadata. Header: `x-alitellm-auth-api-key: sk-...`

The `whoami` response includes the key's metadata (`user_id`, `email`, `team_id`, budgets, limits) plus a nested `litellm_user` enrichment block. A valid key whose metadata lacks an `email` is returned unenriched.

```bash
curl -s https://<your-app>/api/oauth/whoami \
  -H "x-alitellm-auth-api-key: sk-XXXX" | jq .
# "Bearer sk-XXXX" is also accepted.
```

Status codes:

- `GET /api/oauth/whoami` — `200` (valid key; unenriched `200` when the key has no email), `401` (missing header / invalid key), `404` (valid key, email present, but no matching LiteLLM user), `502` (LiteLLM unreachable / 5xx).
- `DELETE /api/oauth/tokens/{id}` — `200` (deleted), `401` (missing/invalid key), `403` (key has no associated user), `404` (token not owned by the caller), `502` (LiteLLM failure).

### Admin Endpoints (master-key only)

- `GET /api/users` — List all LiteLLM users. Header: `x-alitellm-auth-api-key: <master-key>`
- `GET /api/users/{email}` — Get a single user (with their keys). Returns `404` when absent.
- `DELETE /api/users/{email}` — Delete a LiteLLM user and their keys. Returns `{"status":"deleted","user_id":"..."}`.

```bash
curl -s https://<your-app>/api/users \
  -H "x-alitellm-auth-api-key: <master-key>" | jq .
```

### Session Endpoints (browser, OIDC session cookie)

Same-origin JSON API for the SPA dashboard. Authentication is the OIDC **session cookie** set
at login — the browser never pastes a master key or `sk-`. All routes require a valid session
(HTML requests redirect to OIDC login; JSON requests return `401`). State-changing routes also
enforce a same-origin `Origin`/`Referer` guard (`403` cross-origin).

- `GET /api/session/me` — current user identity + account limits + spend.
- `GET /api/session/keys` — the user's keys with metadata (no `sk-` or hash leaked to the browser).
- `POST /api/session/keys` — mint a key (optional `{alias, duration}`); returns the `sk-` once.
- `DELETE /api/session/keys/{id}` — delete an owned key (`200`); `403` for any id not in the user's list.
- `GET /api/session/usage?window=30d` — daily usage breakdown.
- `GET /ui` — dashboard placeholder for a valid session; `302` to OIDC otherwise.

## OIDC Integration

See [docs/dex-integration.md](docs/dex-integration.md) for Dex and Keycloak configuration, env-var mapping, and troubleshooting.

## Development

```bash
cd src/api
uv venv .venv && source .venv/bin/activate
uv pip install -e ".[dev]"
pytest
```

Run locally (requires a `.env` with the variables below):

```bash
cd src/api && uvicorn app.main:app --reload --port 8080
```

### Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SESSION_SECRET_KEY` | yes | Cookie signing key — must be identical across all replicas |
| `OAUTH_ISSUER_URL` | yes | OIDC issuer, e.g. `https://dex.example.com/dex` |
| `OAUTH_CLIENT_ID` | yes | OIDC client ID |
| `OAUTH_CLIENT_SECRET` | yes | OIDC client secret |
| `LITELLM_URL` | yes | Internal LiteLLM base URL (server-side admin calls) |
| `LITELLM_MASTER_KEY` | yes | LiteLLM admin key; also the credential for admin endpoints |
| `APP_BASE_URL` | no | Public URL of this service (default `http://localhost:8080`) |
| `API_PUBLIC_URL` | no | Public LiteLLM API URL shown to users (default `https://api.ackstorm.ai` — override per deployment) |
| `SESSION_HTTPS_ONLY` | no | Mark the session cookie `Secure` (default `false`). Set `true` in production behind HTTPS. |
| `FACTORY_CONFIG_PATH` | no | Path to a mounted ConfigMap JSON (`{"team": {...}, "user": {...}}`) with default LiteLLM team/user params |

## Deployment

A Helm chart (`deploy/helm/alitellm-auth/`) and a Kustomize base (`deploy/kustomize/base/`) are
provided. See [deploy/README.md](deploy/README.md) for details.

```bash
# Helm
helm install alitellm-auth deploy/helm/alitellm-auth -n test

# Kustomize
kubectl apply -k deploy/kustomize/base -n test
```

Both inject `SESSION_HTTPS_ONLY` (prod default `true`) and mount the factory-config ConfigMap.
`GET /health` is the liveness/readiness probe target.

## Contributing & License

Apache-2.0 (see [LICENSE](LICENSE)). See [CONTRIBUTING.md](CONTRIBUTING.md),
[SECURITY.md](SECURITY.md), and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
