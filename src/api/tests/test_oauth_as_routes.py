# SPDX-License-Identifier: Apache-2.0
import asyncio
import base64
import hashlib
import json
from unittest.mock import AsyncMock, patch

import httpx
from authlib.jose import jwt as _jwt
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse

from app.config import Settings
from app.oauth_as import routes
from app.oauth_as.grants import Grants
from app.oauth_as.store import MemoryStore
from app.oauth_as.tokens import Signer
from tests.test_oauth_as_grants import FakeRedis
from tests.test_oauth_as_tokens import _pem


VERIFIER = "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk"
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
)


def make_settings(**over) -> Settings:
    kw = dict(
        app_base_url="https://platform.test",
        session_secret_key="test-secret-32-chars-padding-xxxx",
        oauth_issuer_url="http://dex.test/dex",
        oauth_client_id="test-client",
        oauth_client_secret="test-secret",
        litellm_url="http://litellm.test",
        litellm_master_key="sk-test",
        api_public_url="https://api.test",
        as_enabled=True,
        as_redis_url="memory://",
        as_signing_key_pem=_pem(),
        as_key_encryption_key=Fernet.generate_key().decode(),
        internal_token="shh",
        session_https_only=True,
    )
    kw.update(over)
    return Settings(**kw)


def make_client(settings: Settings | None = None, grants: Grants | None = None) -> TestClient:
    """A bare app with only the AS router — no Dex wiring, no SPA mount."""
    settings = settings or make_settings()
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret_key)
    routes.configure_as(
        settings,
        store=MemoryStore(),
        signer=Signer(settings.as_signing_key_pem),
        grants=grants or Grants(FakeRedis({}), {}),
    )
    app.include_router(routes.router)
    return TestClient(app, raise_server_exceptions=False)


def test_as_metadata_names_every_endpoint_under_the_issuer():
    response = make_client().get("/.well-known/oauth-authorization-server")
    assert response.status_code == 200
    metadata = response.json()
    assert metadata["issuer"] == "https://platform.test"
    assert metadata["authorization_endpoint"] == "https://platform.test/oauth/authorize"
    assert metadata["token_endpoint"] == "https://platform.test/oauth/token"
    assert metadata["registration_endpoint"] == "https://platform.test/oauth/register"
    assert metadata["jwks_uri"] == "https://platform.test/oauth/jwks.json"
    assert metadata["code_challenge_methods_supported"] == ["S256"]
    assert metadata["grant_types_supported"] == ["authorization_code", "refresh_token"]
    assert metadata["token_endpoint_auth_methods_supported"] == ["none"]


def test_jwks_is_served():
    response = make_client().get("/oauth/jwks.json")
    assert response.status_code == 200
    assert response.json()["keys"][0]["kty"] == "RSA"


def test_protected_resource_document_names_the_api_and_this_as():
    response = make_client().get("/.well-known/oauth-protected-resource")
    assert response.status_code == 200
    document = response.json()
    assert document["resource"] == "https://api.test"
    assert document["authorization_servers"] == ["https://platform.test"]
    assert document["scopes_supported"] == ["alitellm"]
    assert document["bearer_methods_supported"] == ["header"]


def test_protected_resource_document_exists_for_every_mcp_path():
    response = make_client().get("/.well-known/oauth-protected-resource/mcp/mcp-aws-eks-ro")
    assert response.status_code == 200
    document = response.json()
    assert document["resource"] == "https://api.test/mcp/mcp-aws-eks-ro"
    assert document["authorization_servers"] == ["https://platform.test"]
    assert document["scopes_supported"] == ["alitellm", "mcp-aws-eks-ro"]
    assert document["bearer_methods_supported"] == ["header"]


