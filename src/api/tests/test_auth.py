# SPDX-License-Identifier: Apache-2.0
import base64
import json as _json
from unittest.mock import AsyncMock, MagicMock, patch, ANY

import httpx
import pytest
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner

from app.config import Settings
from app.litellm_client import LiteLLMUserNotFound
from app.main import create_app


def make_test_settings() -> Settings:
    return Settings(
        app_base_url="http://localhost:8080",
        session_secret_key="test-secret-32-chars-padding-xxxx",
        oauth_issuer_url="http://dex.test/dex",
        oauth_client_id="test-client",
        oauth_client_secret="test-secret",
        litellm_url="http://litellm.test",
        litellm_master_key="sk-test",
        api_public_url="https://api.test",
    )


@pytest.fixture()
def client() -> TestClient:
    """Shared test client -- no server exceptions so we can assert status codes."""
    app = create_app(settings=make_test_settings())
    return TestClient(app, raise_server_exceptions=False)


def test_auth_callback_success_returns_html(client):
    """Callback with valid token returns success HTML with key."""
    mock_token = {
        "userinfo": {"email": "alice@example.com", "name": "Alice Example"},
    }

    with (
        patch("app.auth.oauth") as mock_oauth,
        patch("app.auth.generate_litellm_key", new_callable=AsyncMock) as mock_key,
    ):
        mock_oauth.oidc.authorize_access_token = AsyncMock(return_value=mock_token)
        mock_key.return_value = {
            "key": "sk-test-key",
            "id": "key-123",
            "team_id": "team-platform",
        }

        response = client.get("/api/oauth/callback")

    assert response.status_code == 200
    assert "sk-test-key" in response.text
    assert "alice@example.com" in response.text


def test_auth_callback_no_email_returns_error_html(client):
    """Callback with token missing email renders error page."""
    mock_token = {"userinfo": {}}  # no email

    with patch("app.auth.oauth") as mock_oauth:
        mock_oauth.oidc.authorize_access_token = AsyncMock(return_value=mock_token)
        response = client.get("/api/oauth/callback")

    assert response.status_code == 400
    assert "Error" in response.text


def test_auth_callback_litellm_failure_returns_error_html(client):
    """Callback renders error page when LiteLLM key generation fails."""
    mock_token = {"userinfo": {"email": "alice@example.com", "name": "Alice"}}

    with (
        patch("app.auth.oauth") as mock_oauth,
        patch("app.auth.generate_litellm_key", new_callable=AsyncMock) as mock_key,
    ):
        mock_oauth.oidc.authorize_access_token = AsyncMock(return_value=mock_token)
        mock_key.side_effect = Exception("LiteLLM unavailable")

        response = client.get("/api/oauth/callback")

    assert response.status_code == 500
    assert "Error" in response.text


def test_auth_callback_oidc_error_returns_error_html(client):
    """Callback renders error page when OIDC exchange fails."""
    with patch("app.auth.oauth") as mock_oauth:
        mock_oauth.oidc.authorize_access_token = AsyncMock(
            side_effect=Exception("OIDC state mismatch")
        )
        response = client.get("/api/oauth/callback")

    assert response.status_code == 400
    assert "Error" in response.text


# ---------------------------------------------------------------------------
# /api/oauth/whoami
# ---------------------------------------------------------------------------


_fake_info_base = {
    "id": "key-123",
    "email": "alice@example.com",
    "name": "Alice Example",
    "team_id": "team-platform",
    "user_id": "alice@example.com",
    "models": ["all-team-models"],
    "created_at": "2026-01-01T00:00:00+00:00",
    "expires": None,
    "spend": 1.23,
    "max_budget": 50.0,
    "budget_duration": "24h",
    "tpm_limit": 1000000,
    "rpm_limit": 100,
    "last_active": "2026-03-03T05:35:44.827000+00:00",
}

_fake_litellm_user = {
    "user_id": "alice@example.com",
    "email": "alice@example.com",
    "role": "internal_user",
    "spend": 2.5,
    "max_budget": 10.0,
    "teams": ["platform"],
}


