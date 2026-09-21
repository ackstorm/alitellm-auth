# OAuth Front Door — port the ACH fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port to the restored OAuth front door (branch `restore/oauth-front-door`, commit `4e38245`) the three bug classes the sibling repo `../ach` fixed after this code was ported there (2026-09-17 → 2026-09-21), so they are not re-discovered here.

**Architecture:** Two seams. (1) The Go Envoy `ext_authz` service (`authz/`) learns path families: `/v1`, `/gemini`, `/mcp`, `/a2a` require a credential; every other path on the API host is a catch-all where a presented credential is resolved and nothing presented is forwarded untouched. `Authorization` is only ever consumed when it carries our own JWS; anything else there is LiteLLM's to authenticate. The `legacyPassthrough` knob goes away. (2) The Python authorization server (`src/api/app/oauth_as/routes.py`) asks Dex for `offline_access`, keeps ONE Dex refresh token per user (`dexrt:<email>` in the AS store, newest login wins) and replays it at Dex on every `refresh_token` grant before rotating its own token, so a user disabled at the identity provider is out at the next refresh instead of after `AS_REFRESH_TTL_SECONDS`.

**Tech Stack:** Go 1.25 (`authz/`, tests with `go test`), Python 3.12 + FastAPI + Authlib 1.8 + httpx (`src/api`, tests with pytest + `unittest.mock`), Helm chart under `deploy/helm/alitellm-auth`.

**Source of truth for each fix (read the commit message, not just the diff):**

| Task | ach commit(s) | Problem fixed there |
|---|---|---|
| 1 | `1abb5f7`, `d091c08`, `e26ec26`, `d148e04` | authz 401'd LiteLLM's own UI/admin calls on the host (foreign `Authorization`, or nothing presented outside the model/MCP paths) |
| 2 | `3194271`, `46a2101` | AS never re-asked Dex on refresh; then, one Dex refresh token per (user, client) means a per-session copy strands the first tool when a second one logs in |
| 3 | `12539cd` | as-callback crashed with a bare 500 when LiteLLM provisioning failed |

