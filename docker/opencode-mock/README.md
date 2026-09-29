# opencode mock backend

Standalone, dependency-free mock of an `ackstorm.opencode-config/1` backend:
fake OAuth AS (RFC 9728/8414 discovery, DCR, PKCE browser flow, RFC 8628
device flow), `/clients/opencode/config`, and an OpenAI-compatible
`/v1/chat/completions` that echoes back whatever you send it. Built to
validate the `opencode-oidc-provider` plugin (both the v1 and v2 exports) and
OpenWork end to end without a real ackstorm deployment.

Not a security reference — PKCE/state aren't verified, tokens are opaque
strings, nothing persists across restarts.

## Run it

```bash
docker compose -f docker-compose.opencode-mock.yml up --build
```

Listens on `:8000`. Endpoints: `.well-known/oauth-protected-resource`,
`.well-known/oauth-authorization-server`, `/register`, `/authorize`,
`/device_authorization`, `/token`, `/clients/opencode/config`,
`/v1/chat/completions`, and `/stats` (debug counters: `refresh_calls`,
`device_calls`, `auth_code_calls`, `chat_calls`).

Tokens issued at login are deliberately short-lived (`SHORT_TOKEN_SECONDS`,
default 90s) so the very next credential resolution exercises the plugin's
refresh path; a refresh issues a long-lived one (`LONG_TOKEN_SECONDS`,
default 3600s). Watch `POST /stats` before/after a model call to confirm
`refresh_calls` increments.

## Wire the plugin at it

Same as a real deployment: the mock serves `/.well-known/opencode`, so one URL
installs the plugin (opencode v1 and v2; v2 commands take `--standalone`):

```bash
opencode auth login http://127.0.0.1:8000
opencode auth login -p acktest      # v2: opencode auth login acktest --method sso-device
opencode models                      # should list acktest/echo-model
opencode run --model acktest/echo-model "hello"   # should echo it back
```

If running headless (no browser), `opencode` needs an `xdg-open` on `$PATH`
or the CLI crashes trying to auto-open the login URL — a stub that just
prints the URL is enough:

```bash
mkdir -p /tmp/fakebin && printf '#!/bin/sh\necho "open: $1"\n' > /tmp/fakebin/xdg-open
chmod +x /tmp/fakebin/xdg-open
PATH=/tmp/fakebin:$PATH opencode auth login
```

The device-code method avoids needing a real browser at all — pick it in the
picker and open the printed `verification_uri_complete` yourself if you
want, or just let the poll succeed (this mock auto-approves after one
`authorization_pending`).

## Troubleshooting

- **`UnexpectedStatus: 500` on `opencode auth login`, docker logs show nothing
  reached the container**: check `opencode`'s own log
  (`<log_dir from 'opencode debug paths'>/*.log`), not docker's — the plugin's
  fetch is failing before it ever reaches the network, so docker never sees a
  request. Two known causes, both look identical from the CLI:
  - `api`/`platform` in `opencode.json` don't match where the container
    actually listens (wrong port, stray path suffix like `/v1`, or a leftover
    value from an earlier provider name). They should both be exactly
    `http://127.0.0.1:8000`, no path.
  - A stale `opencode serve --service` background daemon still holds the
    managed-service port from an earlier run — `pkill -f 'opencode serve
    --service'` and retry, or pass `--standalone` to skip that daemon
    entirely (`opencode auth login <provider> --method <id> --standalone`).

## Testing OpenWork

OpenWork's engine v1 loads the same global `opencode.json`, so once the CLI
picks up `acktest` as above, restart OpenWork and check whether it shows up
as a model provider too — that's the actual open question from this round of
testing (it did **not** show up for a v1-shaped plugin under OpenWork's v2
engine; unverified against the v2 plugin export at time of writing).

This mock does **not** implement OpenWork's Den (`/openwork`, `/api/den/*`)
— it only covers the opencode plugin's own auth/config/model path, not
OpenWork's organization join/branding flow. Nothing here requires joining an
org; the plugin + global config is enough on its own.

## Known gaps

- MCP: the mock registers one `mcp-mock` entry in `/clients/opencode/config`
  so clients see it end to end, but doesn't implement the MCP protocol — connecting
  to it will fail. Good enough to confirm the entry is delivered and disabled by
  default; not for testing an actual MCP round-trip.
- Skills: one static skill is served and should materialize as a real
  OpenCode skill; content isn't meaningful beyond confirming delivery.
