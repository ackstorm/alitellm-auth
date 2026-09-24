# SPDX-License-Identifier: Apache-2.0
import asyncio
import base64
import hashlib
import json
import re
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx
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
    assert metadata["authorization_response_iss_parameter_supported"] is True
    assert metadata["grant_types_supported"] == [
        "authorization_code",
        "refresh_token",
        "urn:ietf:params:oauth:grant-type:device_code",
    ]
    assert (
        metadata["device_authorization_endpoint"]
        == "https://platform.test/oauth/device_authorization"
    )
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
    c = make_client(make_settings(as_services=json.dumps(SERVICES)))
    response = c.get("/.well-known/oauth-protected-resource/mcp/mcp-aws-eks-ro")
    assert response.status_code == 200
    document = response.json()
    assert document["resource"] == "https://api.test/mcp/mcp-aws-eks-ro"
    assert document["authorization_servers"] == ["https://platform.test"]
    assert document["scopes_supported"] == ["alitellm", "mcp-aws-eks-ro"]
    assert document["bearer_methods_supported"] == ["header"]
    # A path segment that is not a registered service advertises no scope for it.
    # It still gets a 200 document ON PURPOSE: before authentication a real and
    # an unknown MCP server must look identical, or this route becomes an
    # anonymous oracle for which servers exist (accepted 2026-09-23).
    unknown = c.get("/.well-known/oauth-protected-resource/mcp/mcp-nope").json()
    assert unknown["scopes_supported"] == ["alitellm"]


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
    assert body["grant_types"] == [
        "authorization_code",
        "refresh_token",
        "urn:ietf:params:oauth:grant-type:device_code",
    ]


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
    # offline_access: Dex hands back a refresh token the AS replays at every
    # refresh of ours, so a user disabled at the IdP is out within one access TTL.
    assert kwargs["scope"] == "openid email profile offline_access"


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
    assert "iss=https%3A%2F%2Fplatform.test" in location  # RFC 9207, on errors too


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
            return_value={
                "userinfo": {"email": " U@X.COM ", "name": "U"},
                "refresh_token": "dex-rt-1",
            }
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
    assert "iss=https%3A%2F%2Fplatform.test" in location  # RFC 9207
    ensure.assert_awaited_once()
    assert ensure.await_args.args[0] == "u@x.com"
    code = location.partition("code=")[2].partition("&")[0]
    assert asyncio.run(routes._store.get("code", code))["sub"] == "u@x.com"
    assert asyncio.run(routes._store.get("dexrt", "u@x.com")) == {"rt": "dex-rt-1"}


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
    # Dex already rotated the user's token at the code exchange: it is stored even
    # though LiteLLM provisioning failed, or the user's other tools would die.
    assert asyncio.run(routes._store.get("dexrt", "u@x.com")) == {"rt": "dex-rt-1"}
    assert asyncio.run(routes._store.get("pending", pending_id)) is None  # burned either way


def test_as_callback_does_not_call_a_litellm_rejection_unreachable():
    """LiteLLM answering 4xx is a provisioning bug, not an outage: no "try again"."""
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
        req = httpx.Request("POST", "http://litellm.test/team/member_add")
        rejected = httpx.HTTPStatusError(
            "rejected", request=req, response=httpx.Response(400, request=req)
        )
        with patch("app.oauth_as.routes.ensure_team_and_user", AsyncMock(side_effect=rejected)):
            r = c.get(f"/oauth/as-callback?code=dexcode&state={pending_id}", follow_redirects=False)
    assert r.status_code == 502 and "(400)" in r.text
    assert "unreachable" not in r.text


BROKER = "https://api.test/aws-eks-ro-callback"
SERVICES = {"mcp-aws-eks-ro": {"store": "aws-eks-ro", "broker": BROKER}}
GRANTED = {"oauth:aws-eks-ro:state:u@x.com": json.dumps({"granted": True})}


def _query(response) -> dict[str, str]:
    return {k: v[0] for k, v in parse_qs(urlparse(response.headers["location"]).query).items()}


