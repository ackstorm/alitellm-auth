# SPDX-License-Identifier: Apache-2.0
import httpx
import pytest
import respx
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.admin import require_admin
from app.config import Settings
from app.litellm_client import LiteLLMUserNotFound
from app.main import create_app

LITELLM_URL = "http://litellm.test"


def make_test_settings() -> Settings:
    return Settings(
        app_base_url="http://localhost:8080",
        session_secret_key="test-secret-32-chars-padding-xxxx",
        oauth_issuer_url="http://dex.test/dex",
        oauth_client_id="test-client",
        oauth_client_secret="test-secret",
        litellm_url="http://litellm.test",
        litellm_master_key="sk-master",
        api_public_url="https://api.test",
    )


@pytest.fixture()
def client() -> TestClient:
    app = create_app(settings=make_test_settings())
    return TestClient(app, raise_server_exceptions=False)


def _make_http_error(status_code: int, message: str = "error") -> httpx.HTTPStatusError:
    resp = MagicMock(status_code=status_code)
    return httpx.HTTPStatusError(message, request=MagicMock(), response=resp)


# ADMIN-04: authz gating


def test_users_requires_header(client):
    assert client.get("/api/users").status_code == 401


def test_users_non_master_key_forbidden(client):
    r = client.get("/api/users", headers={"x-alitellm-auth-api-key": "sk-not-master"})
    assert r.status_code == 403


