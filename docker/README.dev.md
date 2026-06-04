# Local dev stack — the whole app, live

Run the **entire** alitellm-auth app locally with a mock OIDC user and realistic
LiteLLM data. One command, one URL, no real OIDC provider and no real LiteLLM proxy.

```bash
docker-compose -f docker-compose.dev.yml up --build
```

Then open:

```
http://localhost:5173/ui/
```

Click sign-in and you are logged in **non-interactively** as the mock user — the
authenticated React console renders end-to-end against canned-but-realistic data.

> This is **DEV TOOLING ONLY**. It is intentionally permissive (mock OIDC accepts
> any client secret; the mock LiteLLM trusts every request). Never expose it.

---

## What's in the stack

| Service        | Image / build                              | Port (host) | Role |
|----------------|--------------------------------------------|-------------|------|
| `ui`           | `node:22-slim` + `vite dev` (HMR)          | `5173`*     | Serves `src/ui-next` at `/ui/`; proxies `/api`→auth |
| `auth`         | `docker/auth-dev.Dockerfile` (the REAL app)| `8080`,`5173`| FastAPI `uvicorn app.main:app --reload` |
| `mock-oidc`    | `ghcr.io/navikt/mock-oauth2-server`        | `8081`      | Non-interactive OIDC issuer (`interactiveLogin:false`) |
| `mock-litellm` | `docker/mock-litellm` (tiny FastAPI stub)  | `4000`      | Serves the repo's LiteLLM response fixtures |

\* The `ui` service shares the `auth` container's network namespace
(`network_mode: service:auth`), so vite's hardcoded proxy target `localhost:8080`
(in `src/ui-next/vite.config.ts`) reaches the auth uvicorn **with no frontend
edit**. Because of that, port `5173` is published on the `auth` service, not `ui`.

The backend and frontend source under `src/` are **never modified** — `auth`
bind-mounts `src/api/app` (so `uvicorn --reload` hot-reloads Python edits) and `ui`
bind-mounts `src/ui-next` (so vite HMR hot-reloads React edits).

---

## The mock user

Configured in `docker/mock-oidc/config.json` (claims issued by the OIDC token
endpoint) and aligned with `src/api/tests/fixtures/user_info.json`:

| Claim   | Value                |
|---------|----------------------|
| `sub`   | `alice@example.com`  |
| `email` | `alice@example.com`  |
| `name`  | `Mock User`          |

The same email drives `docker/mock-litellm/fixtures/keys.json` (key ownership) so
the dashboard, key list, and usage stats all render populated for this user. The
shared team is `team-platform` (derived from `OAUTH_CLIENT_ID=platform`).

---

## OIDC dual-addressability (why `oidc.localtest.me`)

authlib fetches the OIDC discovery doc **server-side** (from the `auth` container)
and also redirects the **browser** to the same provider. The mock OIDC server builds
its discovery URLs and the token `iss` from the request `Host` header, so the issuer
URL must resolve to the **same** `host:port` from both sides or `iss` validation fails.

- Issuer is `http://oidc.localtest.me:8081/default`.
- `*.localtest.me` resolves to loopback (`127.0.0.1` / `::1`) via **public DNS** — so
  the host browser/curl reach the published `mock-oidc` at `:8081`.
- The `auth` container can't reach the host loopback as itself, so the compose file
  maps `oidc.localtest.me` → the host gateway:
  ```yaml
  extra_hosts:
    - "oidc.localtest.me:host-gateway"
  ```
  Now both the browser and the container resolve `oidc.localtest.me:8081` to the same
  mock-oidc, and discovery + token `iss` stay consistent.

No `/etc/hosts` edit is required when `localtest.me` resolves (it does on most
networks via public DNS).

### Fallback if `localtest.me` does not resolve

If `getent hosts oidc.localtest.me` returns nothing, add one line to `/etc/hosts`:

```
127.0.0.1 oidc.localtest.me
```

(The container still uses the `host-gateway` mapping from the compose file, so only
the host side needs the entry.)

---

## Verify it works (scripted, no browser)

The mock OIDC is non-interactive, so the full login flow runs headless with curl:

```bash
# 1. Log in (drives OIDC discovery → authorize → callback → /ui) into a cookie jar
curl -sL -c /tmp/jar -b /tmp/jar 'http://localhost:5173/api/oauth/login?action=ui' -o /dev/null

# 2. Identity, keys, stats — all 200, all populated
curl -s -b /tmp/jar http://localhost:5173/api/session/me
curl -s -b /tmp/jar http://localhost:5173/api/session/keys
curl -s -b /tmp/jar 'http://localhost:5173/api/session/stats?start_date=2026-05-05&end_date=2026-06-04'
```

`/api/session/me` returns `alice@example.com` / `Mock User` with budget `15.935/50.0`;
`/keys` returns 4 synthetic keys; `/stats` returns populated totals + per-model + per-key
breakdowns with non-trivial period-over-period deltas.

---

## Useful commands

```bash
# Logs (all or one service)
docker-compose -f docker-compose.dev.yml logs -f
docker-compose -f docker-compose.dev.yml logs -f auth

# Rebuild just the mock (its app.py is COPY'd, not bind-mounted)
docker-compose -f docker-compose.dev.yml up -d --build mock-litellm

# Tear down
docker-compose -f docker-compose.dev.yml down
```

## Files

```
docker-compose.dev.yml           # the 4-service stack
docker/auth-dev.Dockerfile       # dev image for the real FastAPI app
docker/mock-oidc/config.json     # non-interactive OIDC config + mock user claims
docker/mock-litellm/             # tiny FastAPI LiteLLM stub
  ├── app.py                     # endpoints the backend calls (litellm_client.py)
  ├── Dockerfile
  ├── requirements.txt
  └── fixtures/keys.json         # synthetic virtual keys for the mock user
```