def _login_with(c: TestClient, client_id: str, scope: str):
    """Run /authorize → Dex → /as-callback and return the callback response."""
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
            return_value={"userinfo": {"email": "u@x.com"}, "refresh_token": "dex-rt-1"}
        )
        with patch("app.oauth_as.routes.ensure_team_and_user", AsyncMock(return_value="default")):
            r = c.get(f"/oauth/as-callback?code=dexcode&state={pending_id}", follow_redirects=False)
    assert r.status_code == 302, r.text
    return r


def test_as_callback_passes_the_sso_groups_to_provisioning():
    c = make_client()
    client_id = _register(c)
    with patch("app.oauth_as.routes.oauth") as mock_oauth:
        mock_oauth.oidc.authorize_redirect = AsyncMock(
            return_value=RedirectResponse("http://dex.test/auth", status_code=302)
        )
        c.get("/oauth/authorize", params=_authorize_params(client_id), follow_redirects=False)
        pending_id = mock_oauth.oidc.authorize_redirect.call_args.kwargs["state"]
        mock_oauth.oidc.authorize_access_token = AsyncMock(
            return_value={
                "userinfo": {"email": "u@x.com", "groups": ["aws@x.com"]},
                "refresh_token": "dex-rt-1",
            }
        )
        with patch("app.oauth_as.routes.ensure_team_and_user", AsyncMock()) as ensure:
            c.get(f"/oauth/as-callback?code=dexcode&state={pending_id}", follow_redirects=False)
    assert ensure.await_args.kwargs["sso_groups"] == ["aws@x.com"]


def test_code_carries_the_mcp_scopes_the_user_holds_a_grant_for():
    c = make_client(
        make_settings(as_services=json.dumps(SERVICES)), Grants(FakeRedis(dict(GRANTED)), SERVICES)
    )
    client_id = _register(c)
    code = _query(_login_with(c, client_id, "alitellm mcp-aws-eks-ro"))["code"]
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
    code = _query(_login_with(c, client_id, "alitellm mcp-aws-eks-ro"))["code"]
    first = c.post("/oauth/token", data=_token_form(client_id, code=code)).json()
    assert first["scope"] == "alitellm mcp-aws-eks-ro"
    projection.clear()  # the pod condemned the grant
    with (
        patch("app.oauth_as.routes._dex_refresh", AsyncMock(return_value="dex-rt-2")),
        patch("app.oauth_as.routes._user_exists", AsyncMock(return_value=True)),
    ):
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


@respx.mock
def test_a_missing_grant_sends_the_user_to_the_service_broker_then_back():
    fake = FakeRedis({})
    c = make_client(make_settings(as_services=json.dumps(SERVICES)), Grants(fake, SERVICES))
    client_id = _register(c)
    reg = respx.post(f"{BROKER}/register").respond(201, json={"client_id": "front-at-broker"})
    r = _login_with(c, client_id, "alitellm mcp-aws-eks-ro")
    # off to the broker, with PKCE, our callback, and the chain id as state
    assert r.headers["location"].startswith(f"{BROKER}/authorize?")
    q = _query(r)
    assert q["client_id"] == "front-at-broker"
    assert q["code_challenge_method"] == "S256" and len(q["code_challenge"]) == 43
    assert q["scope"] == "aws-eks-ro"
    assert q["redirect_uri"] == "https://platform.test/oauth/broker-callback"
    assert reg.called
    # and who the ceremony is for, said by us: the broker keys the grant by this
    # rather than by whatever account gets picked at the provider
    hint = _jwt.decode(q["login_hint"], routes._signer.jwks()["keys"][0])
    assert hint["sub"] == "u@x.com" and hint["aud"] == "aws-eks-ro"
    assert hint["iss"] == "https://platform.test" and hint["exp"] - hint["iat"] == routes.HINT_TTL
    assert len(hint["jti"]) >= 16  # the broker spends it on first use
    chain_id = q["state"]
    # the broker stored the grant during its consent; the projection now says so
    fake.data["oauth:aws-eks-ro:state:u@x.com"] = json.dumps({"granted": True})
    r = c.get(f"/oauth/broker-callback?code=brokercode&state={chain_id}", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].startswith("http://127.0.0.1:5000/cb?")
    q = _query(r)
    assert q["state"] == "xyz"
    assert asyncio.run(routes._store.get("code", q["code"]))["scope"] == "alitellm mcp-aws-eks-ro"
    # the chain id was single-use
    r = c.get(f"/oauth/broker-callback?code=brokercode&state={chain_id}", follow_redirects=False)
    assert r.status_code == 400


