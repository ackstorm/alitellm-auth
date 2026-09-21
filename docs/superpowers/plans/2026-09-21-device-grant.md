# RFC 8628 Device Grant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user sign in to the OAuth front door from a host with no usable browser (SSH, container): the AS gains the RFC 8628 device grant, the OpenCode plugin gains a second login method, `ackstorm-token` gains `login --no-browser`.

**Architecture:** The AS (`src/api/app/oauth_as/routes.py`) adds `POST /oauth/device_authorization` (user code + device code, 10 min), a `GET|POST /oauth/device` verification page that parks a `pending` record and sends the browser through the SAME Dex leg as `/oauth/authorize`, a device tail in `as-callback` that flips the device record to `approved`/`denied`, and a `urn:ietf:params:oauth:grant-type:device_code` branch in `/oauth/token` that the client polls. Clients: the plugin's method is a verbatim port of ACH `6fa97f8`; `ackstorm-token` gets a `device_login()` next to `login()`. Spec: `docs/superpowers/specs/2026-09-21-device-grant-design.md`.

**Tech Stack:** Python 3.12 + FastAPI + Authlib + Jinja2 (tests: pytest, `unittest.mock`, in-memory store); Node ≥ 20 ESM plugin (tests: `node --test`); stdlib Python 3 CLI.

## Global Constraints

- All output in English: code, comments, docs, commits.
- Python gates from `src/api/`: `.venv/bin/pytest tests/ -q` (currently 391 passed) and ruff **0.8.4**: `uvx ruff@0.8.4 check app tests && uvx ruff@0.8.4 format --check app tests` (`uv run ruff` is a different version — never use it as the gate).
- Node gate from the repo root: `node --test test/opencode-auth.test.mjs` (currently 2 passed; `node` is on the host).
- Commit on a branch off `main` (`feat/device-grant`). Conventional commit subject < 72 chars; trailer `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>` literally. Never `git add` `docs/superpowers/` (except the two files this plan names), `scripts/mcp_auth_check.py` or `.superpowers/`. No `make release-*`, no tags, no push.
- Store values are dicts. Kinds and shapes (exact): `device:<device_code>` = `{"client_id", "user_code", "status": "pending"|"approved"|"denied", "sub"?}`; `device_user:<user_code>` = `{"device_code"}`; a device `pending` = `{"device_code", "scopes": [<audience>]}`.
- Constants (exact): `DEVICE_TTL = 600`, `DEVICE_INTERVAL = 5`, `DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"`, `USER_CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ"`, user code shape `XXXX-XXXX`.
- A device login issues scope = `settings.as_audience` only. No MCP scope chain.
- Never log a token, a device code or a user code together with an email.

---

### Task 1: AS — device authorization, verification page, callback tail, token grant, metadata

**Files:**
- Modify: `src/api/app/oauth_as/routes.py` (constants after `DEXRT`; `authorization_server_metadata`; `register`; `as_callback`; `token`; new helpers + routes)
- Create: `src/api/app/templates/device.html`
- Modify: `src/api/tests/test_oauth_as_routes.py` (two existing assertions + new tests)
- Modify: `CHANGELOG.md`, `TODO.md`

**Interfaces:**
- Consumes: `_store` (`get/put/pop(kind, key)`), `_settings.as_issuer`, `_settings.as_audience`, `_settings.app_base_url`, `oauth.oidc.authorize_redirect(request, callback, state=..., scope=DEX_SCOPE)`, `_issue(sub, client_id, scope)`, `_error(status, code, description="")`, `_html_error(status, message)`, `PENDING_TTL`, `DEX_SCOPE`.
- Produces (module-level in `routes.py`): `DEVICE_TTL`, `DEVICE_INTERVAL`, `DEVICE_GRANT`, `USER_CODE_ALPHABET`, `_new_user_code() -> str`, `_normalize_user_code(raw: str) -> str`, `_device_settle(device_code, status, sub="") -> dict | None`, `_device_finish(request, pending) -> HTMLResponse`, routes `POST /oauth/device_authorization`, `GET /oauth/device`, `POST /oauth/device`. Metadata gains `device_authorization_endpoint`.

- [ ] **Step 1: Write the failing tests**

In `src/api/tests/test_oauth_as_routes.py`:

(a) `test_as_metadata_names_every_endpoint_under_the_issuer` — replace the `grant_types_supported` assertion with:

```python
    assert metadata["grant_types_supported"] == [
        "authorization_code",
        "refresh_token",
        "urn:ietf:params:oauth:grant-type:device_code",
    ]
    assert metadata["device_authorization_endpoint"] == "https://platform.test/oauth/device_authorization"
```

(b) `test_register_accepts_a_public_client_with_loopback_and_https_redirects` — replace the `grant_types` assertion with:

```python
    assert body["grant_types"] == [
        "authorization_code",
        "refresh_token",
        "urn:ietf:params:oauth:grant-type:device_code",
    ]
```