Not ported, on purpose: `0258c5c` (re-mint a key LiteLLM no longer lists — `internal.py::_key_alive` already does this per front-key call; the authz key cache serves a deleted key for at most `AUTHZ_KEY_CACHE_TTL_SECONDS`=300 s, accepted), `ebe5bde` (login CSRF binding — covered by Authlib's session state, test `test_a_callback_from_a_browser_that_did_not_start_the_request_is_refused`), `8eff416`/`6fa97f8` (RFC 8628 device grant — a feature, separate plan), and everything BIP/reaper/content-service specific.

## Global Constraints

- All output in English: code, comments, docs, commits.
- Python: run everything from `src/api/` with the repo venv (`.venv/bin/pytest`, `uv run ruff`). The CI ruff pin is **0.8.4** — lint with `uvx ruff@0.8.4 check app tests && uvx ruff@0.8.4 format --check app tests` before every commit (local `uv run ruff` is 0.14 and disagrees on one rule; CI is the gate).
- Go: no `go` on the host. Run `docker run --rm -v "$PWD/authz:/src" -w /src -e GOPATH=/tmp/gopath golang:1.25-alpine sh -c 'gofmt -l . && go vet ./... && go test ./...'` from the repo root (`authz/go.mod` requires go ≥ 1.25; the `golang:1.23-alpine` image on the box fails).
- Helm: `helm template t deploy/helm/alitellm-auth --set authServer.enabled=true --set authz.enabled=true --set istio.enabled=true --set istio.gateway.name=gw` must render.
- Commit on branch `restore/oauth-front-door`. Conventional commit subjects < 72 chars. Commit trailer: `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.
- Do NOT run `make release-*`, `git tag`, or push tags.
- Store values are dicts (`Store.put(kind, key, value: dict, ttl)`); the Dex refresh token record is `{"rt": "<token>"}` under kind `dexrt`, key = lower-cased email.
- Never log a refresh token, an access token or an `sk-`.

---

### Task 1: authz — path families, foreign `Authorization` forwarded, `legacyPassthrough` removed

**Files:**
- Modify: `authz/decide.go:29-83` (`Decide` and its doc comment), add `protected()` + `protectedPrefixes`
- Modify: `authz/config.go:16,38` (drop `LegacyPassthrough`)
- Modify: `authz/main.go:49` (log line no longer prints `cfg.LegacyPassthrough`)
- Modify: `authz/decide_test.go:28-33,90-116,156-164`
- Modify: `deploy/helm/alitellm-auth/values.yaml:192` (drop `legacyPassthrough`)
- Modify: `deploy/helm/alitellm-auth/templates/authz-deployment.yaml:45-46` (drop the `AUTHZ_LEGACY_PASSTHROUGH` env)
- Modify: `CHANGELOG.md` (`## [unreleased]`)

**Interfaces:**
- Consumes: `Decide(ctx, cfg Config, path string, h map[string]string, v Verifier, r KeyResolver) Decision` — signature unchanged; `server.go:25` keeps calling it.
- Produces: `func protected(path string) bool` (package-private), `var protectedPrefixes = []string{"/v1/", "/gemini/", "/mcp/", "/a2a/"}`. `Config` loses the `LegacyPassthrough` field.

The policy after this task (this text becomes the `Decide` doc comment):

```
1. custom header (or x-api-key) present → a LiteLLM key (sk-…) is renamed into the
   outbound header; our JWS is verified and mapped (401 invalid_token when it does
   not verify; 403 insufficient_scope on /mcp/<svc> without that scope). The slot
   header is removed. Authorization is untouched. Same on every path.
2. Authorization: Bearer <JWS> → ours: verified, mapped, removed (same 401/403 as 1).
3. Authorization carrying anything else (a LiteLLM key in the OpenAI-SDK shape,
   LiteLLM UI's own bearer, Basic …) → not ours: forwarded untouched, LiteLLM
   authenticates it. Nothing is set.
4. the outbound header already present → forwarded untouched (it is LiteLLM's key
   by definition; LiteLLM authenticates it).
5. nothing presented → 401 + challenge on a protected family (/v1, /gemini, /mcp,
   /a2a); forwarded untouched on the catch-all (LiteLLM's UI, /health/*, /key/*, …).
x-user-id is stripped in every case (LiteLLM's impersonation contract with the console).
```

- [ ] **Step 1: Write the failing Go tests**

Replace `TestLegacyOutboundHeaderPassesThroughOnlyWhenEnabled` and `TestALiteLLMKeyInAuthorizationPassesUntouchedWhileLegacyIsOn` in `authz/decide_test.go` with these, and add the last two. Also delete `LegacyPassthrough: true,` from the `cfg` var at the top of the file.

```go
func TestOutboundHeaderPassesThroughUntouched(t *testing.T) {
	// A LiteLLM key already in LiteLLM's own header: LiteLLM authenticates it.
	h := map[string]string{"x-litellm-api-key": "Bearer sk-old", "x-user-id": "spoof"}
	d := decide(h, fakeVerifier{}, &fakeResolver{})
	if !d.Allow || len(d.Set) != 0 || !contains(d.Remove, "x-user-id") || contains(d.Remove, "x-litellm-api-key") {
		t.Fatalf("outbound header: %+v", d)
	}
}

func TestAForeignAuthorizationIsForwardedUntouchedOnEveryPath(t *testing.T) {
	// Not ours: a LiteLLM key in the OpenAI-SDK shape, Anthropic's OAuth, LiteLLM
	// UI's own bearer on /v1/agents or /key/info, a Basic credential. LiteLLM decides.
	for _, path := range []string{v1, "/v1/agents", "/key/info", "/health/license", "/mcp/mcp-aws-eks-ro"} {
		for _, auth := range []string{"Bearer sk-abc", "Bearer sk-ant-oat01-xyz", "Bearer opaque-session-token", "Basic dXNlcjpwdw=="} {
			r := &fakeResolver{}
			d := Decide(context.Background(), cfg, path, map[string]string{"authorization": auth, "x-user-id": "spoof"}, fakeVerifier{err: errors.New("never called")}, r)
			if !d.Allow || len(d.Set) != 0 || contains(d.Remove, "authorization") || !contains(d.Remove, "x-user-id") {
				t.Fatalf("%s %q: %+v", path, auth, d)
			}
			if r.calls != 0 {
				t.Fatalf("%s %q: resolver called for a foreign credential", path, auth)
			}
		}
	}
}

func TestAnonymousOnTheCatchAllIsForwardedUntouched(t *testing.T) {
	// LiteLLM's UI, its health and admin surfaces: nothing presented is not our
	// business outside the protected families.
	for _, path := range []string{"/", "/ui", "/ui/", "/health/license", "/key/info", "/sso/callback", "/v2/models", "/v1beta"} {
		d := Decide(context.Background(), cfg, path, map[string]string{"x-user-id": "spoof"}, fakeVerifier{}, &fakeResolver{})
		if !d.Allow || len(d.Set) != 0 || !contains(d.Remove, "x-user-id") {
			t.Fatalf("%s: %+v", path, d)
		}
	}
}

func TestProtectedFamiliesRequireACredential(t *testing.T) {
	for _, path := range []string{"/v1", "/v1/", "/v1/chat/completions", "/gemini/v1beta/models", "/mcp/mcp-aws-eks-ro", "/a2a/agent"} {
		d := Decide(context.Background(), cfg, path, map[string]string{}, fakeVerifier{}, &fakeResolver{})
		if d.Allow || d.Status != 401 || d.WWWAuthenticate == "" {
			t.Fatalf("%s: %+v", path, d)
		}
	}
	for _, path := range []string{"/v10/x", "/gemini-ui", "/mcpx", "/a2ab"} {
		if protected(path) {
			t.Fatalf("%s must not be protected", path)
		}
	}
}
```

Keep `TestAnonymousIs401WithAChallenge` (it runs on `v1`) but extend its assertion so the new message is pinned:

```go
	if d.Body != `{"error":"unauthorized","error_description":"present a LiteLLM key or a token from the authorization server in x-genai-api-key, x-api-key or Authorization: Bearer"}` {
		t.Fatalf("body: %s", d.Body)
	}
```

- [ ] **Step 2: Run the Go tests to verify they fail**

Run (repo root): `docker run --rm -v "$PWD/authz:/src" -w /src -e GOPATH=/tmp/gopath golang:1.25-alpine sh -c 'go vet ./... && go test ./...'`
Expected: compile error `undefined: protected` (and `unknown field LegacyPassthrough` once you remove it from `cfg`).

- [ ] **Step 3: Rewrite `Decide`, drop `LegacyPassthrough`**

`authz/decide.go` — replace lines 29-83 (the doc comment and `Decide`) with:

```go
// protectedPrefixes are the model API and the MCP/A2A servers: a request
// there must carry a credential. Everything else on the host (LiteLLM's UI,
// /health/*, /key/*, /v2/*, …) is the catch-all — a presented credential is
// resolved, nothing presented is forwarded untouched and LiteLLM decides.
var protectedPrefixes = []string{"/v1/", "/gemini/", "/mcp/", "/a2a/"}

func protected(path string) bool {
	for _, p := range protectedPrefixes {
		if path == strings.TrimSuffix(p, "/") || strings.HasPrefix(path, p) {
			return true
		}
	}
	return false
}

// Decide is the whole policy. Order matters and is the contract.
//
// Authorization is not ours: it may carry the upstream provider's credential
// (Claude Code with an Anthropic subscription sends Anthropic's OAuth there and
// our key in the custom header), LiteLLM's own UI bearer, or a LiteLLM key in
// the OpenAI-SDK shape. It is consumed in exactly one case — when it carries
// OUR JWS — so LiteLLM receives exactly one thing from us, the outbound header.
//
//  1. custom header (or x-api-key) present → a LiteLLM key (sk-…) is renamed;
//     our JWT is verified and mapped. That header is removed. Authorization untouched.
//  2. Authorization: Bearer <JWS> → ours: verified, mapped, removed
//  3. Authorization carrying anything else → not ours: forwarded untouched,
//     LiteLLM authenticates it
//  4. the outbound header already present → forwarded untouched (LiteLLM's key)
//  5. nothing presented → 401 with the pointer that starts the ceremony on a
//     protected family; forwarded untouched on the catch-all
//
// A user token on /mcp/<svc> must carry scope <svc> (a grant for that service),
// or the answer is the 403 that makes an MCP client step up. Agent keys are
// not scope-gated: their grant comes through the `authenticate` tool.
func Decide(ctx context.Context, cfg Config, path string, h map[string]string, v Verifier, r KeyResolver) Decision {
	// x-user-id is LiteLLM's impersonation contract with the console; nothing
	// from the internet may carry it. Also stripped at the route.
	strip := []string{"x-user-id"}
	untouched := Decision{Allow: true, Set: map[string]string{}, Remove: strip}

	// x-api-key is where the Anthropic SDK puts an API key: Claude Code with
	// ANTHROPIC_API_KEY or an apiKeyHelper sends it there, never in
	// Authorization. Same two shapes as the custom header.
	for _, name := range []string{cfg.InboundHeader, "x-api-key"} {
		raw := h[name]
		if raw == "" {
			continue
		}
		tok := bareKey(raw)
		remove := append(strip, name)
		if !looksLikeJWS(tok) {
			return allowWithKey(cfg, tok, remove)
		}
		return userPath(ctx, cfg, path, tok, remove, v, r)
	}
	if auth := h["authorization"]; auth != "" {
		if tok := bareKey(auth); strings.HasPrefix(auth, "Bearer ") && looksLikeJWS(tok) {
			return userPath(ctx, cfg, path, tok, append(strip, "authorization"), v, r)
		}
		return untouched // not ours; LiteLLM authenticates it
	}
	if h[cfg.OutboundHeader] != "" || !protected(path) {
		return untouched
	}
	return deny(401, challenge(cfg, path, ""),
		`{"error":"unauthorized","error_description":"present a LiteLLM key or a token from the authorization server in `+cfg.InboundHeader+`, x-api-key or Authorization: Bearer"}`)
}
```

`authz/config.go` — delete line 16 (`LegacyPassthrough   bool …`) and line 38 (`LegacyPassthrough:   envOr("AUTHZ_LEGACY_PASSTHROUGH", "true") == "true",`).

`authz/main.go:48-49` — the startup log becomes:

```go
	log.Printf("authz listening on %s (inbound %s → outbound %s, issuer=%s)",
		cfg.ListenAddr, cfg.InboundHeader, cfg.OutboundHeader, cfg.Issuer)
```

- [ ] **Step 4: Run the Go tests to verify they pass**

Run: `docker run --rm -v "$PWD/authz:/src" -w /src -e GOPATH=/tmp/gopath golang:1.25-alpine sh -c 'gofmt -l . && go vet ./... && go test ./...'`
Expected: `gofmt -l` prints nothing; `ok  	github.com/ackstorm/alitellm-auth/authz`.

- [ ] **Step 5: Drop the knob from the chart, note the change**

`deploy/helm/alitellm-auth/values.yaml` — delete line 192 (`legacyPassthrough: true …`). Right below `outboundHeader:` add:

```yaml
  # Only /v1, /gemini, /mcp and /a2a require a credential. Every other path on
  # the host (LiteLLM's UI, /health/*, /key/*) is forwarded as it came when
  # nothing is presented; a presented credential is resolved everywhere.
  # Authorization is consumed only when it carries this AS's own token.
```

`deploy/helm/alitellm-auth/templates/authz-deployment.yaml` — delete lines 45-46 (`- name: AUTHZ_LEGACY_PASSTHROUGH` and its `value:`).

`CHANGELOG.md`, under `## [unreleased]`, add a `### Fixed` section (create it if absent) with:

```markdown
- authz: LiteLLM's own UI and admin surfaces on the API host work again. Only
  `/v1`, `/gemini`, `/mcp` and `/a2a` require a credential; every other path is
  forwarded untouched when nothing is presented. An `Authorization` header that
  is not this AS's own token (LiteLLM's UI bearer, an `sk-` in the OpenAI-SDK
  shape) is forwarded untouched everywhere and LiteLLM authenticates it. The
  `authz.legacyPassthrough` value and `AUTHZ_LEGACY_PASSTHROUGH` are gone (ported
  from ach `1abb5f7`, `d091c08`, `e26ec26`).
```

Run: `helm template t deploy/helm/alitellm-auth --set authServer.enabled=true --set authz.enabled=true --set istio.enabled=true --set istio.gateway.name=gw | grep -c AUTHZ_LEGACY`
Expected: `0` (and the command exits 1 from grep only — the template itself rendered).

- [ ] **Step 6: Commit**

```bash
git add authz/ deploy/helm/alitellm-auth/values.yaml deploy/helm/alitellm-auth/templates/authz-deployment.yaml CHANGELOG.md
git commit -m "fix(authz): protected families only; foreign Authorization forwarded untouched" -m "Outside /v1, /gemini, /mcp and /a2a the authz answered 401 to LiteLLM's own
UI and admin calls (nothing presented, or LiteLLM's own bearer in
Authorization) before LiteLLM saw them. Rule now: a credential is required
only on the protected families; Authorization is consumed only when it is
this AS's JWS, anything else there is forwarded untouched and LiteLLM
authenticates it; the outbound header passes as it came. legacyPassthrough
had no remaining meaning and is gone.

Ported from ach 1abb5f7, d091c08, e26ec26.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: AS — `offline_access`, one Dex refresh token per user, re-validate at Dex on every refresh

**Files:**
- Modify: `src/api/app/oauth_as/routes.py:33-37` (constants), `:275-278` (authorize redirect), `:281-308` (`as_callback`), `:454-500` (`_user_exists`, `token`)
- Modify: `src/api/tests/test_oauth_as_routes.py:229-247`, `:343-372`, `:625-641`, `:700-783`
- Modify: `docs/dex-integration.md:22` (scopes paragraph), `TODO.md`, `CHANGELOG.md`

**Interfaces:**
- Consumes: `oauth.oidc` (Authlib Starlette client registered in `app/auth.py::configure_auth`): `authorize_redirect(request, redirect_uri, **kwargs)` accepts a per-call `scope=` (Authlib 1.8 `create_authorization_url`: `if "scope" not in kwargs: kwargs["scope"] = self.scope`); `authorize_access_token(request)` returns Dex's token dict (`refresh_token` present when `offline_access` was granted); `load_server_metadata()` returns the OIDC discovery document (`token_endpoint`). Store from `app.oauth_as.store.Store`: `get/put/pop(kind, key)`.
- Produces (module-level in `routes.py`, all patched by tests by dotted path `app.oauth_as.routes.<name>`):
  - `DEX_SCOPE = "openid email profile offline_access"`
  - `class DexRefused(Exception)`
  - `async def _dex_refresh(refresh_token: str) -> str` — returns the rotated Dex refresh token (the same one when Dex did not rotate); raises `DexRefused` on a 4xx from Dex, `httpx.HTTPError` when Dex is unreachable or 5xx.
  - `async def _revalidate_at_dex(sub: str) -> str | None` — replays the user's shared `dexrt` record, stores the rotated one, returns it; `None` when the IdP no longer honours the user (record deleted); raises `httpx.HTTPError` when Dex is unreachable.

- [ ] **Step 1: Write the failing tests**

In `src/api/tests/test_oauth_as_routes.py`:

(a) `test_authorize_stores_request_and_redirects_to_dex_with_https_callback` — after `assert kwargs["state"]` add:

```python
    # offline_access: Dex hands back a refresh token the AS replays at every
    # refresh of ours, so a user disabled at the IdP is out within one access TTL.
    assert kwargs["scope"] == "openid email profile offline_access"
```

(b) `test_as_callback_mints_code_returns_to_client_and_eagerly_creates_user` — change the mocked token to carry a refresh token and assert it is stored once per user:

```python
        mock_oauth.oidc.authorize_access_token = AsyncMock(
            return_value={"userinfo": {"email": " U@X.COM ", "name": "U"}, "refresh_token": "dex-rt-1"}
        )
```
and at the end of the test:
```python
    assert asyncio.run(routes._store.get("dexrt", "u@x.com")) == {"rt": "dex-rt-1"}
```

(c) `_login_with` helper (line ~386) — same: `return_value={"userinfo": {"email": "u@x.com"}, "refresh_token": "dex-rt-1"}`.

(d) New test right after (b):

```python
def test_as_callback_fails_loud_when_dex_issues_no_refresh_token():
    c = make_client()
    client_id = _register(c)
    with patch("app.oauth_as.routes.oauth") as mock_oauth:
        mock_oauth.oidc.authorize_redirect = AsyncMock(
            return_value=RedirectResponse("http://dex.test/auth", status_code=302)
        )
        c.get("/oauth/authorize", params=_authorize_params(client_id), follow_redirects=False)
        pending_id = mock_oauth.oidc.authorize_redirect.call_args.kwargs["state"]
        mock_oauth.oidc.authorize_access_token = AsyncMock(
            return_value={"userinfo": {"email": "u@x.com"}}  # no refresh_token
        )
        with patch("app.oauth_as.routes.ensure_team_and_user", AsyncMock()) as ensure:
            r = c.get(f"/oauth/as-callback?code=dexcode&state={pending_id}", follow_redirects=False)
    assert r.status_code == 400 and "refresh token" in r.text
    ensure.assert_not_awaited()
    assert asyncio.run(routes._store.get("dexrt", "u@x.com")) is None
```

(e) `_seed_code` — also seed the user's Dex refresh token so the refresh tests have one:

```python
def _seed_code(client_id: str, code="thecode") -> None:
    asyncio.run(routes._store.put("dexrt", "u@x.com", {"rt": "dex-rt-1"}))
    asyncio.run(
        routes._store.put(
            "code",
            code,
            {
                "client_id": client_id,
                "redirect_uri": "http://127.0.0.1:5000/cb",
                "state": "s",
                "code_challenge": CHALLENGE,
                "scope": "alitellm",
                "sub": "u@x.com",
            },
            ttl=120,
        )
    )
```
(only the first `asyncio.run(...)` line is new.)

(f) The four existing refresh tests (`test_refresh_rotates_and_the_old_token_dies`, `test_refresh_for_an_offboarded_user_consumes_token_without_replacement`, `test_refresh_litellm_outage_preserves_refresh_token`, `test_wrong_client_refresh_does_not_consume_token`) keep their assertions; wrap each `with patch("app.oauth_as.routes._user_exists", …)` in an outer `with patch("app.oauth_as.routes._dex_refresh", AsyncMock(return_value="dex-rt-2")):` so Dex says yes. In `test_refresh_rotates_and_the_old_token_dies` add, after the first successful refresh:

```python
        assert asyncio.run(routes._store.get("dexrt", "u@x.com")) == {"rt": "dex-rt-2"}
```
In `test_wrong_client_refresh_does_not_consume_token` also assert the Dex mock was not awaited (the client check comes first).

(g) New tests after `test_wrong_client_refresh_does_not_consume_token`:

```python
def _refresh(c: TestClient, client_id: str, refresh_token: str):
    return c.post(
        "/oauth/token",
        data={"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": client_id},
    )


def test_refresh_refused_by_the_idp_ends_every_session_of_the_user():
    c = make_client()
    client_id = _register(c)
    _seed_code(client_id)
    first = c.post("/oauth/token", data=_token_form(client_id)).json()
    _seed_code(client_id, code="second")
    sibling = c.post("/oauth/token", data=_token_form(client_id, code="second")).json()
    with (
        patch("app.oauth_as.routes._dex_refresh", AsyncMock(side_effect=routes.DexRefused("invalid_grant"))) as dex,
        patch("app.oauth_as.routes._user_exists", AsyncMock(return_value=True)) as exists,
    ):
        r = _refresh(c, client_id, first["refresh_token"])
        assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
        assert asyncio.run(routes._store.get("refresh", first["refresh_token"])) is None
        assert asyncio.run(routes._store.get("dexrt", "u@x.com")) is None
        exists.assert_not_awaited()
        # The sibling session fails its next refresh without asking Dex again.
        dex.reset_mock()
        r = _refresh(c, client_id, sibling["refresh_token"])
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
    dex.assert_not_awaited()
    assert asyncio.run(routes._store.get("refresh", sibling["refresh_token"])) is None


def test_refresh_with_the_idp_unreachable_is_503_and_keeps_everything():
    c = make_client()
    client_id = _register(c)
    _seed_code(client_id)
    first = c.post("/oauth/token", data=_token_form(client_id)).json()
    with patch("app.oauth_as.routes._dex_refresh", AsyncMock(side_effect=httpx.ConnectError("down"))):
        r = _refresh(c, client_id, first["refresh_token"])
    assert r.status_code == 503 and r.json()["error"] == "temporarily_unavailable"
    assert asyncio.run(routes._store.get("refresh", first["refresh_token"])) is not None
    assert asyncio.run(routes._store.get("dexrt", "u@x.com")) == {"rt": "dex-rt-1"}


def test_refresh_retries_once_when_a_sibling_rotated_the_shared_dex_token():
    # Two tools refresh in the same second: the second replays a Dex token the
    # first just rotated. Dex refuses it; the token stored NOW is tried once
    # before the user's sessions are ended.
    c = make_client()
    client_id = _register(c)
    _seed_code(client_id)
    first = c.post("/oauth/token", data=_token_form(client_id)).json()

    async def refuse_then_accept(rt: str) -> str:
        if rt == "dex-rt-1":
            await routes._store.put("dexrt", "u@x.com", {"rt": "dex-rt-2"})  # the sibling won
            raise routes.DexRefused("invalid_grant")
        assert rt == "dex-rt-2"
        return "dex-rt-3"

    with (
        patch("app.oauth_as.routes._dex_refresh", AsyncMock(side_effect=refuse_then_accept)) as dex,
        patch("app.oauth_as.routes._user_exists", AsyncMock(return_value=True)),
    ):
        r = _refresh(c, client_id, first["refresh_token"])
    assert r.status_code == 200, r.text
    assert dex.await_count == 2
    assert asyncio.run(routes._store.get("dexrt", "u@x.com")) == {"rt": "dex-rt-3"}


def test_refresh_without_a_dex_token_on_file_is_invalid_grant_without_asking_dex():
    c = make_client()
    client_id = _register(c)
    _seed_code(client_id)
    first = c.post("/oauth/token", data=_token_form(client_id)).json()
    asyncio.run(routes._store.pop("dexrt", "u@x.com"))  # e.g. Redis flushed, or ended by a sibling
    with patch("app.oauth_as.routes._dex_refresh", AsyncMock()) as dex:
        r = _refresh(c, client_id, first["refresh_token"])
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
    dex.assert_not_awaited()
    assert asyncio.run(routes._store.get("refresh", first["refresh_token"])) is None


@respx.mock
def test_dex_refresh_posts_the_token_endpoint_and_classifies_the_answer():
    make_client()  # configures routes._settings
    endpoint = respx.post("http://dex.test/dex/token")
    with patch("app.oauth_as.routes.oauth") as mock_oauth:
        mock_oauth.oidc.load_server_metadata = AsyncMock(
            return_value={"token_endpoint": "http://dex.test/dex/token"}
        )
        endpoint.mock(return_value=httpx.Response(200, json={"access_token": "a", "refresh_token": "dex-rt-2"}))
        assert asyncio.run(routes._dex_refresh("dex-rt-1")) == "dex-rt-2"
        sent = endpoint.calls.last.request
        assert b"grant_type=refresh_token" in sent.content and b"refresh_token=dex-rt-1" in sent.content
        assert sent.headers["authorization"].startswith("Basic ")
        # Dex may answer without rotating: the presented token stays valid.
        endpoint.mock(return_value=httpx.Response(200, json={"access_token": "a"}))
        assert asyncio.run(routes._dex_refresh("dex-rt-1")) == "dex-rt-1"
        endpoint.mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
        with pytest.raises(routes.DexRefused):
            asyncio.run(routes._dex_refresh("dex-rt-1"))
        endpoint.mock(return_value=httpx.Response(502))
        with pytest.raises(httpx.HTTPError):
            asyncio.run(routes._dex_refresh("dex-rt-1"))
```
Add `import pytest` to the test module imports (`respx` and `httpx` are already imported).

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd src/api && .venv/bin/pytest tests/test_oauth_as_routes.py -q`
Expected: the new tests fail with `AttributeError: module 'app.oauth_as.routes' has no attribute '_dex_refresh'` / `DexRefused`; (a) fails on `KeyError: 'scope'`; (b) fails on the `dexrt` assertion.

- [ ] **Step 3: Implement in `routes.py`**

Constants (after `HINT_TTL`, line 37):

```python
# offline_access: Dex hands back a refresh token that every refresh of OURS
# replays at Dex first, so a user disabled at the identity provider is out at
# the next refresh, not after AS_REFRESH_TTL_SECONDS. Requested only here, not
# by the console login: Dex keeps ONE refresh token per (user, client) and
# replaces it whenever a login asks for offline_access.
DEX_SCOPE = "openid email profile offline_access"
DEXRT = "dexrt"  # store kind: the user's Dex refresh token, keyed by email
```

`authorize` (line 278):

```python
    return await oauth.oidc.authorize_redirect(request, callback, state=pending_id, scope=DEX_SCOPE)
```

`as_callback` — replace lines 295-299 with:

```python
    userinfo = token.get("userinfo") or {}
    email = (userinfo.get("email") or "").strip().lower()
    if not email:
        return _html_error(400, "the identity provider returned no email")
    dex_refresh = token.get("refresh_token")
    if not dex_refresh:
        # Loud, at login: the alternative is a session that dies at its first refresh.
        logger.error("Dex issued no refresh token: offline_access not granted for this connector")
        return _html_error(400, "the identity provider issued no refresh token (offline_access)")
    await ensure_team_and_user(email, _settings, name=userinfo.get("name"))
    # One Dex refresh token per user, newest login wins — Dex itself keeps one
    # per (user, client) and replaces it on a new login, so a second tool
    # signing in must not strand the first tool's session.
    await _store.put(DEXRT, email, {"rt": dex_refresh}, ttl=_settings.as_refresh_ttl_seconds)
```
(Task 3 wraps the `ensure_team_and_user` call; leave it bare here.)

Replace `_user_exists` … end of file (lines 454-500) with:

```python
async def _user_exists(sub: str) -> bool:
    assert _settings is not None
    try:
        await get_litellm_user(sub, _settings)
    except LiteLLMUserNotFound:
        return False
    return True


class DexRefused(Exception):
    """Dex answered the refresh with an OAuth error (invalid_grant): the identity
    provider no longer honours the user, the token expired or was rotated away."""


async def _dex_refresh(refresh_token: str) -> str:
    """Replay a Dex refresh token; return the rotated one (the same one when Dex
    did not rotate). DexRefused on a 4xx; httpx.HTTPError when Dex is unreachable
    or answers 5xx."""
    assert _settings is not None
    metadata = await oauth.oidc.load_server_metadata()
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            metadata["token_endpoint"],
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            auth=(_settings.oauth_client_id, _settings.oauth_client_secret),
        )
    if 400 <= resp.status_code < 500:
        raise DexRefused(resp.text[:200])
    resp.raise_for_status()
    return resp.json().get("refresh_token") or refresh_token


async def _revalidate_at_dex(sub: str) -> str | None:
    """Ask the identity provider whether the user still stands: replay the user's
    shared Dex refresh token and store the rotated one. None (record deleted)
    when the IdP refuses. A sibling session may rotate the shared token while
    we are at Dex, so a refusal is retried once with the token stored now."""
    assert _store is not None and _settings is not None
    rec = await _store.get(DEXRT, sub)
    for _ in range(2):
        if rec is None:
            return None
        try:
            rotated = await _dex_refresh(rec["rt"])
        except DexRefused as exc:
            current = await _store.get(DEXRT, sub)
            if current is not None and current["rt"] != rec["rt"]:
                rec = current
                continue
            logger.info("Identity provider refused the refresh for a user; sessions ended: %s", exc)
            await _store.pop(DEXRT, sub)
            return None
        await _store.put(DEXRT, sub, {"rt": rotated}, ttl=_settings.as_refresh_ttl_seconds)
        return rotated
    await _store.pop(DEXRT, sub)
    return None


@router.post("/oauth/token")
async def token(request: Request) -> JSONResponse:
    assert _store is not None and _settings is not None and _grants is not None
    form = await request.form()
    grant = form.get("grant_type")
    client_id = str(form.get("client_id", ""))
    if grant == "authorization_code":
        rec = await _store.pop("code", str(form.get("code", "")))
        if (
            rec is None
            or rec["client_id"] != client_id
            or not _redirect_matches(rec["redirect_uri"], str(form.get("redirect_uri", "")))
            or not _pkce_ok(rec["code_challenge"], str(form.get("code_verifier", "")))
        ):
            return _error(400, "invalid_grant")
        return await _issue(rec["sub"], client_id, rec["scope"])
    if grant == "refresh_token":
        presented = str(form.get("refresh_token", ""))
        rec = await _store.get("refresh", presented)
        if rec is None or rec["client_id"] != client_id:
            return _error(400, "invalid_grant")
        # The identity provider first: only a user Dex still honours gets a new
        # pair. A refusal ends every session of the user (the Dex token is gone,
        # so siblings fail their next refresh without asking Dex) and the client
        # goes back to login, where the IdP says no. Dex unreachable is a 503
        # and the presented token stays valid.
        try:
            honoured = await _revalidate_at_dex(rec["sub"])
        except httpx.HTTPError as exc:
            logger.warning("Refresh deferred, identity provider unreachable: %s", exc)
            return _error(503, "temporarily_unavailable", "identity provider unreachable")
        if honoured is None:
            await _store.pop("refresh", presented)
            return _error(400, "invalid_grant", "the identity provider no longer honours this session")
        try:
            alive = await _user_exists(rec["sub"])
        except httpx.HTTPError as exc:
            logger.warning("Refresh deferred, LiteLLM unreachable: %s", exc)
            return _error(503, "temporarily_unavailable")
        consumed = await _store.pop("refresh", presented)
        if consumed is None or consumed["client_id"] != client_id:
            return _error(400, "invalid_grant")
        if not alive:
            logger.info("Refused a refresh for a user no longer in LiteLLM")
            return _error(400, "invalid_grant")
        # Re-derived on every refresh: a revoked grant drops off within one access-token TTL.
        scopes = await _grants.scopes_for(
            consumed["sub"], consumed["scope"].split(), _settings.as_audience
        )
        return await _issue(consumed["sub"], client_id, " ".join(scopes))
    return _error(400, "unsupported_grant_type")
```

Why the front key is NOT revoked on refusal (ach revokes its oauth `pk_`): here the authz resolves `sub → front key` through `/api/internal/front-key`, which self-heals — a revoked key would simply be re-minted on the next request carrying a still-valid JWT. Exposure after an IdP refusal is bounded by `AS_ACCESS_TTL_SECONDS` (default 3600) either way, which is the same bound ach ends up with. Put this sentence as a comment above `if honoured is None:`.

- [ ] **Step 4: Run the whole Python suite and lint**

Run: `cd src/api && .venv/bin/pytest tests/ -q && uvx ruff@0.8.4 check app tests && uvx ruff@0.8.4 format --check app tests`
Expected: all pass (384 before this task + 5 new); ruff clean. If `format --check` complains, run `uvx ruff@0.8.4 format app tests` and re-run.

- [ ] **Step 5: Docs**

`docs/dex-integration.md:22` — after the scopes bullet add:

```markdown
- With the OAuth front door on (`AS_ENABLED=true`) the authorization server's own
  login additionally requests **`offline_access`**: the Dex refresh token it gets
  back is replayed at Dex on every refresh of an AS token, so a user disabled at
  the identity provider is out within one access-token TTL. The connector must
  issue refresh tokens (Google, Microsoft, GitHub and the generic OIDC connector
  do; a Dex `staticPasswords` user does too). A login that comes back without one
  fails at `/oauth/as-callback` with "the identity provider issued no refresh
  token". Dex keeps one refresh token per (user, client) and replaces it on a new
  login, which is why the AS stores it once per user, not per session.
```

`TODO.md` — delete the line `- [ ] Dex → LiteLLM offboarding sync (the refresh-time LiteLLM re-check is a stopgap).` (search for it; it is in the `## Platform / gitops` section restored by the revert). Add under `## Code`:

```markdown
- [ ] Two tools on two machines refreshing in the same second replay the same Dex
  token; the loser retries once with the rotated one (`_revalidate_at_dex`). If
  that ever shows as spurious `invalid_grant`, set Dex `expiry.refreshTokens.reuseInterval`.
```

`CHANGELOG.md`, same `### Fixed` section as Task 1:

```markdown
- AS: every `refresh_token` grant is re-validated at the identity provider. Login
  requests `offline_access`; the Dex refresh token is kept ONCE per user (newest
  login wins — Dex keeps one per user and client) and replayed at Dex before the
  AS rotates its own token. A Dex refusal ends every session of that user
  (`invalid_grant`, the client goes back to login); Dex unreachable is a 503 and
  the presented token stays valid; a login Dex answers without a refresh token
  fails loud. Ported from ach `3194271`, `46a2101`.
```

- [ ] **Step 6: Commit**

```bash
cd "$(git rev-parse --show-toplevel)"
git add src/api/app/oauth_as/routes.py src/api/tests/test_oauth_as_routes.py docs/dex-integration.md TODO.md CHANGELOG.md
git commit -m "fix(oauth-as): re-validate every refresh at the identity provider" -m "The AS rotated its own refresh token for AS_REFRESH_TTL_SECONDS without
ever asking Dex again, so a user disabled at the IdP kept working until the
chain lapsed. Login now requests offline_access and keeps Dex's refresh
token once per user (Dex keeps one per user and client and replaces it on
a new login; a per-session copy stranded the first tool as soon as a second
one signed in). The refresh_token grant replays it at Dex first: a refusal
deletes it and the presented token and answers invalid_grant, so sibling
sessions fail their next refresh without asking Dex; Dex unreachable is a
503 and nothing is consumed; a login without a refresh token fails loud.

Ported from ach 3194271 and 46a2101.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: AS — provisioning failure at `as-callback` is a 503 page, not a stack trace

**Files:**
- Modify: `src/api/app/oauth_as/routes.py` (`as_callback`, the `ensure_team_and_user` call written in Task 2)
- Test: `src/api/tests/test_oauth_as_routes.py`

**Interfaces:**
- Consumes: `app.litellm_client.ensure_team_and_user(email, settings, name=...)` raises `httpx.HTTPError` (subclasses `HTTPStatusError`, `RequestError`) when LiteLLM fails.
- Produces: nothing new.

- [ ] **Step 1: Write the failing test**

After `test_as_callback_fails_loud_when_dex_issues_no_refresh_token` add:

```python
def test_as_callback_renders_a_503_when_litellm_provisioning_fails():
    c = make_client()
    client_id = _register(c)
    with patch("app.oauth_as.routes.oauth") as mock_oauth:
        mock_oauth.oidc.authorize_redirect = AsyncMock(
            return_value=RedirectResponse("http://dex.test/auth", status_code=302)
        )
        c.get("/oauth/authorize", params=_authorize_params(client_id), follow_redirects=False)
        pending_id = mock_oauth.oidc.authorize_redirect.call_args.kwargs["state"]
        mock_oauth.oidc.authorize_access_token = AsyncMock(
            return_value={"userinfo": {"email": "u@x.com"}, "refresh_token": "dex-rt-1"}
        )
        with patch(
            "app.oauth_as.routes.ensure_team_and_user",
            AsyncMock(side_effect=httpx.ConnectError("litellm down")),
        ):
            r = c.get(f"/oauth/as-callback?code=dexcode&state={pending_id}", follow_redirects=False)
    assert r.status_code == 503 and "provisioning" in r.text
    assert asyncio.run(routes._store.get("dexrt", "u@x.com")) is None  # nothing stored for a login that did not happen
    assert asyncio.run(routes._store.get("pending", pending_id)) is None  # burned either way
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd src/api && .venv/bin/pytest tests/test_oauth_as_routes.py::test_as_callback_renders_a_503_when_litellm_provisioning_fails -q`
Expected: FAIL — `assert 500 == 503` (the TestClient is built with `raise_server_exceptions=False`, so the unhandled `ConnectError` surfaces as a 500).

- [ ] **Step 3: Guard the call**

In `as_callback`, replace `await ensure_team_and_user(email, _settings, name=userinfo.get("name"))` with:

```python
    try:
        await ensure_team_and_user(email, _settings, name=userinfo.get("name"))
    except httpx.HTTPError as exc:
        logger.warning("User provisioning failed at as-callback: %s", exc)
        return _html_error(503, "user provisioning failed: LiteLLM is unreachable, try again")
```

- [ ] **Step 4: Run the suite and lint**

Run: `cd src/api && .venv/bin/pytest tests/ -q && uvx ruff@0.8.4 check app tests && uvx ruff@0.8.4 format --check app tests`
Expected: all pass, ruff clean.

- [ ] **Step 5: Commit**

```bash
cd "$(git rev-parse --show-toplevel)"
git add src/api/app/oauth_as/routes.py src/api/tests/test_oauth_as_routes.py
git commit -m "fix(oauth-as): provisioning failure at as-callback is a 503 page" -m "ensure_team_and_user raising at the Dex callback surfaced as a bare 500
with a traceback in the log. It is a LiteLLM outage: say so, 503, and the
user retries from the tool. Ported from ach 12539cd.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: authz — configurable list of inbound credential headers

Requested by the user after Task 1 (2026-09-21). ACH declares its credential slots as a list; here the list was one configurable name (`AUTHZ_INBOUND_HEADER`) plus `x-api-key` hardcoded. No per-header `mode` is needed: the value shape decides (`sk-` → renamed into the outbound header, JWS → verified and mapped), so the chart carries only the names, in precedence order.

**Files:**
- Modify: `authz/config.go` (`InboundHeader string` → `InboundHeaders []string`, env `AUTHZ_INBOUND_HEADERS`)
- Modify: `authz/decide.go` (the slot loop and the 401 body)
- Modify: `authz/main.go:48-49` (log line)
- Modify: `authz/decide_test.go:28-33` (`cfg` var) + new tests
- Create: `authz/config_test.go`
- Modify: `deploy/helm/alitellm-auth/values.yaml:190`, `deploy/helm/alitellm-auth/templates/authz-deployment.yaml:41-42`, `deploy/helm/alitellm-auth/templates/istio-authorizationpolicy.yaml:13` (comment)
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: `Decide(ctx, cfg, path, h, v, r)` from Task 1; `envOr(k, d string) string` in `config.go`.
- Produces: `Config.InboundHeaders []string` (lower-cased, trimmed, in precedence order; default `["x-genai-api-key", "x-api-key"]`); `func splitHeaders(s string) []string`. `Config.InboundHeader` no longer exists.

- [ ] **Step 1: Write the failing tests**

`authz/decide_test.go` — in the `cfg` var replace `InboundHeader:       "x-genai-api-key",` with `InboundHeaders:      []string{"x-genai-api-key", "x-api-key"},`. Then add:

```go
func TestOnlyDeclaredInboundHeadersAreSlots(t *testing.T) {
	// A deployment that declares one slot: x-api-key is then just another
	// header, so a key there is "nothing presented" — 401 on /v1, forwarded
	// untouched on the catch-all.
	one := cfg
	one.InboundHeaders = []string{"x-genai-api-key"}
	h := map[string]string{"x-api-key": "sk-abc"}
	if d := Decide(context.Background(), one, v1, h, fakeVerifier{}, &fakeResolver{}); d.Allow || d.Status != 401 {
		t.Fatalf("undeclared slot on /v1: %+v", d)
	}
	if d := Decide(context.Background(), one, "/health/license", h, fakeVerifier{}, &fakeResolver{}); !d.Allow || len(d.Set) != 0 || contains(d.Remove, "x-api-key") {
		t.Fatalf("undeclared slot on the catch-all: %+v", d)
	}
	if d := Decide(context.Background(), one, v1, map[string]string{}, fakeVerifier{}, &fakeResolver{}); d.Body != `{"error":"unauthorized","error_description":"present a LiteLLM key or a token from the authorization server in x-genai-api-key or Authorization: Bearer"}` {
		t.Fatalf("body names only the declared slots: %s", d.Body)
	}
}

func TestInboundHeaderPrecedenceFollowsTheList(t *testing.T) {
	rev := cfg
	rev.InboundHeaders = []string{"x-api-key", "x-genai-api-key"}
	d := Decide(context.Background(), rev, v1, map[string]string{"x-genai-api-key": "sk-custom", "x-api-key": "sk-anthropic"}, fakeVerifier{}, &fakeResolver{})
	if d.Set["x-litellm-api-key"] != "Bearer sk-anthropic" || !contains(d.Remove, "x-api-key") || contains(d.Remove, "x-genai-api-key") {
		t.Fatalf("precedence: %+v", d)
	}
}
```

Create `authz/config_test.go`:

```go
package main

import (
	"reflect"
	"testing"
)

func TestLoadConfigParsesInboundHeaders(t *testing.T) {
	t.Setenv("AUTHZ_INBOUND_HEADERS", " X-GenAI-Api-Key , x-api-key,, x-custom ")
	got := LoadConfig().InboundHeaders
	want := []string{"x-genai-api-key", "x-api-key", "x-custom"}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}
	t.Setenv("AUTHZ_INBOUND_HEADERS", "")
	if got := LoadConfig().InboundHeaders; !reflect.DeepEqual(got, []string{"x-genai-api-key", "x-api-key"}) {
		t.Fatalf("default: %v", got)
	}
}
```

- [ ] **Step 2: Run the Go gate to verify it fails**

Run: `docker run --rm -v "$PWD/authz:/src" -w /src -e GOPATH=/tmp/gopath golang:1.25-alpine sh -c 'go vet ./... && go test ./...'`
Expected: compile error `unknown field InboundHeaders in struct literal`.

- [ ] **Step 3: Implement**

`authz/config.go` — replace the `InboundHeader` field and its `LoadConfig` line:

```go
	InboundHeaders      []string // the headers an agent may present its credential in, in precedence order
```
```go
		InboundHeaders:      splitHeaders(envOr("AUTHZ_INBOUND_HEADERS", "x-genai-api-key,x-api-key")),
```
and add at the end of the file:

```go
// splitHeaders: "A, b,,c" → ["a", "b", "c"]. Envoy hands ext_authz lower-cased
// names, so the list is lower-cased once here.
func splitHeaders(s string) []string {
	var out []string
	for _, h := range strings.Split(s, ",") {
		if h = strings.ToLower(strings.TrimSpace(h)); h != "" {
			out = append(out, h)
		}
	}
	return out
}
```

`authz/decide.go` — the slot loop header and its comment become:

```go
	// The declared slots, in precedence order. x-api-key is where the Anthropic
	// SDK puts an API key (Claude Code with ANTHROPIC_API_KEY or an apiKeyHelper
	// sends it there, never in Authorization), so it is in the default list.
	// Same two shapes in every slot.
	for _, name := range cfg.InboundHeaders {
```
and the 401 body becomes:

```go
	return deny(401, challenge(cfg, path, ""),
		`{"error":"unauthorized","error_description":"present a LiteLLM key or a token from the authorization server in `+strings.Join(cfg.InboundHeaders, ", ")+` or Authorization: Bearer"}`)
```
Also update the `Decide` doc comment's point 1 from "custom header (or x-api-key) present" to "a declared inbound header present".

`authz/main.go:48-49`:

```go
	log.Printf("authz listening on %s (inbound %v → outbound %s, issuer=%s)",
		cfg.ListenAddr, cfg.InboundHeaders, cfg.OutboundHeader, cfg.Issuer)
```

- [ ] **Step 4: Run the Go gate to verify it passes**

Run: `docker run --rm -v "$PWD/authz:/src" -w /src -e GOPATH=/tmp/gopath golang:1.25-alpine sh -c 'gofmt -l . && go vet ./... && go test ./...'`
Expected: `gofmt -l` prints nothing; `ok  	github.com/ackstorm/alitellm-auth/authz`. (`server_test.go:66` pins the two-slot default body and still matches.)

- [ ] **Step 5: Chart + changelog**

`deploy/helm/alitellm-auth/values.yaml:190` — replace `inboundHeader: "x-genai-api-key"    # what agents send` with:

```yaml
  # Headers an agent may present its credential in, in precedence order. The
  # value shape decides what happens (sk- renamed into outboundHeader, this AS's
  # token verified and mapped); no per-header mode. Every name here must ALSO be
  # in the gitops extensionProvider's includeRequestHeadersInCheck (see
  # templates/istio-authorizationpolicy.yaml) or Envoy never hands it to authz.
  inboundHeaders: ["x-genai-api-key", "x-api-key"]
```

`deploy/helm/alitellm-auth/templates/authz-deployment.yaml:41-42`:

```yaml
            - name: AUTHZ_INBOUND_HEADERS
              value: {{ join "," .Values.authz.inboundHeaders | quote }}
```

`deploy/helm/alitellm-auth/templates/istio-authorizationpolicy.yaml:13` (a comment) — replace `"{{ .Values.authz.inboundHeader }}", "x-api-key"` with `{{ range .Values.authz.inboundHeaders }}"{{ . }}", {{ end }}` so the rendered note lists the declared slots.

`CHANGELOG.md`, under `## [unreleased]` add `### Changed` (create it if absent) with:

```markdown
- authz: the inbound credential headers are a list — `authz.inboundHeaders`
  (default `["x-genai-api-key", "x-api-key"]`, precedence order) rendered to
  `AUTHZ_INBOUND_HEADERS`; `authz.inboundHeader` / `AUTHZ_INBOUND_HEADER` are
  gone. Only declared names are credential slots; the value shape still decides
  what happens with it.
```

Run: `helm template t deploy/helm/alitellm-auth --set authServer.enabled=true --set authz.enabled=true --set istio.enabled=true --set istio.gateway.name=gw | grep -A1 AUTHZ_INBOUND_HEADERS`
Expected: `value: "x-genai-api-key,x-api-key"`. Then `grep -rn -i 'inboundHeader\b\|AUTHZ_INBOUND_HEADER\b' authz deploy` → nothing.

- [ ] **Step 6: Commit**

```bash
git add authz/ deploy/helm/alitellm-auth/values.yaml deploy/helm/alitellm-auth/templates/authz-deployment.yaml deploy/helm/alitellm-auth/templates/istio-authorizationpolicy.yaml CHANGELOG.md
git commit -m "feat(authz): inbound credential headers are a configurable list" -m "One configurable slot plus a hardcoded x-api-key becomes
AUTHZ_INBOUND_HEADERS (chart authz.inboundHeaders), in precedence order.
No per-header mode: the value shape decides. A name not in the list is
not a slot, so a key there is nothing presented.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Final gate (once, after Task 4)

- [ ] Go: `docker run --rm -v "$PWD/authz:/src" -w /src -e GOPATH=/tmp/gopath golang:1.25-alpine sh -c 'gofmt -l . && go vet ./... && go test ./...'` → `ok`.
- [ ] Python: `cd src/api && .venv/bin/pytest tests/ -q` → 0 failures; `uvx ruff@0.8.4 check app tests && uvx ruff@0.8.4 format --check app tests` → clean.
- [ ] Chart: `helm lint deploy/helm/alitellm-auth` and the `helm template … --set authz.enabled=true …` line from Global Constraints render; `grep -rn -i 'LEGACY_PASSTHROUGH\|inboundHeader\b' deploy authz` → nothing.
- [ ] One review of the three commits together (`git diff 4e38245..HEAD`), not one per task.
- [ ] Live check the deployer must do before cutting a release (not automatable here): with the front door enabled on a cluster, `curl -si https://api.<domain>/health/license` returns LiteLLM's answer (not a 401 with `WWW-Authenticate`), `curl -si https://api.<domain>/v1/models` returns `401` + `WWW-Authenticate: Bearer resource_metadata=…`, and a real `ackstorm-token` login followed by a second login from another tool leaves the first tool able to refresh.