def test_whoami_missing_header_returns_401(client):
    """GET /api/oauth/whoami without header → 401."""
    response = client.get("/api/oauth/whoami")

    assert response.status_code == 401
    assert "missing" in response.json()["detail"].lower()


def test_whoami_valid_key_returns_user_json(client):
    """GET /api/oauth/whoami with valid key → 200 + user_id + nested litellm_user in JSON."""
    fake_info = dict(_fake_info_base)

    with (
        patch("app.auth.get_key_info", new_callable=AsyncMock) as mock_info,
        patch("app.auth.get_litellm_user", new_callable=AsyncMock) as mock_user,
    ):
        mock_info.return_value = fake_info
        mock_user.return_value = dict(_fake_litellm_user)
        response = client.get(
            "/api/oauth/whoami",
            headers={"x-alitellm-auth-api-key": "sk-valid-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "key-123"
    assert "key_alias" not in data
    assert data["user_id"] == "alice@example.com"
    assert data["email"] == "alice@example.com"
    assert data["team_id"] == "team-platform"
    assert data["spend"] == 1.23
    assert data["max_budget"] == 50.0
    assert data["budget_duration"] == "24h"
    assert data["tpm_limit"] == 1000000
    assert data["rpm_limit"] == 100
    assert data["last_active"] == "2026-03-03T05:35:44.827000+00:00"
    assert "litellm_user" in data
    assert data["litellm_user"]["role"] == "internal_user"


def test_whoami_spend_defaults_to_zero_when_absent(client):
    """GET /api/oauth/whoami returns spend=0.0 when get_key_info defaults the field."""
    fake_info = {
        "id": "key-123",
        "email": "alice@example.com",
        "name": "Alice Example",
        "team_id": "team-platform",
        "user_id": "alice@example.com",
        "models": ["all-team-models"],
        "created_at": "2026-01-01T00:00:00+00:00",
        "expires": None,
        "spend": 0.0,  # get_key_info defaults this to 0.0 when LiteLLM omits it
    }

    with (
        patch("app.auth.get_key_info", new_callable=AsyncMock) as mock_info,
        patch("app.auth.get_litellm_user", new_callable=AsyncMock) as mock_user,
    ):
        mock_info.return_value = fake_info
        mock_user.return_value = dict(_fake_litellm_user)
        response = client.get(
            "/api/oauth/whoami",
            headers={"x-alitellm-auth-api-key": "sk-valid-key"},
        )

    assert response.status_code == 200
    assert response.json()["spend"] == 0.0


def _make_http_error(status_code: int, message: str = "error") -> httpx.HTTPStatusError:
    """Build a minimal httpx.HTTPStatusError for use in mocks."""
    resp = MagicMock(status_code=status_code)
    return httpx.HTTPStatusError(message, request=MagicMock(), response=resp)


def test_whoami_bearer_prefix_is_stripped(client):
    """GET /api/oauth/whoami accepts 'Bearer sk-...' in addition to plain 'sk-...'."""
    fake_info = {
        "id": "key-123",
        "email": "alice@example.com",
        "name": "Alice Example",
        "team_id": "team-platform",
        "user_id": "alice@example.com",
        "models": ["all-team-models"],
        "created_at": "2026-01-01T00:00:00+00:00",
        "expires": None,
    }

    with (
        patch("app.auth.get_key_info", new_callable=AsyncMock) as mock_info,
        patch("app.auth.get_litellm_user", new_callable=AsyncMock) as mock_user,
    ):
        mock_info.return_value = fake_info
        mock_user.return_value = dict(_fake_litellm_user)
        response = client.get(
            "/api/oauth/whoami",
            headers={"x-alitellm-auth-api-key": "Bearer sk-valid-key"},
        )

    assert response.status_code == 200


def test_whoami_invalid_key_returns_401(client):
    """GET /api/oauth/whoami with unknown key → 401."""
    err = _make_http_error(404, "not found")

    with patch("app.auth.get_key_info", new_callable=AsyncMock) as mock_info:
        mock_info.side_effect = err
        response = client.get(
            "/api/oauth/whoami",
            headers={"x-alitellm-auth-api-key": "sk-bad-key"},
        )

    assert response.status_code == 401
    assert "invalid" in response.json()["detail"].lower()


def test_whoami_litellm_server_error_returns_502(client):
    """GET /api/oauth/whoami when LiteLLM key lookup errors → 502."""
    err = _make_http_error(500, "server error")

    with patch("app.auth.get_key_info", new_callable=AsyncMock) as mock_info:
        mock_info.side_effect = err
        response = client.get(
            "/api/oauth/whoami",
            headers={"x-alitellm-auth-api-key": "sk-any-key"},
        )

    assert response.status_code == 502


def test_whoami_valid_key_user_not_found_returns_404(client):
    """GET /api/oauth/whoami with valid key whose LiteLLM User is absent → 404."""
    with (
        patch("app.auth.get_key_info", new_callable=AsyncMock) as mock_info,
        patch("app.auth.get_litellm_user", new_callable=AsyncMock) as mock_user,
    ):
        mock_info.return_value = {**_fake_info_base, "user_id": "alice@example.com"}
        mock_user.side_effect = LiteLLMUserNotFound("alice@example.com")
        response = client.get(
            "/api/oauth/whoami",
            headers={"x-alitellm-auth-api-key": "sk-valid-key"},
        )

    assert response.status_code == 404


def test_whoami_enrichment_error_returns_502(client):
    """GET /api/oauth/whoami when LiteLLM user enrichment fails with 5xx → 502."""
    with (
        patch("app.auth.get_key_info", new_callable=AsyncMock) as mock_info,
        patch("app.auth.get_litellm_user", new_callable=AsyncMock) as mock_user,
    ):
        mock_info.return_value = {**_fake_info_base, "user_id": "alice@example.com"}
        mock_user.side_effect = _make_http_error(500)
        response = client.get(
            "/api/oauth/whoami",
            headers={"x-alitellm-auth-api-key": "sk-valid-key"},
        )

    assert response.status_code == 502


def test_whoami_valid_key_without_email_returns_unenriched(client):
    """WR-01: a valid key whose metadata has no email returns key info as-is (no 404)."""
    fake_info = {**_fake_info_base, "email": None}

    with (
        patch("app.auth.get_key_info", new_callable=AsyncMock) as mock_info,
        patch("app.auth.get_litellm_user", new_callable=AsyncMock) as mock_user,
    ):
        mock_info.return_value = fake_info
        response = client.get(
            "/api/oauth/whoami",
            headers={"x-alitellm-auth-api-key": "sk-valid-key"},
        )

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == "key-123"
    # No enrichment attempted when email is absent
    assert "litellm_user" not in data
    mock_user.assert_not_called()


def test_me_path_is_gone(client):
    """Old /api/oauth/me path is removed (hard rename to /whoami)."""
    response = client.get("/api/oauth/me")
    assert response.status_code == 404


def test_delete_token_success(client):
    """DELETE /api/oauth/tokens/{id} with valid header."""
    caller_info = {"email": "alice@example.com", "id": "caller-id"}
    user_keys = [
        {"id": "key-123", "key": "sk-123"},
        {"id": "key-456", "key": "sk-456"},
    ]

    with (
        patch("app.auth.get_key_info", new_callable=AsyncMock) as mock_info,
        patch("app.auth.list_litellm_keys", new_callable=AsyncMock) as mock_list,
        patch("app.auth.delete_litellm_key", new_callable=AsyncMock) as mock_delete,
    ):
        mock_info.return_value = caller_info
        mock_list.return_value = user_keys

        response = client.delete(
            "/api/oauth/tokens/key-123",
            headers={"x-alitellm-auth-api-key": "sk-admin"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "deleted"
    assert response.json()["id"] == "key-123"
    mock_delete.assert_called_once_with("sk-123", ANY)


def test_delete_token_unauthorized(client):
    """DELETE /api/oauth/tokens/{id} without header → 401."""
    response = client.delete("/api/oauth/tokens/key-123")
    assert response.status_code == 401


def test_delete_token_not_found(client):
    """DELETE /api/oauth/tokens/{id} for a key not belonging to user → 404."""
    caller_info = {"email": "alice@example.com", "id": "caller-id"}
    user_keys = [
        {"id": "key-123", "key": "sk-123"},
    ]

    with (
        patch("app.auth.get_key_info", new_callable=AsyncMock) as mock_info,
        patch("app.auth.list_litellm_keys", new_callable=AsyncMock) as mock_list,
    ):
        mock_info.return_value = caller_info
        mock_list.return_value = user_keys

        response = client.delete(
            "/api/oauth/tokens/key-UNKNOWN",
            headers={"x-alitellm-auth-api-key": "sk-admin"},
        )

    assert response.status_code == 404


def test_delete_token_invalid_key_returns_401(client):
    """DELETE: caller key rejected by LiteLLM (4xx) → 401."""
    err = _make_http_error(404, "not found")

    with patch("app.auth.get_key_info", new_callable=AsyncMock) as mock_info:
        mock_info.side_effect = err
        response = client.delete(
            "/api/oauth/tokens/key-123",
            headers={"x-alitellm-auth-api-key": "sk-bad-key"},
        )

    assert response.status_code == 401
    assert "invalid" in response.json()["detail"].lower()


def test_delete_token_backend_down_returns_502(client):
    """WR-02: DELETE when LiteLLM key lookup errors with 5xx → 502, not 401."""
    err = _make_http_error(500, "server error")

    with patch("app.auth.get_key_info", new_callable=AsyncMock) as mock_info:
        mock_info.side_effect = err
        response = client.delete(
            "/api/oauth/tokens/key-123",
            headers={"x-alitellm-auth-api-key": "sk-valid-key"},
        )

    assert response.status_code == 502


def test_delete_token_backend_delete_failure_returns_502(client):
    """WR-05: a 5xx from delete_litellm_key maps to 502 with a generic detail (no raw leak)."""
    caller_info = {"email": "alice@example.com", "id": "caller-id"}
    user_keys = [{"id": "key-123", "key": "sk-123"}]
    err = _make_http_error(500, "boom: backend resp.text leak")

    with (
        patch("app.auth.get_key_info", new_callable=AsyncMock) as mock_info,
        patch("app.auth.list_litellm_keys", new_callable=AsyncMock) as mock_list,
        patch("app.auth.delete_litellm_key", new_callable=AsyncMock) as mock_delete,
    ):
        mock_info.return_value = caller_info
        mock_list.return_value = user_keys
        mock_delete.side_effect = err

        response = client.delete(
            "/api/oauth/tokens/key-123",
            headers={"x-alitellm-auth-api-key": "sk-admin"},
        )

    assert response.status_code == 502
    assert response.json()["detail"] == "Failed to delete token"
    assert "backend resp.text leak" not in response.text


def test_delete_token_email_less_caller_refused_403(client):
    """WR-B: an email-less caller key cannot enumerate/delete other email-less keys.

    Mirrors the WR-01 whoami guard on the destructive path. When the caller key
    has no email metadata, email is None; without the guard the ownership filter
    (metadata.get("email") == None) would match every other email-less key and
    allow a successful delete. We must refuse before listing keys.
    """
    caller_info = {"email": None, "id": "caller-id"}

    with (
        patch("app.auth.get_key_info", new_callable=AsyncMock) as mock_info,
        patch("app.auth.list_litellm_keys", new_callable=AsyncMock) as mock_list,
        patch("app.auth.delete_litellm_key", new_callable=AsyncMock) as mock_delete,
    ):
        mock_info.return_value = caller_info

        response = client.delete(
            "/api/oauth/tokens/key-other-emailless",
            headers={"x-alitellm-auth-api-key": "sk-emailless"},
        )

    assert response.status_code == 403
    # Never list or delete on behalf of an email-less key.
    mock_list.assert_not_called()
    mock_delete.assert_not_called()


# ---------------------------------------------------------------------------
# Unified /api/oauth/callback — action dispatching
# ---------------------------------------------------------------------------


def _make_session_cookie(secret: str, data: dict) -> str:
    """Create a signed Starlette session cookie for test use."""
    signer = TimestampSigner(secret)
    payload = base64.b64encode(_json.dumps(data).encode()).decode()
    return signer.sign(payload).decode()


_TEST_SESSION_SECRET = "test-secret-32-chars-padding-xxxx"


def test_callback_action_login_generates_key(client):
    """action=login → generates a new key and renders success HTML."""
    mock_token = {
        "userinfo": {"email": "alice@example.com", "name": "Alice Example"},
    }

    with (
        patch("app.auth.oauth") as mock_oauth,
        patch("app.auth.generate_litellm_key", new_callable=AsyncMock) as mock_key,
    ):
        mock_oauth.oidc.authorize_access_token = AsyncMock(return_value=mock_token)
        mock_key.return_value = {"key": "sk-new", "id": "key-1", "team_id": "t-1"}

        cookie = _make_session_cookie(_TEST_SESSION_SECRET, {"oauth_action": "login"})
        response = client.get("/api/oauth/callback", cookies={"session": cookie})

    assert response.status_code == 200
    assert "sk-new" in response.text


def test_callback_action_reveal_shows_account_without_key(client):
    """action=reveal → lists keys and renders success HTML; key field is omitted (not recoverable)."""
    mock_token = {
        "userinfo": {"email": "alice@example.com", "name": "Alice Example"},
    }

    with (
        patch("app.auth.oauth") as mock_oauth,
        patch("app.auth.list_litellm_keys", new_callable=AsyncMock) as mock_list,
    ):
        mock_oauth.oidc.authorize_access_token = AsyncMock(return_value=mock_token)
        mock_list.return_value = [{"key": "hash-not-usable", "id": "key-old"}]

        cookie = _make_session_cookie(_TEST_SESSION_SECRET, {"oauth_action": "reveal"})
        response = client.get("/api/oauth/callback", cookies={"session": cookie})

    assert response.status_code == 200
    assert "alice@example.com" in response.text
    assert "hash-not-usable" not in response.text


def test_callback_action_tokens_returns_json_without_key(client):
    """action=tokens → lists keys as JSON; 'key' field is stripped from each token."""
    mock_token = {
        "userinfo": {"email": "alice@example.com", "name": "Alice Example"},
    }

    with (
        patch("app.auth.oauth") as mock_oauth,
        patch("app.auth.list_litellm_keys", new_callable=AsyncMock) as mock_list,
    ):
        mock_oauth.oidc.authorize_access_token = AsyncMock(return_value=mock_token)
        mock_list.return_value = [{"key": "sk-t1", "id": "key-t1"}]

        cookie = _make_session_cookie(_TEST_SESSION_SECRET, {"oauth_action": "tokens"})
        response = client.get("/api/oauth/callback", cookies={"session": cookie})

    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "alice@example.com"
    assert "key" not in data["tokens"][0]
    assert data["tokens"][0]["id"] == "key-t1"


def test_callback_action_reveal_list_failure_does_not_leak_backend_text(client):
    """WR-A: a list_litellm_keys failure on reveal renders a generic page, no raw leak."""
    mock_token = {
        "userinfo": {"email": "alice@example.com", "name": "Alice Example"},
    }
    err = _make_http_error(500, "boom: backend resp.text leak from /key/list")

    with (
        patch("app.auth.oauth") as mock_oauth,
        patch("app.auth.list_litellm_keys", new_callable=AsyncMock) as mock_list,
    ):
        mock_oauth.oidc.authorize_access_token = AsyncMock(return_value=mock_token)
        mock_list.side_effect = err

        cookie = _make_session_cookie(_TEST_SESSION_SECRET, {"oauth_action": "reveal"})
        response = client.get("/api/oauth/callback", cookies={"session": cookie})

    assert response.status_code == 500
    assert "backend resp.text leak" not in response.text
    assert "Could not retrieve your tokens" in response.text


def test_login_action_ui_stamps_oauth_action_ui(client):
    """GET /api/oauth/login?action=ui stamps session['oauth_action']='ui' (D-13)."""
    from starlette.responses import RedirectResponse as StarletteRedirectResponse

    captured = {}

    async def _capture_redirect(request, callback_url, **kwargs):
        captured["oauth_action"] = request.session.get("oauth_action")
        return StarletteRedirectResponse(url="http://dex.test/auth", status_code=302)

    with patch("app.auth.oauth") as mock_oauth:
        mock_oauth.oidc.authorize_redirect = AsyncMock(side_effect=_capture_redirect)
        response = client.get("/api/oauth/login?action=ui", follow_redirects=False)

    assert response.status_code in (302, 303)
    assert captured["oauth_action"] == "ui"


def test_login_action_junk_falls_back_to_login(client):
    """A non-whitelisted ?action= value is never written to the session (T-09-04)."""
    from starlette.responses import RedirectResponse as StarletteRedirectResponse

    captured = {}

    async def _capture_redirect(request, callback_url, **kwargs):
        captured["oauth_action"] = request.session.get("oauth_action")
        return StarletteRedirectResponse(url="http://dex.test/auth", status_code=302)

    with patch("app.auth.oauth") as mock_oauth:
        mock_oauth.oidc.authorize_redirect = AsyncMock(side_effect=_capture_redirect)
        response = client.get(
            "/api/oauth/login?action=../../etc/passwd", follow_redirects=False
        )

    assert response.status_code in (302, 303)
    assert captured["oauth_action"] == "login"


def test_callback_action_ui_eager_creates_without_minting(client):
    """action=ui → ensure_team_and_user IS called, generate_litellm_key is NOT (D-13)."""
    mock_token = {
        "userinfo": {"email": "alice@example.com", "name": "Alice Example"},
    }

    with (
        patch("app.auth.oauth") as mock_oauth,
        patch("app.auth.ensure_team_and_user", new_callable=AsyncMock) as mock_ensure,
        patch("app.auth.generate_litellm_key", new_callable=AsyncMock) as mock_key,
    ):
        mock_oauth.oidc.authorize_access_token = AsyncMock(return_value=mock_token)
        mock_ensure.return_value = None

        cookie = _make_session_cookie(_TEST_SESSION_SECRET, {"oauth_action": "ui"})
        response = client.get(
            "/api/oauth/callback", cookies={"session": cookie}, follow_redirects=False
        )

    assert response.status_code == 302
    assert response.headers["location"].endswith("/ui")
    mock_ensure.assert_awaited_once()
    mock_key.assert_not_called()


def test_callback_action_tokens_list_failure_does_not_leak_backend_text(client):
    """WR-A: a list_litellm_keys failure on tokens renders a generic page, no raw leak."""
    mock_token = {
        "userinfo": {"email": "alice@example.com", "name": "Alice Example"},
    }
    err = _make_http_error(500, "boom: backend resp.text leak from /key/list")

    with (
        patch("app.auth.oauth") as mock_oauth,
        patch("app.auth.list_litellm_keys", new_callable=AsyncMock) as mock_list,
    ):
        mock_oauth.oidc.authorize_access_token = AsyncMock(return_value=mock_token)
        mock_list.side_effect = err

        cookie = _make_session_cookie(_TEST_SESSION_SECRET, {"oauth_action": "tokens"})
        response = client.get("/api/oauth/callback", cookies={"session": cookie})

    assert response.status_code == 500
    assert "backend resp.text leak" not in response.text
    assert "Could not retrieve your tokens" in response.text