@respx.mock
def test_broker_registration_is_cached_per_broker():
    c = make_client(
        make_settings(as_services=json.dumps(SERVICES)), Grants(FakeRedis({}), SERVICES)
    )
    reg = respx.post(f"{BROKER}/register").respond(201, json={"client_id": "front-at-broker"})
    for _ in range(2):
        _login_with(c, _register(c), "alitellm mcp-aws-eks-ro")
    assert reg.call_count == 1


@respx.mock
def test_an_unreachable_broker_finishes_without_the_scope():
    c = make_client(
        make_settings(as_services=json.dumps(SERVICES)), Grants(FakeRedis({}), SERVICES)
    )
    respx.post(f"{BROKER}/register").mock(side_effect=httpx.ConnectError("down"))
    r = _login_with(c, _register(c), "alitellm mcp-aws-eks-ro")
    assert r.headers["location"].startswith("http://127.0.0.1:5000/cb?")
    assert asyncio.run(routes._store.get("code", _query(r)["code"]))["scope"] == "alitellm"


def test_broker_error_finishes_without_the_scope():
    """The user declined at the provider: the client still gets its token, without that service."""
    c = make_client(
        make_settings(as_services=json.dumps(SERVICES)), Grants(FakeRedis({}), SERVICES)
    )
    asyncio.run(
        routes._store.put(
            "chain",
            "ch1",
            {
                "client_id": "c",
                "redirect_uri": "http://127.0.0.1:5000/cb",
                "state": "s",
                "code_challenge": CHALLENGE,
                "scopes": ["alitellm", "mcp-aws-eks-ro"],
                "sub": "u@x.com",
                "todo": ["mcp-aws-eks-ro"],
                "verifier": "v",
            },
            ttl=600,
        )
    )
    r = c.get("/oauth/broker-callback?error=access_denied&state=ch1", follow_redirects=False)
    assert r.status_code == 302
    assert asyncio.run(routes._store.get("code", _query(r)["code"]))["scope"] == "alitellm"