(c) Append at the end of the module:

```python
# ── RFC 8628 device grant ────────────────────────────────────────────────────

DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"


def _device_start(c: TestClient, client_id: str) -> dict:
    r = c.post("/oauth/device_authorization", data={"client_id": client_id})
    assert r.status_code == 200, r.text
    assert r.headers["cache-control"] == "no-store"
    return r.json()


def _device_token(c: TestClient, client_id: str, device_code: str):
    return c.post(
        "/oauth/token",
        data={"grant_type": DEVICE_GRANT, "device_code": device_code, "client_id": client_id},
    )


def _device_confirm_through_dex(c: TestClient, user_code: str, *, dex_fails: bool = False):
    """POST the code on the page → Dex → as-callback; return the callback response."""
    with patch("app.oauth_as.routes.oauth") as mock_oauth:
        mock_oauth.oidc.authorize_redirect = AsyncMock(
            return_value=RedirectResponse("http://dex.test/auth", status_code=302)
        )
        r = c.post("/oauth/device", data={"user_code": user_code}, follow_redirects=False)
        assert r.status_code == 302, r.text
        kwargs = mock_oauth.oidc.authorize_redirect.call_args.kwargs
        assert kwargs["scope"] == "openid email profile offline_access"
        pending_id = kwargs["state"]
        assert asyncio.run(routes._store.get("pending", pending_id))["scopes"] == ["alitellm"]
        if dex_fails:
            mock_oauth.oidc.authorize_access_token = AsyncMock(side_effect=RuntimeError("access_denied"))
        else:
            mock_oauth.oidc.authorize_access_token = AsyncMock(
                return_value={"userinfo": {"email": "u@x.com"}, "refresh_token": "dex-rt-1"}
            )
        with patch("app.oauth_as.routes.ensure_team_and_user", AsyncMock(return_value="default")):
            return c.get(f"/oauth/as-callback?code=dexcode&state={pending_id}", follow_redirects=False)


def test_device_authorization_issues_a_user_code_and_parks_the_device():
    c = make_client()
    client_id = _register(c)
    da = _device_start(c, client_id)
    assert re.fullmatch(r"[BCDFGHJKLMNPQRSTVWXZ]{4}-[BCDFGHJKLMNPQRSTVWXZ]{4}", da["user_code"])
    assert da["verification_uri"] == "https://platform.test/oauth/device"
    assert da["verification_uri_complete"] == f"https://platform.test/oauth/device?user_code={da['user_code']}"
    assert da["expires_in"] == 600 and da["interval"] == 5
    assert asyncio.run(routes._store.get("device", da["device_code"])) == {
        "client_id": client_id,
        "user_code": da["user_code"],
        "status": "pending",
    }
    assert asyncio.run(routes._store.get("device_user", da["user_code"])) == {"device_code": da["device_code"]}


def test_device_authorization_rejects_an_unknown_client():
    r = make_client().post("/oauth/device_authorization", data={"client_id": "nope"})
    assert r.status_code == 400 and r.json()["error"] == "invalid_client"


def test_device_page_prefills_the_code_and_rejects_an_unknown_one():
    c = make_client()
    r = c.get("/oauth/device?user_code=BCDF-GHJK")
    assert r.status_code == 200 and 'value="BCDF-GHJK"' in r.text and "Confirm" in r.text
    with patch("app.oauth_as.routes.oauth") as mock_oauth:
        r = c.post("/oauth/device", data={"user_code": "BCDF-GHJK"})
        mock_oauth.oidc.authorize_redirect.assert_not_called()
    assert r.status_code == 400 and "not found or expired" in r.text


def test_user_code_normalisation():
    assert routes._normalize_user_code(" bcdf ghjk ") == "BCDF-GHJK"
    assert routes._normalize_user_code("BCDF-GHJK") == "BCDF-GHJK"
    assert routes._normalize_user_code("bcdfghjk") == "BCDF-GHJK"
    assert routes._normalize_user_code("BCDF-GHJ") == ""


def test_device_login_end_to_end_then_single_redemption():
    c = make_client()
    client_id = _register(c)
    da = _device_start(c, client_id)
    # Before approval the client keeps polling.
    r = _device_token(c, client_id, da["device_code"])
    assert r.status_code == 400 and r.json()["error"] == "authorization_pending"
    # The user types the code in any browser (lower-case, spaced) and signs in at Dex.
    r = _device_confirm_through_dex(c, da["user_code"].lower().replace("-", " "))
    assert r.status_code == 200 and "terminal" in r.text
    assert asyncio.run(routes._store.get("device", da["device_code"])) == {
        "client_id": client_id,
        "user_code": da["user_code"],
        "status": "approved",
        "sub": "u@x.com",
    }
    assert asyncio.run(routes._store.get("device_user", da["user_code"])) is None
    assert asyncio.run(routes._store.get("dexrt", "u@x.com")) == {"rt": "dex-rt-1"}
    # The poll now returns the same pair every grant issues; scope is the audience only.
    r = _device_token(c, client_id, da["device_code"])
    assert r.status_code == 200, r.text
    tok = r.json()
    assert tok["scope"] == "alitellm" and tok["refresh_token"]
    claims = _jwt.decode(tok["access_token"], routes._signer.jwks())
    assert claims["sub"] == "u@x.com" and claims["scope"] == "alitellm"
    # Single redemption.
    r = _device_token(c, client_id, da["device_code"])
    assert r.status_code == 400 and r.json()["error"] == "expired_token"


def test_device_token_rejects_another_client_and_an_unknown_code():
    c = make_client()
    client_id, other = _register(c), _register(c)
    da = _device_start(c, client_id)
    r = _device_token(c, other, da["device_code"])
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
    r = _device_token(c, client_id, "nope")
    assert r.status_code == 400 and r.json()["error"] == "expired_token"


def test_device_login_refused_at_dex_is_access_denied_once():
    c = make_client()
    client_id = _register(c)
    da = _device_start(c, client_id)
    r = _device_confirm_through_dex(c, da["user_code"], dex_fails=True)
    assert r.status_code == 400
    assert asyncio.run(routes._store.get("device", da["device_code"]))["status"] == "denied"
    assert asyncio.run(routes._store.get("device_user", da["user_code"])) is None
    r = _device_token(c, client_id, da["device_code"])
    assert r.status_code == 400 and r.json()["error"] == "access_denied"
    r = _device_token(c, client_id, da["device_code"])
    assert r.status_code == 400 and r.json()["error"] == "expired_token"


def test_a_settled_device_code_cannot_be_approved_twice():
    c = make_client()
    client_id = _register(c)
    da = _device_start(c, client_id)
    assert _device_confirm_through_dex(c, da["user_code"]).status_code == 200
    # The index is gone, so the page refuses the code before Dex is involved.
    with patch("app.oauth_as.routes.oauth") as mock_oauth:
        r = c.post("/oauth/device", data={"user_code": da["user_code"]})
        mock_oauth.oidc.authorize_redirect.assert_not_called()
    assert r.status_code == 400 and "not found or expired" in r.text
```
`import re` must be present at the top of the test module (add it if absent; `asyncio`, `patch`, `AsyncMock`, `RedirectResponse`, `_jwt`, `TestClient` already are).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd src/api && .venv/bin/pytest tests/test_oauth_as_routes.py -q -k "device or user_code or metadata or register_accepts"`
Expected: the metadata/register assertions fail on the missing grant type; the device tests fail with 404s / `AttributeError: _normalize_user_code`.

- [ ] **Step 3: Implement — constants, metadata, DCR, helpers, routes**

In `routes.py`, after `DEXRT = ...` add:

```python
# RFC 8628 device grant: the headless login. The host that needs the token shows
# a code, the user signs in from any browser, the host polls /oauth/token.
DEVICE_TTL = 600
DEVICE_INTERVAL = 5
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
USER_CODE_ALPHABET = "BCDFGHJKLMNPQRSTVWXZ"  # 20 symbols, no look-alikes (no vowels, 0/O, 1/I)
_TEMPLATES = Jinja2Templates(directory=str(Path(__file__).resolve().parent.parent / "templates"))
```
with imports `from pathlib import Path` and `from fastapi.templating import Jinja2Templates` added in their sorted places.

`authorization_server_metadata()` — add the endpoint and the grant type:

```python
        "device_authorization_endpoint": f"{issuer}/oauth/device_authorization",
        ...
        "grant_types_supported": ["authorization_code", "refresh_token", DEVICE_GRANT],