def test_users_master_key_is_admin(client):
    with patch("app.admin.list_litellm_users", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = [{"user_id": "a@x.com"}]
        r = client.get("/api/users", headers={"x-alitellm-auth-api-key": "sk-master"})
    assert r.status_code == 200
    assert r.json()["users"][0]["user_id"] == "a@x.com"


# ADMIN-01: list with filters (D-01)


def test_users_role_filter(client):
    with patch("app.admin.list_litellm_users", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = [{"user_id": "a@x.com", "role": "internal_user"}]
        r = client.get(
            "/api/users?role=internal_user", headers={"x-alitellm-auth-api-key": "sk-master"}
        )
    assert r.status_code == 200
    mock_list.assert_called_once()
    _, kwargs = mock_list.call_args
    assert kwargs.get("role") == "internal_user"


def test_users_email_filter(client):
    with patch("app.admin.list_litellm_users", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = [{"user_id": "a@x.com"}]
        r = client.get("/api/users?email=a@x.com", headers={"x-alitellm-auth-api-key": "sk-master"})
    assert r.status_code == 200
    _, kwargs = mock_list.call_args
    assert kwargs.get("email") == "a@x.com"


# ADMIN-02: inspect (D-04 user+keys)


def test_get_user_found(client):
    with (
        patch("app.admin.get_litellm_user", new_callable=AsyncMock) as mock_user,
        patch("app.admin.list_litellm_keys", new_callable=AsyncMock) as mock_keys,
    ):
        mock_user.return_value = {"user_id": "a@x.com", "role": "internal_user"}
        mock_keys.return_value = [{"id": "key-1", "key": "sk-secret", "models": []}]
        r = client.get("/api/users/a@x.com", headers={"x-alitellm-auth-api-key": "sk-master"})
    assert r.status_code == 200
    data = r.json()
    assert data["user_id"] == "a@x.com"
    assert "keys" in data
    # key field must be stripped from inspect output (D-04, T-03-07)
    assert all("key" not in k for k in data["keys"])


def test_get_user_not_found(client):
    with patch("app.admin.get_litellm_user", new_callable=AsyncMock) as mock_user:
        mock_user.side_effect = LiteLLMUserNotFound("ghost@x.com")
        r = client.get("/api/users/ghost@x.com", headers={"x-alitellm-auth-api-key": "sk-master"})
    assert r.status_code == 404


def test_get_user_litellm_502(client):
    with patch("app.admin.get_litellm_user", new_callable=AsyncMock) as mock_user:
        mock_user.side_effect = _make_http_error(500, "boom")
        r = client.get("/api/users/a@x.com", headers={"x-alitellm-auth-api-key": "sk-master"})
    assert r.status_code == 502


# ADMIN-03: delete (D-02 404-if-absent)


def test_delete_user(client):
    with (
        patch("app.admin.get_litellm_user", new_callable=AsyncMock) as mock_get,
        patch("app.admin.delete_litellm_user", new_callable=AsyncMock) as mock_del,
    ):
        mock_get.return_value = {"user_id": "a@x.com"}
        r = client.delete("/api/users/a@x.com", headers={"x-alitellm-auth-api-key": "sk-master"})
    assert r.status_code == 200
    assert r.json() == {"status": "deleted", "user_id": "a@x.com"}
    mock_del.assert_called_once()


def test_delete_user_not_found(client):
    with patch("app.admin.get_litellm_user", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = LiteLLMUserNotFound("ghost@x.com")
        r = client.delete(
            "/api/users/ghost@x.com", headers={"x-alitellm-auth-api-key": "sk-master"}
        )
    assert r.status_code == 404


# ─────────────────────────────────────────────────────────────────────────────
# Live-backend behaviors — mocks grounded in REAL LiteLLM v1.83.10-stable
# response shapes (captured from a throwaway litellm-database:v1.83.10-stable
# container, the version the ach / alitellm-operator e2e clusters pin). These
# convert the 03-HUMAN-UAT items into deterministic in-process coverage; full
# live-cluster verification is the dedicated e2e phase (docker-compose).
#
# Tokens/hashes below are sanitized placeholders — this repo goes public with
# secret-scanning hooks, so no real sk- value is committed. Only the JSON SHAPE
# is real (verified against the live capture).
# ─────────────────────────────────────────────────────────────────────────────


# UAT item 3 / WR-03: non-ASCII auth header → 403, never a 500.
@pytest.mark.asyncio
async def test_require_admin_non_ascii_header_returns_403():
    """A raw header byte 0x80-0xFF decodes (latin-1) to a non-ASCII str, and
    hmac.compare_digest raises TypeError on a non-ASCII *str* — pre-WR-03 that
    surfaced as a 500 for an UNAUTHENTICATED caller. The UTF-8 bytes-compare fix
    must yield a clean 403. Asserted at the guard directly: httpx's TestClient
    cannot transmit a non-ASCII header byte, so the over-the-wire path is the
    e2e phase's job.
    """
    settings = make_test_settings()
    with pytest.raises(HTTPException) as exc:
        await require_admin("sk-\xff\x80", settings)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_require_admin_accepts_master_key():
    settings = make_test_settings()
    # Accepts the master key without raising 403; returns None (the sentinel
    # return was dead — _guard discards it).
    assert await require_admin(settings.litellm_master_key, settings) is None


# UAT item 1 / T-03-07: the secret token must not survive the REAL /key/list
# (token-hash strings) → /key/info hydration path into the inspect response.
@respx.mock
def test_get_user_strips_token_through_real_keylist_hydration(client):
    # /user/info — real wrapper shape, non-placeholder user_id (no fallback hit).
    respx.get(f"{LITELLM_URL}/user/info").mock(
        return_value=httpx.Response(
            200,
            json={
                "user_id": "alice@example.com",
                "user_info": {
                    "user_id": "alice@example.com",
                    "user_email": "alice@example.com",
                    "user_role": "internal_user",
                    "teams": [],
                    "models": [],
                    "metadata": {},
                    "spend": 0.0,
                    "max_budget": None,
                },
            },
        )
    )
    # /key/list default shape in v1.83 is a list of opaque token-HASH STRINGS,
    # which forces list_litellm_keys down the get_key_info hydration path.
    respx.get(f"{LITELLM_URL}/key/list").mock(
        return_value=httpx.Response(
            200,
            json={
                "keys": ["a1b2c3hashfake0001"],
                "total_count": 1,
                "current_page": 1,
                "total_pages": 1,
            },
        )
    )
    # /key/info hydration: real {"key":..,"info":{..}} wrapper. The inner info
    # carries metadata.email (ownership) but no raw token, so list_litellm_keys
    # restores key=<hash> — which the endpoint must then strip.
    respx.get(f"{LITELLM_URL}/key/info").mock(
        return_value=httpx.Response(
            200,
            json={
                "key": "sk-test-fake-redacted",
                "info": {
                    "key_name": "sk-...0001",
                    "user_id": "alice@example.com",
                    "team_id": None,
                    "models": [],
                    "metadata": {"email": "alice@example.com", "name": "Alice"},
                    "spend": 0.0,
                },
            },
        )
    )

    r = client.get("/api/users/alice@example.com", headers={"x-alitellm-auth-api-key": "sk-master"})
    assert r.status_code == 200
    data = r.json()
    assert data["keys"], "expected the hydrated key to be listed"
    for entry in data["keys"]:
        assert "key" not in entry  # raw token/hash stripped from inspect output
    # Belt-and-braces: no token material leaks anywhere in the response body.
    assert "sk-test-fake-redacted" not in r.text
    assert "a1b2c3hashfake0001" not in r.text


# UAT item 2 / WR-05: a FAILED /user/list fallback on the destructive DELETE
# pre-check maps to 502 (backend unknown) — never a misleading 404.
@respx.mock
def test_delete_user_backend_down_on_list_fallback_returns_502(client):
    respx.get(f"{LITELLM_URL}/user/info").mock(
        return_value=httpx.Response(
            404,
            json={
                "error": {
                    "message": "User x not found",
                    "type": "internal_server_error",
                    "param": "None",
                    "code": "404",
                },
            },
        )
    )
    respx.get(f"{LITELLM_URL}/user/list").mock(
        return_value=httpx.Response(
            500,
            json={
                "error": {"message": "internal", "type": "internal_server_error", "code": "500"},
            },
        )
    )
    delete_route = respx.post(f"{LITELLM_URL}/user/delete").mock(
        return_value=httpx.Response(200, json=1)
    )

    r = client.delete("/api/users/x@example.com", headers={"x-alitellm-auth-api-key": "sk-master"})
    assert r.status_code == 502
    assert not delete_route.called  # must NOT destroy when existence is UNKNOWN


# UAT item 2 / D-02: genuine absence (empty /user/list) → 404, no delete call.
@respx.mock
def test_delete_user_genuine_absence_returns_404(client):
    respx.get(f"{LITELLM_URL}/user/info").mock(
        return_value=httpx.Response(
            404,
            json={
                "error": {"message": "User ghost not found", "code": "404"},
            },
        )
    )
    respx.get(f"{LITELLM_URL}/user/list").mock(
        return_value=httpx.Response(
            200,
            json={
                "users": [],
                "total": 0,
                "page": 1,
                "page_size": 100,
                "total_pages": 0,
            },
        )
    )
    delete_route = respx.post(f"{LITELLM_URL}/user/delete").mock(
        return_value=httpx.Response(200, json=1)
    )

    r = client.delete(
        "/api/users/ghost@example.com", headers={"x-alitellm-auth-api-key": "sk-master"}
    )
    assert r.status_code == 404
    assert not delete_route.called