def test_register_accepts_a_public_client_with_loopback_and_https_redirects():
    response = make_client().post(
        "/oauth/register",
        json={
            "client_name": "opencode",
            "redirect_uris": ["http://127.0.0.1:19876/callback", "https://app.example/cb"],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["client_id"]
    assert body["token_endpoint_auth_method"] == "none"
    assert body["redirect_uris"] == ["http://127.0.0.1:19876/callback", "https://app.example/cb"]
    assert body["grant_types"] == ["authorization_code", "refresh_token"]


def test_register_rejects_plain_http_off_loopback():
    response = make_client().post(
        "/oauth/register", json={"redirect_uris": ["http://evil.example/cb"]}
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


def test_register_rejects_confidential_clients_and_missing_redirects():
    client = make_client()
    response = client.post(
        "/oauth/register",
        json={
            "redirect_uris": ["https://a/cb"],
            "token_endpoint_auth_method": "client_secret_basic",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"

    response = client.post("/oauth/register", json={"client_name": "x"})
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


def test_register_rejects_non_object_json_and_malformed_redirect_uri():
    client = make_client()
    response = client.post("/oauth/register", json=["https://app.example/cb"])
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"

    response = client.post(
        "/oauth/register", content="{", headers={"content-type": "application/json"}
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client_metadata"

    response = client.post("/oauth/register", json={"redirect_uris": ["http://[::1/cb"]})
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_redirect_uri"


def test_register_rejects_invalid_ports_fragments_and_userinfo():
    client = make_client()
    for uri in (
        "https://app.example:bad/cb",
        "https://app.example:65536/cb",
        "http://127.0.0.1:bad/cb",
        "http://127.0.0.1:65536/cb",
        "https://app.example/cb#fragment",
        "https://user@app.example/cb",
        "http://user@127.0.0.1:1234/cb",
    ):
        response = client.post("/oauth/register", json={"redirect_uris": [uri]})
        assert response.status_code == 400, uri
        assert response.json()["error"] == "invalid_redirect_uri", uri


def test_redirect_matches_exactly_except_loopback_port():
    matches = routes._redirect_matches
    assert matches("https://app.example/cb", "https://app.example/cb")
    assert not matches("https://app.example/cb", "https://app.example:443/cb")
    assert matches("http://127.0.0.1:1000/cb?state=x", "http://127.0.0.1:2000/cb?state=x")
    assert not matches("http://127.0.0.1:1000/cb?state=x", "http://127.0.0.1:2000/cb?state=y")
    assert not matches("http://127.0.0.1:1000/cb;one", "http://127.0.0.1:2000/cb;two")
    assert not matches("http://127.0.0.1:1000/cb", "http://localhost:2000/cb")


async def test_registrations_expire_after_client_ttl(monkeypatch):
    import app.oauth_as.store as store

    now = [1000.0]
    monkeypatch.setattr(store.time, "time", lambda: now[0])
    client = make_client()
    client_id = _register(client)
    assert await routes._store.get("client", client_id) is not None

    now[0] += routes.CLIENT_TTL + 1
    assert await routes._store.get("client", client_id) is None


def _authorize_params(client_id: str, **over) -> dict:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": "http://127.0.0.1:5000/cb",
        "state": "xyz",
        "code_challenge": "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM",
        "code_challenge_method": "S256",
        "scope": "alitellm",
    }
    params.update(over)
    return params


def _register(c: TestClient, uri="http://127.0.0.1:5000/cb") -> str:
    return c.post("/oauth/register", json={"redirect_uris": [uri]}).json()["client_id"]


def test_authorize_stores_request_and_redirects_to_dex_with_https_callback():
    from unittest.mock import AsyncMock, patch

    c = make_client()
    client_id = _register(c)
    with patch("app.oauth_as.routes.oauth") as mock_oauth:
        mock_oauth.oidc.authorize_redirect = AsyncMock(
            return_value=RedirectResponse("http://dex.test/dex/auth?x=1", status_code=302)
        )
        response = c.get(
            "/oauth/authorize", params=_authorize_params(client_id), follow_redirects=False
        )
    assert response.status_code == 302
    assert response.headers["location"].startswith("http://dex.test/dex/auth")
    args, kwargs = mock_oauth.oidc.authorize_redirect.call_args
    assert args[1] == "https://platform.test/oauth/as-callback"
    assert kwargs["state"]


async def test_authorize_refreshes_the_client_registration_ttl(monkeypatch):
    import app.oauth_as.store as store

    now = [1000.0]
    monkeypatch.setattr(store.time, "time", lambda: now[0])
    client = make_client()
    client_id = _register(client)
    now[0] += routes.CLIENT_TTL - 10
    with patch("app.oauth_as.routes.oauth") as mock_oauth:
        mock_oauth.oidc.authorize_redirect = AsyncMock(
            return_value=RedirectResponse("http://dex.test/auth", status_code=302)
        )
        response = client.get(
            "/oauth/authorize",
            params=_authorize_params(client_id),
            follow_redirects=False,
        )
    assert response.status_code == 302

    now[0] += 20  # past the original expiry, inside the refreshed expiry
    assert await routes._store.get("client", client_id) is not None


def test_authorize_never_redirects_to_an_unregistered_uri():
    c = make_client()
    client_id = _register(c)
    response = c.get(
        "/oauth/authorize",
        params=_authorize_params(client_id, redirect_uri="https://evil.example/cb"),
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "location" not in response.headers


def test_authorize_unsupported_scope_redirects_with_invalid_scope_and_state():
    c = make_client()
    client_id = _register(c)
    response = c.get(
        "/oauth/authorize",
        params=_authorize_params(client_id, scope="openid profile", state="keep-me"),
        follow_redirects=False,
    )
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("http://127.0.0.1:5000/cb?")
    assert "error=invalid_scope" in location and "state=keep-me" in location


def test_authorize_missing_scope_defaults_to_configured_audience():
    from unittest.mock import AsyncMock, patch

    c = make_client()
    client_id = _register(c)
    params = _authorize_params(client_id)
    params.pop("scope")
    with patch("app.oauth_as.routes.oauth") as mock_oauth:
        mock_oauth.oidc.authorize_redirect = AsyncMock(
            return_value=RedirectResponse("http://dex.test/auth", status_code=302)
        )
        response = c.get("/oauth/authorize", params=params, follow_redirects=False)
    assert response.status_code == 302
    pending_id = mock_oauth.oidc.authorize_redirect.call_args.kwargs["state"]
    pending = asyncio.run(routes._store.get("pending", pending_id))
    assert pending["scopes"] == ["alitellm"]


def test_authorize_without_pkce_redirects_back_with_invalid_request():
    c = make_client()
    client_id = _register(c)
    params = _authorize_params(client_id)
    del params["code_challenge"]
    response = c.get("/oauth/authorize", params=params, follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("http://127.0.0.1:5000/cb?")
    assert "error=invalid_request" in location and "state=xyz" in location


def test_authorize_rejects_malformed_pkce_challenges_and_preserves_state():
    c = make_client()
    client_id = _register(c)
    for challenge in ("short", "a" * 42, "a" * 44, "a" * 42 + "!"):
        response = c.get(
            "/oauth/authorize",
            params=_authorize_params(client_id, code_challenge=challenge, state="keep-me"),
            follow_redirects=False,
        )
        assert response.status_code == 302
        location = response.headers["location"]
        assert "error=invalid_request" in location
        assert "state=keep-me" in location


def test_as_callback_mints_code_returns_to_client_and_eagerly_creates_user():
    from unittest.mock import AsyncMock, patch

    c = make_client()
    client_id = _register(c)
    with patch("app.oauth_as.routes.oauth") as mock_oauth:
        mock_oauth.oidc.authorize_redirect = AsyncMock(
            return_value=RedirectResponse("http://dex.test/auth", status_code=302)
        )
        c.get("/oauth/authorize", params=_authorize_params(client_id), follow_redirects=False)
        pending_id = mock_oauth.oidc.authorize_redirect.call_args.kwargs["state"]
        mock_oauth.oidc.authorize_access_token = AsyncMock(
            return_value={"userinfo": {"email": " U@X.COM ", "name": "U"}}
        )
        with patch(
            "app.oauth_as.routes.ensure_team_and_user", AsyncMock(return_value="default")
        ) as ensure:
            response = c.get(
                f"/oauth/as-callback?code=dexcode&state={pending_id}", follow_redirects=False
            )
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("http://127.0.0.1:5000/cb?")
    assert "code=" in location and "state=xyz" in location
    ensure.assert_awaited_once()
    assert ensure.await_args.args[0] == "u@x.com"
    code = location.partition("code=")[2].partition("&")[0]
    assert asyncio.run(routes._store.get("code", code))["sub"] == "u@x.com"


SERVICES = {"mcp-aws-eks-ro": {"store": "aws-eks-ro", "broker": "https://b"}}
GRANTED = {"oauth:aws-eks-ro:state:u@x.com": json.dumps({"granted": True})}


def _login_with(c: TestClient, client_id: str, scope: str) -> str:
    """Run /authorize → Dex → /as-callback and return the minted code."""
    with patch("app.oauth_as.routes.oauth") as mock_oauth:
        mock_oauth.oidc.authorize_redirect = AsyncMock(
            return_value=RedirectResponse("http://dex.test/auth", status_code=302)
        )
        r = c.get(
            "/oauth/authorize",
            params=_authorize_params(client_id, scope=scope),
            follow_redirects=False,
        )
        assert r.status_code == 302, r.text
        pending_id = mock_oauth.oidc.authorize_redirect.call_args.kwargs["state"]
        mock_oauth.oidc.authorize_access_token = AsyncMock(
            return_value={"userinfo": {"email": "u@x.com"}}
        )
        with patch("app.oauth_as.routes.ensure_team_and_user", AsyncMock(return_value="default")):
            r = c.get(f"/oauth/as-callback?code=dexcode&state={pending_id}", follow_redirects=False)
    assert r.status_code == 302, r.text
    return r.headers["location"].partition("code=")[2].partition("&")[0]


def test_code_carries_the_mcp_scopes_the_user_holds_a_grant_for():
    c = make_client(
        make_settings(as_services=json.dumps(SERVICES)), Grants(FakeRedis(dict(GRANTED)), SERVICES)
    )
    client_id = _register(c)
    code = _login_with(c, client_id, "alitellm mcp-aws-eks-ro")
    assert asyncio.run(routes._store.get("code", code))["scope"] == "alitellm mcp-aws-eks-ro"


def test_authorize_rejects_a_scope_outside_the_service_registry():
    c = make_client(make_settings(as_services=json.dumps(SERVICES)))
    client_id = _register(c)
    r = c.get(
        "/oauth/authorize",
        params=_authorize_params(client_id, scope="alitellm mcp-google-drive"),
        follow_redirects=False,
    )
    assert r.status_code == 302
    location = r.headers["location"]
    assert "error=invalid_scope" in location and "mcp-google-drive" in location


def test_refresh_drops_a_scope_whose_grant_was_revoked():
    projection = dict(GRANTED)
    c = make_client(
        make_settings(as_services=json.dumps(SERVICES)), Grants(FakeRedis(projection), SERVICES)
    )
    client_id = _register(c)
    code = _login_with(c, client_id, "alitellm mcp-aws-eks-ro")
    first = c.post("/oauth/token", data=_token_form(client_id, code=code)).json()
    assert first["scope"] == "alitellm mcp-aws-eks-ro"
    projection.clear()  # the pod condemned the grant
    with patch("app.oauth_as.routes._user_exists", AsyncMock(return_value=True)):
        r = c.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": first["refresh_token"],
                "client_id": client_id,
            },
        )
    assert r.status_code == 200
    assert r.json()["scope"] == "alitellm"
    claims = _jwt.decode(r.json()["access_token"], routes._signer.jwks())
    assert claims["scope"] == "alitellm"


def test_as_callback_without_pending_request_is_a_400():
    response = make_client().get("/oauth/as-callback?code=x&state=y", follow_redirects=False)
    assert response.status_code == 400


def test_concurrent_authorization_requests_keep_independent_states():
    c = make_client()
    client_id = _register(c)
    with patch("app.oauth_as.routes.oauth") as mock_oauth:
        mock_oauth.oidc.authorize_redirect = AsyncMock(
            return_value=RedirectResponse("http://dex.test/auth", status_code=302)
        )
        c.get("/oauth/authorize", params=_authorize_params(client_id), follow_redirects=False)
        first_state = mock_oauth.oidc.authorize_redirect.call_args.kwargs["state"]
        c.get(
            "/oauth/authorize",
            params=_authorize_params(client_id, state="second"),
            follow_redirects=False,
        )
        second_state = mock_oauth.oidc.authorize_redirect.call_args.kwargs["state"]
        assert first_state != second_state

        mock_oauth.oidc.authorize_access_token = AsyncMock(
            return_value={"userinfo": {"email": "u@x.com"}}
        )
        with patch("app.oauth_as.routes.ensure_team_and_user", AsyncMock(return_value="default")):
            first = c.get(
                f"/oauth/as-callback?code=one&state={first_state}", follow_redirects=False
            )
            second = c.get(
                f"/oauth/as-callback?code=two&state={second_state}", follow_redirects=False
            )

    assert first.status_code == second.status_code == 302
    assert "state=xyz" in first.headers["location"]
    assert "state=second" in second.headers["location"]


def test_authlib_preserves_first_saved_state_after_a_second_real_authorize_redirect():
    from urllib.parse import parse_qs, urlparse

    from authlib.integrations.starlette_client import OAuth
    from app.auth import ConcurrentStateStarletteIntegration

    real_oauth = OAuth()
    real_oauth.framework_integration_cls = ConcurrentStateStarletteIntegration
    real_oauth.register(
        name="oidc",
        authorize_url="https://dex.test/auth",
        access_token_url="https://dex.test/token",
        client_id="test-client",
        client_secret="test-secret",
    )
    c = make_client()
    with (
        patch("app.oauth_as.routes.oauth", real_oauth),
        patch.object(
            real_oauth.oidc,
            "fetch_access_token",
            AsyncMock(return_value={"userinfo": {"email": "u@x.com"}}),
        ),
        patch("app.oauth_as.routes.ensure_team_and_user", AsyncMock(return_value="default")),
    ):
        client_id = _register(c)
        first = c.get(
            "/oauth/authorize", params=_authorize_params(client_id), follow_redirects=False
        )
        first_state = parse_qs(urlparse(first.headers["location"]).query)["state"][0]
        second = c.get(
            "/oauth/authorize",
            params=_authorize_params(client_id, state="second"),
            follow_redirects=False,
        )
        second_state = parse_qs(urlparse(second.headers["location"]).query)["state"][0]
        assert first_state != second_state

        callback = c.get(
            f"/oauth/as-callback?code=first-code&state={first_state}", follow_redirects=False
        )

    assert callback.status_code == 302
    assert "state=xyz" in callback.headers["location"]


def _seed_code(client_id: str, code="thecode") -> None:
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


def _token_form(client_id: str, **over) -> dict:
    f = {
        "grant_type": "authorization_code",
        "code": "thecode",
        "client_id": client_id,
        "redirect_uri": "http://127.0.0.1:5000/cb",
        "code_verifier": VERIFIER,
    }
    f.update(over)
    return f


def test_token_exchanges_a_code_for_a_jwt_and_a_refresh_token():
    c = make_client()
    client_id = _register(c)
    _seed_code(client_id)
    r = c.post("/oauth/token", data=_token_form(client_id))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["token_type"] == "Bearer" and body["expires_in"] == 3600 and body["refresh_token"]
    claims = _jwt.decode(body["access_token"], routes._signer.jwks())
    claims.validate()
    assert (
        claims["sub"] == "u@x.com"
        and claims["client_id"] == client_id
        and claims["aud"] == "alitellm"
    )
    assert r.headers["cache-control"] == "no-store"


def test_token_rejects_a_wrong_verifier_and_the_code_is_burned_anyway():
    c = make_client()
    client_id = _register(c)
    _seed_code(client_id)
    r = c.post("/oauth/token", data=_token_form(client_id, code_verifier="wrong"))
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
    r = c.post("/oauth/token", data=_token_form(client_id))
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"


def test_token_rejects_a_code_for_another_client():
    c = make_client()
    a, b = _register(c), _register(c)
    _seed_code(a)
    r = c.post("/oauth/token", data=_token_form(b))
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"


def test_token_rejects_verifiers_outside_rfc7636_syntax():
    c = make_client()
    client_id = _register(c)
    for verifier in ("a" * 42, "a" * 129, "a" * 42 + " ", "a" * 42 + "+"):
        _seed_code(client_id)
        r = c.post("/oauth/token", data=_token_form(client_id, code_verifier=verifier))
        assert r.status_code == 400 and r.json()["error"] == "invalid_grant"


def test_refresh_rotates_and_the_old_token_dies():
    c = make_client()
    client_id = _register(c)
    _seed_code(client_id)
    first = c.post("/oauth/token", data=_token_form(client_id)).json()
    with patch("app.oauth_as.routes._user_exists", AsyncMock(return_value=True)):
        r = c.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": first["refresh_token"],
                "client_id": client_id,
            },
        )
        assert r.status_code == 200
        second = r.json()
        assert second["refresh_token"] != first["refresh_token"]
        r = c.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": first["refresh_token"],
                "client_id": client_id,
            },
        )
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"


def test_refresh_for_an_offboarded_user_consumes_token_without_replacement():
    c = make_client()
    client_id = _register(c)
    _seed_code(client_id)
    first = c.post("/oauth/token", data=_token_form(client_id)).json()
    with patch("app.oauth_as.routes._user_exists", AsyncMock(return_value=False)):
        r = c.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": first["refresh_token"],
                "client_id": client_id,
            },
        )
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
    assert asyncio.run(routes._store.get("refresh", first["refresh_token"])) is None