def test_broker_callback_without_a_chain_is_a_400():
    r = make_client().get("/oauth/broker-callback?code=x&state=nope", follow_redirects=False)
    assert r.status_code == 400


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
            return_value={"userinfo": {"email": "u@x.com"}, "refresh_token": "dex-rt-1"}
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
            AsyncMock(return_value={"userinfo": {"email": "u@x.com"}, "refresh_token": "dex-rt-1"}),
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
    with (
        patch("app.oauth_as.routes._dex_refresh", AsyncMock(return_value="dex-rt-2")),
        patch("app.oauth_as.routes._user_exists", AsyncMock(return_value=True)),
    ):
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
        assert asyncio.run(routes._store.get("dexrt", "u@x.com")) == {"rt": "dex-rt-2"}
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
    with (
        patch("app.oauth_as.routes._dex_refresh", AsyncMock(return_value="dex-rt-2")),
        patch("app.oauth_as.routes._user_exists", AsyncMock(return_value=False)),
    ):
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
    with (
        patch("app.oauth_as.routes._dex_refresh", AsyncMock(return_value="dex-rt-2")),
        patch(
            "app.oauth_as.routes._user_exists", AsyncMock(side_effect=httpx.ConnectError("down"))
        ),
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
    with (
        patch("app.oauth_as.routes._dex_refresh", AsyncMock(return_value="dex-rt-2")) as dex,
        patch("app.oauth_as.routes._user_exists", AsyncMock(return_value=True)) as exists,
    ):
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
    dex.assert_not_awaited()
    assert asyncio.run(routes._store.get("refresh", first["refresh_token"])) is not None


def _refresh(c: TestClient, client_id: str, refresh_token: str):
    return c.post(
        "/oauth/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        },
    )


def test_refresh_refused_by_the_idp_ends_every_session_of_the_user():
    c = make_client()
    client_id = _register(c)
    _seed_code(client_id)
    first = c.post("/oauth/token", data=_token_form(client_id)).json()
    _seed_code(client_id, code="second")
    sibling = c.post("/oauth/token", data=_token_form(client_id, code="second")).json()
    with (
        patch(
            "app.oauth_as.routes._dex_refresh",
            AsyncMock(side_effect=routes.DexRefused("invalid_grant")),
        ) as dex,
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
    with patch(
        "app.oauth_as.routes._dex_refresh", AsyncMock(side_effect=httpx.ConnectError("down"))
    ):
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
        endpoint.mock(
            return_value=httpx.Response(
                200, json={"access_token": "a", "refresh_token": "dex-rt-2"}
            )
        )
        assert asyncio.run(routes._dex_refresh("dex-rt-1")) == "dex-rt-2"
        sent = endpoint.calls.last.request
        assert (
            b"grant_type=refresh_token" in sent.content
            and b"refresh_token=dex-rt-1" in sent.content
        )
        assert sent.headers["authorization"].startswith("Basic ")
        # Dex may answer without rotating: the presented token stays valid.
        endpoint.mock(return_value=httpx.Response(200, json={"access_token": "a"}))
        assert asyncio.run(routes._dex_refresh("dex-rt-1")) == "dex-rt-1"
        endpoint.mock(return_value=httpx.Response(400, json={"error": "invalid_grant"}))
        with pytest.raises(routes.DexRefused):
            asyncio.run(routes._dex_refresh("dex-rt-1"))
        # Not a refusal of the user: a misconfigured client secret or a 5xx is
        # retryable, never the end of every session.
        for status in (401, 403, 502):
            endpoint.mock(return_value=httpx.Response(status))
            with pytest.raises(httpx.HTTPError):
                asyncio.run(routes._dex_refresh("dex-rt-1"))


def test_unsupported_grant_type():
    r = make_client().post("/oauth/token", data={"grant_type": "password"})
    assert r.status_code == 400 and r.json()["error"] == "unsupported_grant_type"


def test_a_callback_from_a_browser_that_did_not_start_the_request_is_refused():
    """Login CSRF / code injection. An attacker starts /authorize server-side for
    his own client and forwards the victim to the Dex URL; Dex sends the victim
    to /as-callback with the attacker's pending id as state. The pending record
    is in Redis, keyed by that state alone — what ties the two browsers together
    is Authlib's session cookie: /authorize stored the state in the session it set
    on the ATTACKER's response, and the victim's browser has no such session, so
    Authlib refuses before any identity is used. The pending record is burned
    either way. Not mocked here: this is the real Authlib check."""
    fake = FakeRedis({})
    c = make_client(make_settings(as_services=json.dumps(SERVICES)), Grants(fake, SERVICES))
    client_id = _register(c)
    with patch("app.oauth_as.routes.oauth") as mock_oauth:
        mock_oauth.oidc.authorize_redirect = AsyncMock(
            return_value=RedirectResponse("http://dex.test/auth", status_code=302)
        )
        r = c.get("/oauth/authorize", params=_authorize_params(client_id), follow_redirects=False)
        assert r.status_code == 302
        pending_id = mock_oauth.oidc.authorize_redirect.call_args.kwargs["state"]

    victim = TestClient(c.app)  # same server, no cookies: a browser that never saw /authorize
    with patch("app.oauth_as.routes.ensure_team_and_user", AsyncMock(return_value="default")):
        r = victim.get(
            f"/oauth/as-callback?code=dexcode&state={pending_id}", follow_redirects=False
        )
    assert r.status_code == 400
    assert "did not complete the login" in r.text
    assert asyncio.run(routes._store.get("pending", pending_id)) is None  # burned
    assert not fake.data or not any(k.startswith("code") for k in fake.data)


# ── RFC 8628 device grant ────────────────────────────────────────────────────

DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
SAME_ORIGIN = {"origin": "https://platform.test"}


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
        r = c.post(
            "/oauth/device",
            data={"user_code": user_code},
            headers={"origin": "https://platform.test"},
            follow_redirects=False,
        )
        assert r.status_code == 302, r.text
        kwargs = mock_oauth.oidc.authorize_redirect.call_args.kwargs
        assert kwargs["scope"] == "openid email profile offline_access"
        pending_id = kwargs["state"]
        assert asyncio.run(routes._store.get("pending", pending_id))["scopes"] == ["alitellm"]
        if dex_fails:
            mock_oauth.oidc.authorize_access_token = AsyncMock(
                side_effect=RuntimeError("access_denied")
            )
        else:
            mock_oauth.oidc.authorize_access_token = AsyncMock(
                return_value={"userinfo": {"email": "u@x.com"}, "refresh_token": "dex-rt-1"}
            )
        with patch("app.oauth_as.routes.ensure_team_and_user", AsyncMock(return_value="default")):
            return c.get(
                f"/oauth/as-callback?code=dexcode&state={pending_id}", follow_redirects=False
            )


def test_device_authorization_issues_a_user_code_and_parks_the_device():
    c = make_client()
    client_id = _register(c)
    da = _device_start(c, client_id)
    assert re.fullmatch(r"[BCDFGHJKLMNPQRSTVWXZ]{4}-[BCDFGHJKLMNPQRSTVWXZ]{4}", da["user_code"])
    assert da["verification_uri"] == "https://platform.test/oauth/device"
    assert (
        da["verification_uri_complete"]
        == f"https://platform.test/oauth/device?user_code={da['user_code']}"
    )
    assert da["expires_in"] == 600 and da["interval"] == 5
    assert asyncio.run(routes._store.get("device", da["device_code"])) == {
        "client_id": client_id,
        "user_code": da["user_code"],
        "status": "pending",
    }
    assert asyncio.run(routes._store.get("device_user", da["user_code"])) == {
        "device_code": da["device_code"]
    }


def test_device_authorization_rejects_an_unknown_client():
    r = make_client().post("/oauth/device_authorization", data={"client_id": "nope"})
    assert r.status_code == 400 and r.json()["error"] == "invalid_client"


def test_device_page_prefills_the_code_and_rejects_an_unknown_one():
    c = make_client()
    r = c.get("/oauth/device?user_code=BCDF-GHJK")
    assert r.status_code == 200 and 'value="BCDF-GHJK"' in r.text and "Confirm" in r.text
    with patch("app.oauth_as.routes.oauth") as mock_oauth:
        r = c.post("/oauth/device", data={"user_code": "BCDF-GHJK"}, headers=SAME_ORIGIN)
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
        r = c.post("/oauth/device", data={"user_code": da["user_code"]}, headers=SAME_ORIGIN)
        mock_oauth.oidc.authorize_redirect.assert_not_called()
    assert r.status_code == 400 and "not found or expired" in r.text


def test_device_page_refuses_a_cross_site_confirmation():
    """RFC 8628 §5.4: an auto-submitting form on another site must not walk a
    victim with a live IdP session into approving an attacker's code."""
    c = make_client()
    da = _device_start(c, _register(c))
    with patch("app.oauth_as.routes.oauth") as mock_oauth:
        for headers in ({}, {"origin": "https://evil.test"}, {"referer": "https://evil.test/x"}):
            r = c.post("/oauth/device", data={"user_code": da["user_code"]}, headers=headers)
            assert r.status_code == 403, headers
        mock_oauth.oidc.authorize_redirect.assert_not_called()
    assert asyncio.run(routes._store.get("device_user", da["user_code"])) is not None
