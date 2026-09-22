# SPDX-License-Identifier: Apache-2.0
import base64
import json as _json
from unittest.mock import AsyncMock, MagicMock, patch

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


def test_auth_callback_no_email_returns_error_html(client):
    """Callback with token missing email renders error page."""
    mock_token = {"userinfo": {}}  # no email

    with patch("app.auth.oauth") as mock_oauth:
        mock_oauth.oidc.authorize_access_token = AsyncMock(return_value=mock_token)
        response = client.get("/api/oauth/callback")

    assert response.status_code == 400
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


# ---------------------------------------------------------------------------
# Unified /api/oauth/callback — action dispatching
# ---------------------------------------------------------------------------


def _make_session_cookie(secret: str, data: dict) -> str:
    """Create a signed Starlette session cookie for test use."""
    signer = TimestampSigner(secret)
    payload = base64.b64encode(_json.dumps(data).encode()).decode()
    return signer.sign(payload).decode()


_TEST_SESSION_SECRET = "test-secret-32-chars-padding-xxxx"


def test_login_redirects_to_oidc(client):
    """GET /api/oauth/login starts the OIDC flow; the callback_url is built from
    app_base_url (always https), not request.url_for."""
    from starlette.responses import RedirectResponse as StarletteRedirectResponse

    captured = {}

    async def _capture_redirect(request, callback_url, **kwargs):
        captured["callback_url"] = callback_url
        return StarletteRedirectResponse(url="http://dex.test/auth", status_code=302)

    with patch("app.auth.oauth") as mock_oauth:
        mock_oauth.oidc.authorize_redirect = AsyncMock(side_effect=_capture_redirect)
        response = client.get("/api/oauth/login", follow_redirects=False)

    assert response.status_code in (302, 303)
    assert captured["callback_url"] == "http://localhost:8080/api/oauth/callback"


def test_callback_eager_creates_without_minting(client):
    """The callback eager-creates the user via ensure_team_and_user and mints no key (D-13)."""
    mock_token = {
        "userinfo": {"email": "alice@example.com", "name": "Alice Example"},
    }

    with (
        patch("app.auth.oauth") as mock_oauth,
        patch("app.auth.ensure_team_and_user", new_callable=AsyncMock) as mock_ensure,
    ):
        mock_oauth.oidc.authorize_access_token = AsyncMock(return_value=mock_token)
        mock_ensure.return_value = None

        response = client.get("/api/oauth/callback", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"].endswith("/ui")
    mock_ensure.assert_awaited_once()


def test_callback_returns_to_the_openwork_handoff_when_that_was_the_intent(client):
    """A desktop sign-in that detoured through Dex must come back to /openwork.

    Without this the user lands on the SPA and the desktop waits forever.
    """
    mock_token = {"userinfo": {"email": "alice@example.com", "name": "Alice Example"}}
    cookie = _make_session_cookie(_TEST_SESSION_SECRET, {"openwork_handoff": True})

    with (
        patch("app.auth.oauth") as mock_oauth,
        patch("app.auth.ensure_team_and_user", new_callable=AsyncMock),
    ):
        mock_oauth.oidc.authorize_access_token = AsyncMock(return_value=mock_token)
        response = client.get(
            "/api/oauth/callback", cookies={"session": cookie}, follow_redirects=False
        )

    assert response.status_code == 302
    assert response.headers["location"] == "http://localhost:8080/openwork"


# ---------------------------------------------------------------------------
# GET /api/oauth/logout — app-local logout (SPA "sign out" link)
# ---------------------------------------------------------------------------


def test_logout_redirects_to_ui_and_clears_session(client):
    """A seeded session → /api/oauth/logout 302s to /ui/ and clears the cookie."""
    cookie = _make_session_cookie(_TEST_SESSION_SECRET, {"email": "alice@example.com"})
    response = client.get("/api/oauth/logout", cookies={"session": cookie}, follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "http://localhost:8080/ui/"
    # Starlette emits a clearing Set-Cookie once the session is emptied.
    set_cookie = response.headers.get("set-cookie", "")
    assert "session=" in set_cookie
    assert "Max-Age=0" in set_cookie or "max-age=0" in set_cookie or "01 Jan 1970" in set_cookie


def test_logout_without_session_still_redirects(client):
    """No session cookie → logout is still a clean 302 to /ui/ (no 404, no error)."""
    response = client.get("/api/oauth/logout", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "http://localhost:8080/ui/"


def test_auth_callback_token_exchange_error_does_not_leak(client):
    """#4: an OIDC token-exchange exception must NOT render str(exc) into the page."""
    secret = "https://issuer.internal/secret?error_description=leaked"
    with patch("app.auth.oauth") as mock_oauth:
        mock_oauth.oidc.authorize_access_token = AsyncMock(side_effect=Exception(secret))
        response = client.get("/api/oauth/callback")
    assert response.status_code == 400
    assert "issuer.internal" not in response.text


def test_normalize_groups_coerces_provider_shapes() -> None:
    """The groups claim arrives in several shapes and must never raise (SSO-GRP)."""
    from app.auth import normalize_groups

    # Dex returns a list of strings; whitespace and empties are dropped.
    assert normalize_groups(["platform-eng@ackstorm.com", " ai-team@ackstorm.com "]) == [
        "platform-eng@ackstorm.com",
        "ai-team@ackstorm.com",
    ]
    # A provider that sends a single string still yields a list.
    assert normalize_groups("solo@ackstorm.com") == ["solo@ackstorm.com"]
    # Scope not granted / claim absent / junk types degrade to [], never raise.
    assert normalize_groups(None) == []
    assert normalize_groups({"not": "a list"}) == []
    assert normalize_groups([1, None, "", "  ", "ok@x.com"]) == ["ok@x.com"]


def test_normalize_groups_caps_the_list() -> None:
    """A huge groups claim must not overflow the signed session cookie."""
    from app.auth import MAX_GROUPS, normalize_groups

    groups = normalize_groups([f"g{i}@ackstorm.com" for i in range(MAX_GROUPS + 40)])
    assert len(groups) == MAX_GROUPS
    assert groups[0] == "g0@ackstorm.com"


def test_oauth_scopes_must_include_openid() -> None:
    """Dropping openid kills every login; fail at boot, not at sign-in."""
    import pytest

    from app.config import Settings

    base = make_test_settings().model_dump()
    for bad in ("email profile groups", "", "   "):
        with pytest.raises(ValueError, match="openid"):
            Settings(**{**base, "oauth_scopes": bad})