def test_refresh_litellm_outage_preserves_refresh_token():
    c = make_client()
    client_id = _register(c)
    _seed_code(client_id)
    first = c.post("/oauth/token", data=_token_form(client_id)).json()
    with patch(
        "app.oauth_as.routes._user_exists", AsyncMock(side_effect=httpx.ConnectError("down"))
    ):
        r = c.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": first["refresh_token"],
                "client_id": client_id,
            },
        )
    assert r.status_code == 503 and r.json()["error"] == "temporarily_unavailable"
    assert asyncio.run(routes._store.get("refresh", first["refresh_token"])) is not None


def test_wrong_client_refresh_does_not_consume_token():
    c = make_client()
    client_id, other_id = _register(c), _register(c)
    _seed_code(client_id)
    first = c.post("/oauth/token", data=_token_form(client_id)).json()
    with patch("app.oauth_as.routes._user_exists", AsyncMock(return_value=True)) as exists:
        r = c.post(
            "/oauth/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": first["refresh_token"],
                "client_id": other_id,
            },
        )
    assert r.status_code == 400 and r.json()["error"] == "invalid_grant"
    exists.assert_not_awaited()
    assert asyncio.run(routes._store.get("refresh", first["refresh_token"])) is not None


def test_unsupported_grant_type():
    r = make_client().post("/oauth/token", data={"grant_type": "password"})
    assert r.status_code == 400 and r.json()["error"] == "unsupported_grant_type"
