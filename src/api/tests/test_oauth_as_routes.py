# SPDX-License-Identifier: Apache-2.0
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse

from app.config import Settings
from app.oauth_as import routes
from app.oauth_as.store import MemoryStore
from app.oauth_as.tokens import Signer
from tests.test_oauth_as_tokens import _pem


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
        as_signing_key_pem=_pem(),
        as_key_encryption_key=Fernet.generate_key().decode(),
        session_https_only=True,
    )
    kw.update(over)
    return Settings(**kw)


def make_client(settings: Settings | None = None) -> TestClient:
    """A bare app with only the AS router — no Dex wiring, no SPA mount."""
    settings = settings or make_settings()
    app = FastAPI()
    app.add_middleware(SessionMiddleware, secret_key=settings.session_secret_key)
    routes.configure_as(settings, store=MemoryStore(), signer=Signer(settings.as_signing_key_pem))
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
        response = c.get("/oauth/authorize", params=_authorize_params(client_id), follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"].startswith("http://dex.test/dex/auth")
    args, _ = mock_oauth.oidc.authorize_redirect.call_args
    assert args[1] == "https://platform.test/oauth/as-callback"


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
    pending_id = c.cookies.get("session")
    assert pending_id


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
        mock_oauth.oidc.authorize_access_token = AsyncMock(
            return_value={"userinfo": {"email": "u@x.com", "name": "U"}}
        )
        with patch("app.oauth_as.routes.ensure_team_and_user", AsyncMock(return_value="default")) as ensure:
            response = c.get("/oauth/as-callback?code=dexcode&state=s", follow_redirects=False)
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("http://127.0.0.1:5000/cb?")
    assert "code=" in location and "state=xyz" in location
    ensure.assert_awaited_once()
    assert ensure.await_args.args[0] == "u@x.com"


def test_as_callback_without_pending_request_is_a_400():
    response = make_client().get("/oauth/as-callback?code=x&state=y", follow_redirects=False)
    assert response.status_code == 400
