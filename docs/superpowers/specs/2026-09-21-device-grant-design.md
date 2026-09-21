# RFC 8628 device grant on the OAuth front door — design

Status: approved 2026-09-21 (port of ACH's 2026-09-20 design, option A; scope = AS +
OpenCode plugin + ackstorm-token).

## 1. Problem

The authorization server (`src/api/app/oauth_as/`) has one way in: the authorization-code
flow with a loopback redirect. On a remote or headless host (SSH box, container, CI runner
with a human) the browser cannot reach `127.0.0.1:<port>` of the machine that started the
login, so opencode, Claude Code (`ackstorm-token`) and Codex cannot sign in there.
TODO.md has carried "Claude Code loopback: when the browser is on another machine the
redirect fails" since v0.8.1. ACH solved it with the standard headless mechanism.

## 2. Decision

Add the **RFC 8628 Device Authorization Grant** to the AS and a second login method to
both clients. The loopback flow stays the default (`methods[0]` in the plugin, the default
of `ackstorm-token login`); the device grant serves the "another browser" case only.

Sub-decisions:

1. Verification page: the input is prefilled from `verification_uri_complete`; the user
   presses **Confirm** after checking it matches the terminal (RFC 8628 §5.4 — a
   forwarded link never approves on its own).
2. A device login issues the audience scope only (`alitellm`). No MCP scope chain: the
   consent chain needs the client's own browser and a redirect back to it, which a device
   login does not have. `scope` on `device_authorization` is ignored.
3. No `slow_down`: both clients are ours and honour `interval`.
4. No rate limiting on the page: 8 symbols from a 20-symbol alphabet (≈34.6 bits) inside a
   10-minute window, same trade ACH made.
5. Browser binding of the Dex leg = Authlib's session state, exactly as `/oauth/authorize`
   (the pending id is the Dex `state`; the callback fails without the session that started
   it — see `test_a_callback_from_a_browser_that_did_not_start_the_request_is_refused`).

## 3. Server — `src/api/app/oauth_as/routes.py`

### 3.1 `POST /oauth/device_authorization`

Form: `client_id` (a DCR client). Unknown → `400 invalid_client`. Response (RFC 8628 §3.2),
`Cache-Control: no-store`:

```json
{
  "device_code": "<token_urlsafe(32)>",
  "user_code": "BCDF-GHJK",
  "verification_uri": "<issuer>/oauth/device",
  "verification_uri_complete": "<issuer>/oauth/device?user_code=BCDF-GHJK",
  "expires_in": 600,
  "interval": 5
}
```

`user_code`: 8 symbols from `BCDFGHJKLMNPQRSTVWXZ` rendered `XXXX-XXXX`; compared
upper-cased with dashes and spaces removed.

Store (both TTL 600 s): `device:<device_code>` = `{client_id, user_code, status: "pending"}`;
`device_user:<user_code>` = `{device_code}`.

### 3.2 `GET|POST /oauth/device` — verification page

`GET` renders `templates/device.html` (dark card, same family as `error.html`): one text
input prefilled from `?user_code=`, "Confirm this is the code shown in your terminal", a
**Confirm** button, an optional problem line. `POST` (form `user_code`): unknown or expired
→ the same page with "code not found or expired — check your terminal" (`400`); known →
`pending` record `{device_code, scopes: [audience]}` (no `client_id`/`redirect_uri`/
`code_challenge`) under a fresh pending id, then `oauth.oidc.authorize_redirect(request,
<issuer>/oauth/as-callback, state=pending_id, scope=DEX_SCOPE)` — the same Dex leg as
`/oauth/authorize`.

### 3.3 `GET /oauth/as-callback` — one Dex leg, two tails

After the existing Dex exchange, refresh-token guard, `dexrt` put and provisioning:

