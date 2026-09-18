# SPDX-License-Identifier: Apache-2.0
"""Tests for the OpenWork organization server (Den) contract.

See docs/plans/2026-09-18-openwork-den.md. The desktop client is strict about
error shape and CORS; those are pinned here, not left to convention.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.openwork import TOKEN_KIND


def make_test_settings(**overrides):
    from app.config import Settings

    base = dict(
        app_base_url="http://localhost:8080",
        session_secret_key="test-secret-32-chars-padding-xxxx",
        oauth_issuer_url="http://dex.test/dex",
        oauth_client_id="test-client",
        oauth_client_secret="test-secret",
        litellm_url="http://litellm.test",
        litellm_master_key="sk-test",
        openwork_enabled=True,
        as_redis_url="memory://",
    )
    base.update(overrides)
    return Settings(**base)


def _client(**overrides):
    from app.main import create_app

    return TestClient(create_app(make_test_settings(**overrides)))


def _put_token(client: TestClient, token: str = "test-den-token") -> str:
    asyncio.run(
        client.app.state.openwork_store.put(
            TOKEN_KIND, token, {"email": "dev@ackstorm.com", "name": "Dev"}, ttl=3600
        )
    )
    return token


@pytest.fixture
def den_token_client():
    """A TestClient plus a valid Den session token for dev@ackstorm.com."""
    client = _client()
    return client, _put_token(client)


def test_den_routes_absent_when_disabled():
    response = _client(openwork_enabled=False).get("/openwork/api/den/v1/me")
    assert response.status_code == 404


def test_unauthenticated_v1_call_uses_the_den_error_shape():
    # The desktop reads payload.error / payload.message; FastAPI's default
    # {"detail": ...} would surface as a generic "Request failed with 401".
    response = _client().get("/openwork/api/den/v1/me")
    assert response.status_code == 401
    body = response.json()
    assert body["error"] == "unauthorized"
    assert isinstance(body["message"], str) and body["message"]
    assert "detail" not in body


def test_unknown_token_is_rejected_with_the_den_error_shape(den_token_client):
    client, _ = den_token_client
    response = client.get("/openwork/api/den/v1/me", headers={"authorization": "Bearer nope"})
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_me_returns_the_token_owner(den_token_client):
    client, token = den_token_client
    response = client.get("/openwork/api/den/v1/me", headers={"authorization": f"Bearer {token}"})
    assert response.status_code == 200
    user = response.json()["user"]
    assert user["email"] == "dev@ackstorm.com"
    assert user["name"] == "Dev"
    assert user["id"].startswith("user_")


def test_den_cors_reflects_the_requesting_origin():
    # credentials: "include" on the client (den.ts:2916) means the wildcard
    # origin is rejected; the exact origin must come back.
    response = _client().options(
        "/openwork/api/den/v1/me",
        headers={
            "origin": "app://openwork",
            "access-control-request-method": "GET",
            "access-control-request-headers": "authorization",
        },
    )
    assert response.status_code in (200, 204)
    assert response.headers["access-control-allow-origin"] == "app://openwork"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_den_cors_applies_to_real_responses_too(den_token_client):
    client, token = den_token_client
    response = client.get(
        "/openwork/api/den/v1/me",
        headers={"authorization": f"Bearer {token}", "origin": "app://openwork"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "app://openwork"


def test_den_cors_does_not_apply_to_the_spa_api():
    response = _client().options(
        "/api/config",
        headers={"origin": "https://evil.test", "access-control-request-method": "GET"},
    )
    assert "access-control-allow-origin" not in response.headers
