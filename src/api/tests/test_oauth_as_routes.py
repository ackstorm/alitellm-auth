# SPDX-License-Identifier: Apache-2.0
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

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


def test_redirect_matches_exactly_except_loopback_port():
    matches = routes._redirect_matches
    assert matches("https://app.example/cb", "https://app.example/cb")
    assert not matches("https://app.example/cb", "https://app.example:443/cb")
    assert matches("http://127.0.0.1:1000/cb?state=x", "http://127.0.0.1:2000/cb?state=x")
    assert not matches("http://127.0.0.1:1000/cb?state=x", "http://127.0.0.1:2000/cb?state=y")
    assert not matches("http://127.0.0.1:1000/cb", "http://localhost:2000/cb")