- pending without `device_code` → today's path (`_finish` or the consent chain).
- pending with `device_code` → `_device_finish(pending, "approved", sub)`: the device
  record (if still `pending`) becomes `{…, status: "approved", sub}` with the remaining
  TTL (re-put with TTL 600 is acceptable — the client stops polling at `expires_in`),
  `device_user:<user_code>` is deleted, and the page says "Signed in — return to your
  terminal, you can close this tab." A device record that is gone or not pending → `400`
  "this device code has expired — start again from your terminal".
- Dex failure (`authorize_access_token` raises) with a device pending → the record becomes
  `denied` (index deleted) before the existing 400 page is returned, so the client stops
  polling with `access_denied` instead of waiting out the TTL.

### 3.4 `POST /oauth/token` — new grant

`grant_type=urn:ietf:params:oauth:grant-type:device_code`, `device_code`, `client_id`:

| record | reply |
|---|---|
| absent | `400 expired_token` |
| `client_id` mismatch | `400 invalid_grant` |
| `pending` | `400 authorization_pending` |
| `denied` | `400 access_denied` (record popped) |
| `approved` | record **popped** (single redemption), then `_issue(sub, client_id, audience)` — same JWT + refresh as every other grant |

### 3.5 Metadata and DCR

`authorization_server_metadata()` adds `"device_authorization_endpoint":
"<issuer>/oauth/device_authorization"` and the device grant type to
`grant_types_supported`. `/oauth/register` records `grant_types` with the device grant
appended (informational; the AS does not gate grants per client).

## 4. Clients

### 4.1 `clients/opencode/index.mjs` (→ 0.2.0)

Second method, verbatim from ACH `6fa97f8`: `label: "SSO (device code — sign in from
another browser)"`; `authorize()` posts `device_authorization`, returns
`{url: verification_uri_complete, method: "auto", instructions: "Open the URL in any
browser (this or another machine), confirm the code XXXX-XXXX and sign in…", callback()}`
where `callback()` runs `pollDevice()` — poll `/token` every `interval` s (a `slow_down`
adds 5 s) until success, or `expired_token`/`access_denied`/deadline → `{type: "failed"}`.
Throws early when the AS metadata has no `device_authorization_endpoint`. Loopback stays
`methods[0]`.

### 4.2 `clients/ackstorm-token`

`ackstorm-token login --no-browser` (also honoured by the implicit login when there is
nothing to refresh, via the same flag): `device_login(state, meta)` posts
`device_authorization`, prints to stderr

```
Open https://platform.ackstorm.ai/oauth/device in any browser and enter the code:

    BCDF-GHJK

Waiting for you to sign in… (expires in 10 min)
```

then polls `/token` every `interval` s, reading the OAuth error from the 400 body
(`authorization_pending` → keep going, `access_denied`/`expired_token`/deadline → exit
with the reason). Stores the same `access_token`/`refresh_token`/`expires_at` as the
loopback path. Without `--no-browser` behaviour is unchanged.

## 5. Tests

- `tests/test_oauth_as_routes.py`: metadata advertises the endpoint + grant;
  `device_authorization` happy path (shape, store records, TTLs) and unknown client;
  page `GET` prefill; `POST` bad code → 400 page; `POST` good code → 302 to Dex with a
  pending carrying `device_code`; callback approves (record `approved` + `sub`, index gone,
  HTML says return to terminal) and denies on a Dex error; token grant: pending →
  `authorization_pending`, approved → JWT + refresh, second redemption → `expired_token`,
  wrong client → `invalid_grant`, denied → `access_denied`; a device-issued token carries
  scope `alitellm` only.
- `test/opencode-auth.test.mjs`: the device method posts `device_authorization`, returns
  the verification URL, and `callback()` polls through one `authorization_pending` to a
  token.
- `ackstorm-token`: stdlib only, no test harness today; the device path is exercised by
  hand (`ACKSTORM_API=... ackstorm-token login --no-browser`) — noted in the plan's final
  gate, not automated.

## 6. Docs

README "Clients" (opencode second method, `ackstorm-token login --no-browser`), CHANGELOG,
TODO.md (close the loopback item). `docs/dex-integration.md` unchanged: same redirect URI.
