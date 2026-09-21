# alitellm-auth

FastAPI service that authenticates users via an OIDC provider (Dex / Keycloak) and lets each user create LiteLLM virtual keys (`sk-...`) from a web console. It creates a first-class LiteLLM User on every login (`user_id = email`), scopes keys to that user, and exposes admin CRUD endpoints for user management. Companion to alitellm-operator, which owns model/team discovery but not Users or VirtualKeys.

## API Endpoints

### User Endpoints

- `GET /api/oauth/login` — Start the OIDC sign-in flow. On return it eager-creates the LiteLLM user (idempotent) and redirects to the `/ui` console. It does **not** mint a key.
- `GET /api/oauth/logout` — Clear the local session and return to the `/ui` sign-in landing.
- `GET /api/oauth/whoami` — Validate a key and return user identity + LiteLLM user metadata. Header: `x-alitellm-auth-api-key: sk-...`

Keys are created, listed, and deleted from inside the console via the session API (`/api/session/keys`, below). There is no OIDC-redirect endpoint that hands back an `sk-`.

The `whoami` response includes the key's metadata (`user_id`, `email`, `team_id`, budgets, limits) plus a nested `litellm_user` enrichment block. A valid key whose metadata lacks an `email` is returned unenriched.

```bash
curl -s https://<your-app>/api/oauth/whoami \
  -H "x-alitellm-auth-api-key: sk-XXXX" | jq .
# "Bearer sk-XXXX" is also accepted.
```

Status codes:

- `GET /api/oauth/whoami` — `200` (valid key; unenriched `200` when the key has no email), `401` (missing header / invalid key), `404` (valid key, email present, but no matching LiteLLM user), `502` (LiteLLM unreachable / 5xx).

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

## Clients

With the OAuth front door on (`authServer.enabled` + `authz.enabled` + `istio.enabled` in
the chart), `api.<domain>` accepts a front-door JWT in `Authorization` and maps it to the
caller's LiteLLM key. Coding agents get that JWT three ways.

### OpenCode

The plugin is served by this API as an npm tarball, so install it from the platform:

```bash
opencode plugin https://platform.ackstorm.ai/public/opencode-auth -g
opencode auth login -p ackstorm      # browser SSO; tokens land in opencode's auth store
```

Nothing to configure: the plugin takes the provider's API URL from opencode, finds the
authorization server through `/.well-known/oauth-protected-resource` (RFC 9728) and its
endpoints through RFC 8414. The tarball is fetched once; a new release is picked up by
re-running the install command with `-f`. Source: [clients/opencode](clients/opencode).

On a remote or headless host pick the second method, **SSO (device code)**: opencode
prints a `XXXX-XXXX` code and a URL; open the URL in any browser, confirm the code and
sign in — the session completes on its own. A new plugin release is picked up with
`opencode plugin <url> -g -f`.

An exported `LITELLM_API_KEY` still works (the served `api.json` lists it), but an OAuth
credential wins when both are present.

### Claude Code and Codex

Both take "a command that prints a credential". [clients/ackstorm-token](clients/ackstorm-token)
is that command (stdlib Python, DCR + PKCE, refresh token in `~/.config/ackstorm-ai/token.json`).
It finds the authorization server from the API host (`ACKSTORM_API`, default
`https://api.ackstorm.ai`) the same way the OpenCode plugin does:

```json
// ~/.claude/settings.json
{ "apiKeyHelper": "/path/to/ackstorm-token" }
```

```toml
# ~/.codex/config.toml
model_provider = "ackstorm"
[model_providers.ackstorm]
name = "ACKstorm"
base_url = "https://api.ackstorm.ai/v1"
wire_api = "responses"
[model_providers.ackstorm.auth]
command = "/path/to/ackstorm-token"
refresh_interval_ms = 300000
```

With `ANTHROPIC_BASE_URL=https://api.ackstorm.ai` for Claude Code. Codex ignores
`OPENAI_BASE_URL`; the custom provider is required. Both cache the printed token
(Claude Code: `CLAUDE_CODE_API_KEY_HELPER_TTL_MS`; Codex: `refresh_interval_ms`), so
the helper refreshes 10 minutes before expiry — keep the cache interval below that.

On a host with no usable browser run `ackstorm-token login --no-browser` once: it prints
a `XXXX-XXXX` code and a URL; open the URL in any browser, confirm the code and sign in.
Later runs refresh silently as usual.

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

A Helm chart (`deploy/helm/alitellm-auth/`) is provided. See
[deploy/README.md](deploy/README.md) for details.

```bash
helm install alitellm-auth deploy/helm/alitellm-auth -n test
```

It injects `SESSION_HTTPS_ONLY` (prod default `true`) and mounts the factory-config ConfigMap.
`GET /health` is the liveness/readiness probe target.

## Contributing & License

Apache-2.0 (see [LICENSE](LICENSE)). See [CONTRIBUTING.md](CONTRIBUTING.md),
[SECURITY.md](SECURITY.md), and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