```

`register()` — the record's `"grant_types"` becomes `["authorization_code", "refresh_token", DEVICE_GRANT]`.

Helpers (place them right before `_pkce_ok`):

```python
def _new_user_code() -> str:
    raw = "".join(secrets.choice(USER_CODE_ALPHABET) for _ in range(8))
    return f"{raw[:4]}-{raw[4:]}"


def _normalize_user_code(raw: str) -> str:
    """What the user typed → the stored form: "bcdf ghjk" and "BCDF-GHJK" both match."""
    s = raw.strip().upper().replace("-", "").replace(" ", "")
    return f"{s[:4]}-{s[4:]}" if len(s) == 8 else ""


def _device_page(request: Request, code: str, problem: str = "", status: int = 200) -> HTMLResponse:
    return _TEMPLATES.TemplateResponse(
        request,
        "device.html",
        {"code": code, "problem": problem, "done": False},
        status_code=status,
        headers={"Cache-Control": "no-store"},
    )


@router.post("/oauth/device_authorization")
async def device_authorization(request: Request) -> JSONResponse:
    assert _store is not None and _settings is not None
    form = await request.form()
    client = await _store.get("client", str(form.get("client_id", "")))
    if client is None:
        return _error(400, "invalid_client", "unknown client_id")
    device_code = secrets.token_urlsafe(32)
    user_code = _new_user_code()
    await _store.put(
        "device",
        device_code,
        {"client_id": client["client_id"], "user_code": user_code, "status": "pending"},
        ttl=DEVICE_TTL,
    )
    await _store.put("device_user", user_code, {"device_code": device_code}, ttl=DEVICE_TTL)
    uri = f"{_settings.as_issuer}/oauth/device"
    return JSONResponse(
        {
            "device_code": device_code,
            "user_code": user_code,
            "verification_uri": uri,
            "verification_uri_complete": f"{uri}?user_code={user_code}",
            "expires_in": DEVICE_TTL,
            "interval": DEVICE_INTERVAL,
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("/oauth/device")
async def device_page(request: Request) -> HTMLResponse:
    """The verification page: the code is prefilled from verification_uri_complete,
    the user confirms it matches the terminal — a forwarded link never approves on
    its own (RFC 8628 §5.4)."""
    return _device_page(request, request.query_params.get("user_code", ""))


@router.post("/oauth/device")
async def device_confirm(request: Request):
    assert _store is not None and _settings is not None
    form = await request.form()
    typed = str(form.get("user_code", ""))
    user_code = _normalize_user_code(typed)
    index = await _store.get("device_user", user_code) if user_code else None
    if index is None:
        return _device_page(request, typed, "code not found or expired — check your terminal", 400)
    # Same Dex leg as /oauth/authorize: a pending under the Dex state, bound to
    # this browser by Authlib's session. A device login carries the audience scope
    # only — the MCP consent chain needs the client's own browser.
    pending_id = secrets.token_urlsafe(24)
    await _store.put(
        "pending",
        pending_id,
        {"device_code": index["device_code"], "scopes": [_settings.as_audience]},
        ttl=PENDING_TTL,
    )
    callback = _settings.app_base_url.rstrip("/") + "/oauth/as-callback"
    return await oauth.oidc.authorize_redirect(request, callback, state=pending_id, scope=DEX_SCOPE)


async def _device_settle(device_code: str, status: str, sub: str = "") -> dict | None:
    """Flip a pending device record to approved/denied and drop the user-code
    index. None when the record is gone or already settled."""
    assert _store is not None
    rec = await _store.get("device", device_code)
    if rec is None or rec["status"] != "pending":
        return None
    rec = {**rec, "status": status, "sub": sub} if sub else {**rec, "status": status}
    # Re-put with the full TTL: the client stops polling at expires_in anyway.
    await _store.put("device", device_code, rec, ttl=DEVICE_TTL)
    await _store.pop("device_user", rec["user_code"])
    return rec


async def _device_finish(request: Request, pending: dict) -> HTMLResponse:
    rec = await _device_settle(pending["device_code"], "approved", pending["sub"])
    if rec is None:
        return _html_error(400, "this device code has expired — start again from your terminal")
    logger.info("Device authorization approved for client %s", rec["client_id"])
    return _TEMPLATES.TemplateResponse(
        request, "device.html", {"code": "", "problem": "", "done": True}, headers={"Cache-Control": "no-store"}
    )
```

`as_callback` — two edits. In the `except Exception as exc:` branch after `logger.warning(...)`, before the `return _html_error(...)`:

```python
        if pending.get("device_code"):
            await _device_settle(pending["device_code"], "denied")
```
and replace `pending["sub"] = email` + the `todo = [...]` block's start with:

```python
    pending["sub"] = email
    if pending.get("device_code"):
        return await _device_finish(request, pending)
    todo = [
```

`token()` — add the branch before `return _error(400, "unsupported_grant_type")`:

```python
    if grant == DEVICE_GRANT:
        device_code = str(form.get("device_code", ""))
        rec = await _store.get("device", device_code)
        if rec is None:
            return _error(400, "expired_token")
        if rec["client_id"] != client_id:
            return _error(400, "invalid_grant")
        if rec["status"] == "pending":
            return _error(400, "authorization_pending")
        if rec["status"] == "denied":
            await _store.pop("device", device_code)
            return _error(400, "access_denied")
        taken = await _store.pop("device", device_code)  # approved: single redemption
        if taken is None:
            return _error(400, "expired_token")
        return await _issue(taken["sub"], client_id, _settings.as_audience)
```

Create `src/api/app/templates/device.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>alitellm-auth — Sign in from another device</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600&family=Outfit:wght@400;600&display=swap');
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #000; --surface: #0b101e; --border: #1e2233; --dim: #4a5173; --text: #c4cbe3; --bright: #e8ecf7;
    --accent: #10b981; --accent2: #34d399; --glow2: rgba(16,185,129,.15); --danger: #f87171;
    --mono: 'JetBrains Mono', monospace; --sans: 'Outfit', system-ui, sans-serif;
  }
  body { font-family: var(--sans); background: var(--bg); color: var(--text); min-height: 100vh;
    display: flex; align-items: center; justify-content: center; padding: 24px;
    background-image: radial-gradient(ellipse 80% 50% at 50% -20%, var(--glow2), transparent); }
  .card { width: 100%; max-width: 480px; background: var(--surface); border: 1px solid var(--border); border-radius: 16px; overflow: hidden; }
  .header { padding: 32px 32px 24px; border-bottom: 1px solid var(--border); }
  .status-label { font-family: var(--mono); font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 2px; color: var(--accent); margin-bottom: 16px; }
  .name { font-family: var(--mono); font-size: 15px; font-weight: 600; color: var(--bright); margin-bottom: 12px; }
  .name span { color: var(--accent2); }
  .greeting { font-size: 22px; font-weight: 600; color: var(--bright); line-height: 1.3; }
  .sub { margin-top: 6px; font-size: 14px; color: var(--dim); }
  .body { padding: 24px 32px 28px; display: grid; gap: 14px; }
  input { width: 100%; font-family: var(--mono); font-size: 22px; letter-spacing: 4px; text-align: center; text-transform: uppercase;
    background: #000; color: var(--bright); border: 1px solid var(--border); border-radius: 8px; padding: 12px; }
  input:focus { outline: 2px solid var(--accent); border-color: var(--accent); }
  button { font-family: var(--sans); font-size: 15px; font-weight: 600; color: #000; background: var(--accent);
    border: 0; border-radius: 8px; padding: 12px; cursor: pointer; }
  button:focus-visible { outline: 2px solid var(--bright); outline-offset: 2px; }
  .problem { font-family: var(--mono); font-size: 12px; color: var(--danger); }
</style>
</head>
<body>
  <div class="card">
    <div class="header">
      <div class="status-label">{% if done %}Signed in{% else %}Sign in from another device{% endif %}</div>
      <div class="name">alitellm<span>-auth</span></div>
      {% if done %}
      <div class="greeting">You are signed in</div>
      <div class="sub">Return to your terminal — you can close this tab.</div>
      {% else %}
      <div class="greeting">Confirm the code from your terminal</div>
      <div class="sub">Check it matches what the tool printed, then continue to sign in.</div>
      {% endif %}
    </div>
    {% if not done %}
    <form class="body" method="post" action="/oauth/device">
      <input name="user_code" id="user_code" value="{{ code }}" placeholder="XXXX-XXXX" autocomplete="off" autocapitalize="characters" spellcheck="false" required>
      <button type="submit">Confirm</button>
      {% if problem %}<div class="problem">{{ problem }}</div>{% endif %}
    </form>
    {% endif %}
  </div>
</body>
</html>
```

- [ ] **Step 4: Run the whole Python suite and lint**

Run: `cd src/api && .venv/bin/pytest tests/ -q && uvx ruff@0.8.4 check app tests && uvx ruff@0.8.4 format --check app tests`
Expected: 391 + 8 new = 399 passed; ruff clean (run `uvx ruff@0.8.4 format app tests` if the formatter complains, then re-check).

- [ ] **Step 5: Docs**

`CHANGELOG.md`, under `## [unreleased]`, add `### Added` (first section) with:

```markdown
- AS: RFC 8628 device grant for hosts with no usable browser. `POST
  /oauth/device_authorization` hands out a `XXXX-XXXX` code (10 min), the user
  confirms it on `/oauth/device` from any browser and signs in through the same
  Dex leg, and the host polls `/oauth/token` with
  `urn:ietf:params:oauth:grant-type:device_code`. A device login carries the
  audience scope only (no MCP scope chain). Advertised in the RFC 8414 document.
```

`TODO.md` — replace the item `- [ ] Claude Code loopback: when the browser is on another machine the redirect to` + its continuation line with:

```markdown
- [x] Remote / headless host login: RFC 8628 device grant on the AS
  (`/oauth/device_authorization`, `/oauth/device`), `opencode` method 2 and
  `ackstorm-token login --no-browser` (2026-09-21).
```

- [ ] **Step 6: Commit**

```bash
git add src/api/app/oauth_as/routes.py src/api/app/templates/device.html src/api/tests/test_oauth_as_routes.py CHANGELOG.md TODO.md
git commit -m "feat(oauth-as): RFC 8628 device grant" -m "A host with no usable browser (SSH, container) could not sign in: the
loopback redirect never reaches it. The AS now serves the device grant —
a user code the person confirms on /oauth/device from any browser, the
same Dex leg as /oauth/authorize, and a /oauth/token grant the host polls.
The device login carries the audience scope only; the MCP consent chain
needs the client's own browser.

Ported from ach 8eff416.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: OpenCode plugin — second method "SSO (device code)"

**Files:**
- Modify: `clients/opencode/index.mjs` (header comment, `pollDevice()`, second entry in `methods`)
- Modify: `clients/opencode/package.json` (`"version": "0.2.0"`)
- Modify: `test/opencode-auth.test.mjs` (fetch mock + one test)
- Modify: `README.md` (OpenCode section), `CHANGELOG.md`

**Interfaces:**
- Consumes: `discover(client)` → `{issuer, as, scope}` where `as` is the RFC 8414 document (now with `device_authorization_endpoint`), `clientId(d)`, `json(url, init)`, `token(d, form)` — all existing in `index.mjs`. AS contract from Task 1.
- Produces: `plugin.auth.methods[1]` with `label "SSO (device code — sign in from another browser)"`; `authorize()` resolves `{url, method: "auto", instructions, callback}`; `callback()` resolves `{type: "success", access, refresh, expires}` or `{type: "failed"}`.

- [ ] **Step 1: Write the failing test**

In `test/opencode-auth.test.mjs`:

(a) In the fetch mock, extend the metadata response and add the two device branches. The metadata line becomes:

```js
  if (url === `${ISSUER}/.well-known/oauth-authorization-server`) {
    return ok({ issuer: ISSUER, token_endpoint: `${ISSUER}/token`, registration_endpoint: `${ISSUER}/register`, authorization_endpoint: `${ISSUER}/authorize`, device_authorization_endpoint: `${ISSUER}/device_authorization` })
  }
  if (url === `${ISSUER}/device_authorization`) {
    return ok({ device_code: "dc-1", user_code: "BCDF-GHJK", verification_uri: `${ISSUER}/device`, verification_uri_complete: `${ISSUER}/device?user_code=BCDF-GHJK`, expires_in: 600, interval: 0.01 })
  }
```
and inside the `${ISSUER}/token` branch, before the `refresh_token` check:

```js
    if (form.get("grant_type") === "urn:ietf:params:oauth:grant-type:device_code") {
      devicePolls += 1
      if (devicePolls < 2) return new Response(JSON.stringify({ error: "authorization_pending" }), { status: 400 })
      return ok({ access_token: "a-device", refresh_token: "r-current", expires_in: 3600 })
    }
```
with `let devicePolls = 0` declared next to `let tokenCalls = 0`.

(b) Add the test after "a login registers once …":

```js
test("the device method opens the verification URL and polls until the user has signed in", async () => {
  const f = fakeClient()
  const plugin = await SsoAuth({ client: f.client })
  const method = plugin.auth.methods[1]
  assert.match(method.label, /device code/)
  const { url, instructions, callback } = await method.authorize()
  assert.equal(url, `${ISSUER}/device?user_code=BCDF-GHJK`)
  assert.match(instructions, /BCDF-GHJK/)
  const result = await callback()
  assert.equal(result.type, "success")
  assert.equal(result.access, "a-device")
  assert.equal(devicePolls, 2, "one authorization_pending, then the token")
  // Loopback stays the default method (OpenWork and the CLI take methods[0]).
  assert.equal(plugin.auth.methods[0].label, "SSO (browser)")
})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `node --test test/opencode-auth.test.mjs`
Expected: the new test fails with `TypeError: Cannot read properties of undefined (reading 'label')` (no `methods[1]`).

- [ ] **Step 3: Implement**

`clients/opencode/index.mjs` — in the header comment, after the install line, add:

```js
// Two ways in: a browser on this machine (loopback redirect), or the RFC 8628
// device grant for a remote/headless host — the URL is opened on ANY browser,
// the plugin polls the AS until the user has signed in there; nothing comes
// back to this machine but the token.
//
```

Before `function listen(state)` add:

```js
// RFC 8628 §3.4–3.5: poll /token every `interval` until the user has signed
// in on the other browser; authorization_pending keeps going, slow_down adds
// 5 s, anything else (expired_token, access_denied) ends it.
async function pollDevice(d, form, interval, expiresIn) {
  const deadline = Date.now() + expiresIn * 1000
  let wait = (interval || 5) * 1000
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms))
  for (;;) {
    await sleep(wait)
    const r = await fetch(d.as.token_endpoint, {
      method: "POST",
      headers: { "content-type": "application/x-www-form-urlencoded" },
      body: new URLSearchParams(form),
      signal: AbortSignal.timeout(15_000),
    })
    const j = await r.json()
    if (r.ok) return { access: j.access_token, refresh: j.refresh_token, expires: Date.now() + j.expires_in * 1000 }
    if (j.error === "slow_down") wait += 5000
    else if (j.error !== "authorization_pending") throw new Error(j.error ?? `${r.status}`)
    if (Date.now() > deadline) throw new Error("the code expired before you signed in")
  }
}
```

In `methods: [ … ]`, after the existing `"SSO (browser)"` object, add:

```js
        {
          type: "oauth",
          label: "SSO (device code — sign in from another browser)",
          async authorize() {
            const d = await discover(client)
            if (!d.as.device_authorization_endpoint) throw new Error("the authorization server does not offer the device grant")
            const client_id = await clientId(d)
            const da = await json(d.as.device_authorization_endpoint, {
              method: "POST",
              headers: { "content-type": "application/x-www-form-urlencoded" },
              body: new URLSearchParams({ client_id }),
            })
            return {
              url: da.verification_uri_complete ?? da.verification_uri,
              method: "auto",
              instructions: `Open the URL in any browser (this or another machine), confirm the code ${da.user_code} and sign in. This session completes on its own.`,
              async callback() {
                try {
                  const t = await pollDevice(d, { grant_type: "urn:ietf:params:oauth:grant-type:device_code", device_code: da.device_code, client_id }, da.interval, da.expires_in)
                  return { type: "success", ...t }
                } catch {
                  return { type: "failed" }
                }
              },
            }
          },
        },
```

`clients/opencode/package.json`: `"version": "0.2.0"`.

- [ ] **Step 4: Run the node tests**

Run: `node --test test/opencode-auth.test.mjs`
Expected: `# pass 3`, `# fail 0`.

- [ ] **Step 5: Docs**

`README.md`, OpenCode section, after the code block's `opencode auth login -p ackstorm` line's paragraph ("Nothing to configure: …"), add:

```markdown
On a remote or headless host pick the second method, **SSO (device code)**: opencode
prints a `XXXX-XXXX` code and a URL; open the URL in any browser, confirm the code and
sign in — the session completes on its own. A new plugin release is picked up with
`opencode plugin <url> -g -f`.
```

`CHANGELOG.md`, same `### Added` section as Task 1:

```markdown
- OpenCode plugin 0.2.0: second login method "SSO (device code — sign in from
  another browser)" for a remote or headless host (ported from ach `6fa97f8`).
```

- [ ] **Step 6: Commit**

```bash
git add clients/opencode/index.mjs clients/opencode/package.json test/opencode-auth.test.mjs README.md CHANGELOG.md
git commit -m "feat(opencode-auth): device-grant login for a remote or headless host" -m "Logging into opencode on a remote machine had no way in: the browser
loopback callback never reaches it. The plugin offers a second method,
the RFC 8628 device grant the AS now serves: the verification URL is
opened in any browser, the plugin polls /oauth/token until the user has
signed in there. The loopback method stays first, so OpenWork and the
opencode CLI keep their default. Plugin 0.2.0. Ported from ach 6fa97f8.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `ackstorm-token login --no-browser`

**Files:**
- Modify: `clients/ackstorm-token` (docstring, `client_id()` grant list, new `device_login()`, `main()`)
- Modify: `README.md` (Claude Code and Codex section), `CHANGELOG.md`

**Interfaces:**
- Consumes: `call(url, data, form)` (raises `urllib.error.HTTPError` on 4xx/5xx), `client_id(state, meta)`, `exchange(meta, form) -> {access_token, refresh_token, expires_at}`, `log()`, `metadata()`; AS contract from Task 1.
- Produces: `device_login(state: dict, meta: dict) -> dict` (same return shape as `login()`); CLI flag `--no-browser` accepted anywhere in argv.

There is no test harness for this stdlib script (by design: one file, zero deps). The check is `python3 -m py_compile clients/ackstorm-token` plus a dry run against a fake AS in Step 4.

- [ ] **Step 1: Implement**

Docstring — replace the three usage lines with:

```
    ackstorm-token                        # print a token (logs in if there is nothing to refresh)
    ackstorm-token login                  # force a new browser login
    ackstorm-token login --no-browser     # sign in from ANY browser: shows a code to confirm (RFC 8628)
    ackstorm-token logout                 # forget the tokens
```

`client_id()` — the registration's `"grant_types"` becomes `["authorization_code", "refresh_token", "urn:ietf:params:oauth:grant-type:device_code"]`.

After `login()` add:

```python
def device_login(state: dict, meta: dict) -> dict:
    """RFC 8628: this host shows a code, the user signs in from any browser, we poll."""
    if "device_authorization_endpoint" not in meta:
        sys.exit("the authorization server does not offer the device grant")
    cid = client_id(state, meta)
    da = call(meta["device_authorization_endpoint"], {"client_id": cid}, form=True)
    log(f"Open {da['verification_uri']} in any browser and enter the code:\n\n"
        f"    {da['user_code']}\n\n"
        f"Waiting for you to sign in… (expires in {da['expires_in'] // 60} min)")
    deadline = time.time() + da["expires_in"]
    wait = da.get("interval", 5)
    form = {"grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": da["device_code"], "client_id": cid}
    while time.time() < deadline:
        time.sleep(wait)
        try:
            tok = exchange(meta, form)
        except urllib.error.HTTPError as exc:
            err = json.load(exc).get("error") if exc.code == 400 else None
            if err == "authorization_pending":
                continue
            if err == "slow_down":
                wait += 5
                continue
            sys.exit(f"login failed: {err or exc.code}")
        state.update(tok)
        return state
    sys.exit("the code expired before you signed in")
```

`main()` — replace the first line `cmd = sys.argv[1] if len(sys.argv) > 1 else "print"` with:

```python
    args = [a for a in sys.argv[1:] if a != "--no-browser"]
    do_login = device_login if "--no-browser" in sys.argv else login
    cmd = args[0] if args else "print"
```
and replace both `login(state, ...)` calls inside `main()` (`state = login(state, metadata())` and `state = login(state, meta)`) with `do_login(...)` keeping their arguments.

- [ ] **Step 2: Compile and dry-run against a fake AS**

Run (repo root):

```bash
python3 -m py_compile clients/ackstorm-token && echo compiled
# Fake AS: a 12-line server that answers discovery, registration, device_authorization
# and a token endpoint that says authorization_pending once, then issues.
python3 - <<'EOF' &
import json, http.server
polls = {"n": 0}
class H(http.server.BaseHTTPRequestHandler):
    def _j(self, code, body): self.send_response(code); self.send_header("content-type","application/json"); self.end_headers(); self.wfile.write(json.dumps(body).encode())
    def do_GET(self):
        if self.path.startswith("/.well-known/oauth-protected-resource"): return self._j(200, {"authorization_servers": ["http://127.0.0.1:8765"]})
        if self.path == "/.well-known/oauth-authorization-server": return self._j(200, {"issuer": "http://127.0.0.1:8765", "token_endpoint": "http://127.0.0.1:8765/token", "registration_endpoint": "http://127.0.0.1:8765/register", "authorization_endpoint": "http://127.0.0.1:8765/authorize", "device_authorization_endpoint": "http://127.0.0.1:8765/device_authorization"})
        self._j(404, {})
    def do_POST(self):
        self.rfile.read(int(self.headers.get("content-length", 0)))
        if self.path == "/register": return self._j(201, {"client_id": "c1"})
        if self.path == "/device_authorization": return self._j(200, {"device_code": "dc", "user_code": "BCDF-GHJK", "verification_uri": "http://127.0.0.1:8765/device", "expires_in": 60, "interval": 1})
        polls["n"] += 1
        if polls["n"] < 2: return self._j(400, {"error": "authorization_pending"})
        self._j(200, {"access_token": "a-device", "refresh_token": "r1", "expires_in": 3600})
    def log_message(self, *_): pass
http.server.HTTPServer(("127.0.0.1", 8765), H).serve_forever()
EOF
FAKE=$!
sleep 1
XDG_CONFIG_HOME=$(mktemp -d) ACKSTORM_API=http://127.0.0.1:8765 timeout 30 python3 clients/ackstorm-token login --no-browser; echo "exit=$?"
kill $FAKE
```
Expected: stderr shows the code `BCDF-GHJK` and the URL, then `Logged in.`; `exit=0`. (`timeout 30` is the failure path if polling never ends.)

- [ ] **Step 3: Docs**

`README.md`, "Claude Code and Codex" section, after the sentence ending `refresh token in \`~/.config/ackstorm-ai/token.json\`).` add a paragraph:

```markdown
On a host with no usable browser run `ackstorm-token login --no-browser` once: it prints
a `XXXX-XXXX` code and a URL; open the URL in any browser, confirm the code and sign in.
Later runs refresh silently as usual.
```

`CHANGELOG.md`, same `### Added` section:

```markdown
- `ackstorm-token login --no-browser`: the device grant from the CLI (Claude Code /
  Codex on a remote host).
```

- [ ] **Step 4: Commit**

```bash
git add clients/ackstorm-token README.md CHANGELOG.md
git commit -m "feat(ackstorm-token): login --no-browser through the device grant" -m "Claude Code and Codex on an SSH host had only the paste-the-URL fallback.
The helper now signs in through the AS's RFC 8628 device grant when asked:
it prints the code and the verification URL, polls /oauth/token and stores
the same token pair the loopback login does.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Final gate (once, after Task 3)

- [ ] Python: `cd src/api && .venv/bin/pytest tests/ -q` → 0 failures; ruff 0.8.4 check + format clean.
- [ ] Node: `node --test test/opencode-auth.test.mjs` → 3 pass.
- [ ] `python3 -m py_compile clients/ackstorm-token`.
- [ ] Docker builder stage still bakes the plugin: `docker build -q --target builder -t t . && docker run --rm t sh -c 'tar -tzf /app/opencode-auth.tgz' && docker rmi t` → `package/index.mjs`, `package/package.json`.
- [ ] One review of the three commits together.
- [ ] Manual, after deploy (not automatable here): `ackstorm-token login --no-browser` against the real AS from an SSH host; `opencode auth login -p ackstorm` → method 2 on the same host.
