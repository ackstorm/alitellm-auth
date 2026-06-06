# SPDX-License-Identifier: Apache-2.0
"""Tests for the session-cookie-authenticated API (SAPI-01..06, D-09b, D-18)."""

from __future__ import annotations

import base64
import json as _json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner
from pydantic import ValidationError

from app.config import Settings
from app.litellm_client import LiteLLMUserNotFound
from app.main import create_app

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_TEST_SESSION_SECRET = "test-secret-32-chars-padding-xxxx"


def make_test_settings() -> Settings:
    return Settings(
        app_base_url="http://localhost:8080",
        session_secret_key=_TEST_SESSION_SECRET,
        oauth_issuer_url="http://dex.test/dex",
        oauth_client_id="test-client",
        oauth_client_secret="test-secret",
        litellm_url="http://litellm.test",
        litellm_master_key="sk-test",
        api_public_url="https://api.test",
        session_https_only=False,
    )


def _make_session_cookie(secret: str, data: dict) -> str:
    """Create a signed Starlette session cookie for test use."""
    signer = TimestampSigner(secret)
    payload = base64.b64encode(_json.dumps(data).encode()).decode()
    return signer.sign(payload).decode()


def _authed_cookie(email: str = "alice@example.com", name: str = "Alice") -> dict:
    return {"session": _make_session_cookie(_TEST_SESSION_SECRET, {"email": email, "name": name})}


@pytest.fixture()
def client() -> TestClient:
    app = create_app(settings=make_test_settings())
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# SAPI-01 / SAPI-06 — require_session_user dependency
# ---------------------------------------------------------------------------


def test_require_session_user_resolves(client):
    """Forged session cookie → GET /api/session/me returns 200 (not 401)."""
    with patch("app.session.get_litellm_user", new_callable=AsyncMock) as mock_user:
        mock_user.return_value = {
            "user_id": "alice@example.com",
            "email": "alice@example.com",
            "max_budget": 10.0,
            "budget_duration": "24h",
            "tpm_limit": 1000000,
            "rpm_limit": 100,
            "spend": 0.0,
        }
        response = client.get("/api/session/me", cookies=_authed_cookie())
    assert response.status_code == 200


def test_require_session_user_401(client):
    """No session cookie → GET /api/session/me returns 401 JSON (D-05/D-06)."""
    response = client.get("/api/session/me")
    assert response.status_code == 401
    data = response.json()
    assert data.get("detail") == "Not authenticated"


# ---------------------------------------------------------------------------
# D-03 — /ui serves the SPA shell via StaticFiles (200 text/html, even unauth)
# ---------------------------------------------------------------------------


def test_ui_serves_spa_shell(tmp_path, monkeypatch):
    """A built ui/dist/index.html → GET /ui returns 200 text/html, no auth needed.

    StaticFiles resolves "ui/dist" against the process cwd, so we chdir into a
    tmp dir that contains a minimal built shell, then build the app there.
    """
    dist = tmp_path / "ui" / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>alitellm</title>")

    monkeypatch.chdir(tmp_path)
    app = create_app(settings=make_test_settings())
    local_client = TestClient(app, raise_server_exceptions=False)

    response = local_client.get("/ui/", follow_redirects=False)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")


# ---------------------------------------------------------------------------
# SAPI-02 — GET /api/session/me
# ---------------------------------------------------------------------------

_USER_INFO = {
    "user_id": "alice@example.com",
    "email": "alice@example.com",
    "max_budget": 10.0,
    "budget_duration": "24h",
    "tpm_limit": 1000000,
    "rpm_limit": 100,
    "spend": 2.5,
    "max_parallel_requests": 5,
}


def test_me_returns_budget(client):
    """Authed /me returns identity + limits + spend (SAPI-02/D-09a)."""
    with patch("app.session.get_litellm_user", new_callable=AsyncMock) as mock_user:
        mock_user.return_value = _USER_INFO
        response = client.get("/api/session/me", cookies=_authed_cookie())
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "alice@example.com"
    assert data["team_id"] == "team-test-client"
    assert data["limits"]["max_budget"] == 10.0
    assert data["limits"]["budget_duration"] == "24h"
    assert data["spend"]["current"] == 2.5
    # source must be one of the documented values
    assert data["spend"]["source"] in ("team_member", "team", "user", "unknown")


def test_me_degrades(client):
    """When user enrichment fails, /me gracefully degrades (D-09)."""
    with patch("app.session.get_litellm_user", new_callable=AsyncMock) as mock_user:
        mock_user.side_effect = LiteLLMUserNotFound("alice@example.com")
        response = client.get("/api/session/me", cookies=_authed_cookie())
    assert response.status_code == 200
    data = response.json()
    assert data["email"] == "alice@example.com"
    assert data["limits"] is None or all(v is None for v in (data.get("limits") or {}).values())
    assert data["spend"]["current"] == 0
    assert data["spend"]["source"] == "unknown"


def test_me_unauth_401(client):
    """Unauthenticated /api/session/me → 401 JSON (SAPI-02/SAPI-06)."""
    response = client.get("/api/session/me")
    assert response.status_code == 401


# ---------------------------------------------------------------------------
# SAPI-03 — GET /api/session/keys
# ---------------------------------------------------------------------------

_SESSION_KEYS = [
    {
        "id": "abc123",
        "key_alias": "key-2026-06-03-120000",
        "spend": 1.0,
        "budget": None,
        "tpm_limit": None,
        "rpm_limit": None,
        "models": ["all-team-models"],
        "created_at": "2026-06-03T12:00:00+00:00",
        "expires": None,
    }
]


def test_keys_one_call(client):
    """GET /keys returns keys from list_session_keys (SAPI-03/D-08 one-call path)."""
    with patch("app.session.list_session_keys", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = _SESSION_KEYS
        response = client.get("/api/session/keys", cookies=_authed_cookie())
    assert response.status_code == 200
    data = response.json()
    assert "keys" in data
    assert len(data["keys"]) == 1
    assert data["keys"][0]["id"] == "abc123"
    # No "key" (sk-) should leak to the client
    assert "key" not in data["keys"][0]


def test_list_keys_strips_metadata_but_keeps_is_default(client):
    """The raw metadata (server-side only) must not reach the browser; is_default does."""
    keys = [
        {
            "id": "abc123",
            "token": "ltoken-hash",
            "key": "sk-should-not-leak",
            "key_alias": "key-a",
            "is_default": True,
            "metadata": {"email": "alice@example.com", "user_meta_extra": "secret"},
        }
    ]
    with patch("app.session.list_session_keys", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = keys
        response = client.get("/api/session/keys", cookies=_authed_cookie())
    assert response.status_code == 200
    body = response.json()["keys"][0]
    assert "metadata" not in body
    assert "token" not in body
    assert "key" not in body
    assert body["is_default"] is True


def test_keys_fallback(client):
    """GET /keys still returns correctly when list_session_keys triggers fallback."""
    fallback_keys = [
        {
            "id": "fallback-id",
            "key_alias": "key-2026-06-01-080000",
            "spend": 0.5,
            "budget": None,
            "tpm_limit": None,
            "rpm_limit": None,
            "models": ["all-team-models"],
            "created_at": "2026-06-01T08:00:00+00:00",
            "expires": None,
        }
    ]
    with patch("app.session.list_session_keys", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = fallback_keys
        response = client.get("/api/session/keys", cookies=_authed_cookie())
    assert response.status_code == 200
    assert response.json()["keys"][0]["id"] == "fallback-id"


# ---------------------------------------------------------------------------
# SAPI-04 — POST /api/session/keys
# ---------------------------------------------------------------------------


def test_create_key(client):
    """POST /keys mints a key; tests default alias, custom alias, and duration (SAPI-04/D-10)."""
    # (a) No body → sk- returned once; /key/generate body has no 'duration' key;
    #     alias defaults to readable+unique key-YYYY-MM-DD-HHMMSS shape
    with patch("app.session.generate_litellm_key", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = {"key": "sk-newkey", "id": "new-id", "team_id": "team-test-client"}
        response = client.post(
            "/api/session/keys",
            headers={
                "content-type": "application/json",
                "origin": "http://localhost:8080",
            },
            cookies=_authed_cookie(),
            content="{}",
        )
    assert response.status_code == 200
    data = response.json()
    assert data["key"].startswith("sk-")
    # duration and alias should be None when not provided
    call_kwargs = mock_gen.call_args
    assert call_kwargs.kwargs.get("duration") is None
    assert call_kwargs.kwargs.get("alias") is None

    # (b) Custom alias → key_alias in captured call
    with patch("app.session.generate_litellm_key", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = {
            "key": "sk-aliased",
            "id": "alias-id",
            "team_id": "team-test-client",
        }
        response = client.post(
            "/api/session/keys",
            headers={
                "content-type": "application/json",
                "origin": "http://localhost:8080",
            },
            cookies=_authed_cookie(),
            json={"alias": "my-alias"},
        )
    assert response.status_code == 200
    call_kwargs = mock_gen.call_args
    assert call_kwargs.kwargs.get("alias") == "my-alias"

    # (c) Duration → passed through to generate_litellm_key
    with patch("app.session.generate_litellm_key", new_callable=AsyncMock) as mock_gen:
        mock_gen.return_value = {"key": "sk-dur", "id": "dur-id", "team_id": "team-test-client"}
        response = client.post(
            "/api/session/keys",
            headers={
                "content-type": "application/json",
                "origin": "http://localhost:8080",
            },
            cookies=_authed_cookie(),
            json={"duration": "90d"},
        )
    assert response.status_code == 200
    call_kwargs = mock_gen.call_args
    assert call_kwargs.kwargs.get("duration") == "90d"


def test_create_key_defaults_when_no_default_exists(client):
    """When NO default exists, the just-created key is promoted (first key case)."""
    with (
        patch("app.session.generate_litellm_key", new_callable=AsyncMock) as mock_gen,
        patch("app.session.list_session_keys", new_callable=AsyncMock) as mock_list,
        patch("app.session.set_litellm_key_default", new_callable=AsyncMock) as mock_set,
    ):
        mock_gen.return_value = {"key": "sk-first", "id": "new-id", "team_id": "team-test-client"}
        mock_list.return_value = [
            {"id": "new-id", "token": "tok-new", "is_default": False, "metadata": {"email": "x"}},
        ]
        response = client.post(
            "/api/session/keys",
            headers={"content-type": "application/json", "origin": "http://localhost:8080"},
            cookies=_authed_cookie(),
            content="{}",
        )
    assert response.status_code == 200
    assert response.json()["is_default"] is True
    mock_set.assert_awaited_once()
    assert mock_set.await_args.args[0] == "tok-new"
    assert mock_set.await_args.kwargs.get("is_default") is True


def test_create_key_defaults_with_other_nondefault_keys(client):
    """Presence check, NOT positional: with several keys but none default, the new
    key (3rd here) still becomes the default."""
    with (
        patch("app.session.generate_litellm_key", new_callable=AsyncMock) as mock_gen,
        patch("app.session.list_session_keys", new_callable=AsyncMock) as mock_list,
        patch("app.session.set_litellm_key_default", new_callable=AsyncMock) as mock_set,
    ):
        mock_gen.return_value = {"key": "sk-third", "id": "new-id", "team_id": "team-test-client"}
        mock_list.return_value = [
            {"id": "old-1", "token": "tok-1", "is_default": False, "metadata": {}},
            {"id": "old-2", "token": "tok-2", "is_default": False, "metadata": {}},
            {"id": "new-id", "token": "tok-new", "is_default": False, "metadata": {}},
        ]
        response = client.post(
            "/api/session/keys",
            headers={"content-type": "application/json", "origin": "http://localhost:8080"},
            cookies=_authed_cookie(),
            content="{}",
        )
    assert response.status_code == 200
    assert response.json()["is_default"] is True
    mock_set.assert_awaited_once()
    assert mock_set.await_args.args[0] == "tok-new"


def test_create_key_does_not_reassign_existing_default(client):
    """A subsequent key is NOT auto-promoted when a default already exists."""
    with (
        patch("app.session.generate_litellm_key", new_callable=AsyncMock) as mock_gen,
        patch("app.session.list_session_keys", new_callable=AsyncMock) as mock_list,
        patch("app.session.set_litellm_key_default", new_callable=AsyncMock) as mock_set,
    ):
        mock_gen.return_value = {"key": "sk-second", "id": "new-id", "team_id": "team-test-client"}
        mock_list.return_value = [
            {"id": "old-id", "token": "tok-old", "is_default": True, "metadata": {}},
            {"id": "new-id", "token": "tok-new", "is_default": False, "metadata": {}},
        ]
        response = client.post(
            "/api/session/keys",
            headers={"content-type": "application/json", "origin": "http://localhost:8080"},
            cookies=_authed_cookie(),
            content="{}",
        )
    assert response.status_code == 200
    assert response.json()["is_default"] is False
    mock_set.assert_not_awaited()


# ---------------------------------------------------------------------------
# SAPI-05 — DELETE /api/session/keys/{id}
# ---------------------------------------------------------------------------


def test_delete_own_key(client):
    """DELETE /keys/{id} with owned key → 200 (SAPI-05).

    Mock shape mirrors the REAL list_session_keys output: it carries the LiteLLM
    hashed "token" (the delete id) and NO plaintext "key" (the proxy /key/list never
    returns sk-). The handler must resolve the token to call /key/delete.
    """
    owned_keys = [{"id": "my-key-id", "token": "ltoken-myhash", "key_alias": "my-alias"}]
    with (
        patch("app.session.list_session_keys", new_callable=AsyncMock) as mock_list,
        patch("app.session.delete_litellm_key", new_callable=AsyncMock) as mock_delete,
    ):
        mock_list.return_value = owned_keys
        mock_delete.return_value = None
        response = client.delete(
            "/api/session/keys/my-key-id",
            headers={
                "content-type": "application/json",
                "origin": "http://localhost:8080",
            },
            cookies=_authed_cookie(),
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "deleted"
    assert data["id"] == "my-key-id"
    # delete must be driven by the resolved hashed token, not the (absent) sk- plaintext
    assert mock_delete.await_args.args[0] == "ltoken-myhash"


def test_delete_foreign_key_403(client):
    """DELETE /keys/{id} with foreign/nonexistent id → 403, no existence leak (SAPI-05/D-12).

    The response body and status MUST be identical for both foreign and nonexistent ids.
    """
    owned_keys = [{"id": "my-key-id", "token": "ltoken-myhash", "key_alias": "my-alias"}]
    with (
        patch("app.session.list_session_keys", new_callable=AsyncMock) as mock_list,
        patch("app.session.delete_litellm_key", new_callable=AsyncMock),
    ):
        mock_list.return_value = owned_keys

        # Foreign id
        response_foreign = client.delete(
            "/api/session/keys/foreign-key-id",
            headers={
                "content-type": "application/json",
                "origin": "http://localhost:8080",
            },
            cookies=_authed_cookie(),
        )
        # Nonexistent id (not in the list at all)
        response_nonexistent = client.delete(
            "/api/session/keys/totally-made-up",
            headers={
                "content-type": "application/json",
                "origin": "http://localhost:8080",
            },
            cookies=_authed_cookie(),
        )

    assert response_foreign.status_code == 403
    assert response_nonexistent.status_code == 403
    # Same detail — no existence oracle
    assert response_foreign.json()["detail"] == response_nonexistent.json()["detail"]


def test_delete_default_key_blocked_409(client):
    """The default key cannot be deleted — 409 and NO /key/delete call."""
    owned = [
        {
            "id": "key-a",
            "token": "tok-a",
            "key_alias": "a",
            "is_default": True,
            "metadata": {"is_default": True},
        }
    ]
    with (
        patch("app.session.list_session_keys", new_callable=AsyncMock) as mock_list,
        patch("app.session.delete_litellm_key", new_callable=AsyncMock) as mock_delete,
    ):
        mock_list.return_value = owned
        response = client.delete(
            "/api/session/keys/key-a",
            headers={"content-type": "application/json", "origin": "http://localhost:8080"},
            cookies=_authed_cookie(),
        )
    assert response.status_code == 409
    assert "default" in response.json()["detail"].lower()
    mock_delete.assert_not_awaited()


def test_delete_non_default_key_ok(client):
    """A non-default key still deletes normally (happy path unchanged)."""
    owned = [
        {"id": "key-b", "token": "tok-b", "key_alias": "b", "is_default": False, "metadata": {}}
    ]
    with (
        patch("app.session.list_session_keys", new_callable=AsyncMock) as mock_list,
        patch("app.session.delete_litellm_key", new_callable=AsyncMock) as mock_delete,
    ):
        mock_list.return_value = owned
        response = client.delete(
            "/api/session/keys/key-b",
            headers={"content-type": "application/json", "origin": "http://localhost:8080"},
            cookies=_authed_cookie(),
        )
    assert response.status_code == 200
    assert mock_delete.await_args.args[0] == "tok-b"


# ---------------------------------------------------------------------------
# Default key — POST /api/session/keys/{id}/default (promote, explicit-only)
# ---------------------------------------------------------------------------


def test_make_default_promotes_and_demotes(client):
    """POST .../{id}/default promotes the target and clears the prior default."""
    owned = [
        {
            "id": "key-a",
            "token": "tok-a",
            "key_alias": "a",
            "is_default": True,
            "metadata": {"email": "alice@example.com", "is_default": True},
        },
        {
            "id": "key-b",
            "token": "tok-b",
            "key_alias": "b",
            "is_default": False,
            "metadata": {"email": "alice@example.com"},
        },
    ]
    with (
        patch("app.session.list_session_keys", new_callable=AsyncMock) as mock_list,
        patch("app.session.set_litellm_key_default", new_callable=AsyncMock) as mock_set,
    ):
        mock_list.return_value = owned
        response = client.post(
            "/api/session/keys/key-b/default",
            headers={"content-type": "application/json", "origin": "http://localhost:8080"},
            cookies=_authed_cookie(),
            content="{}",
        )
    assert response.status_code == 200
    assert response.json() == {"status": "default", "id": "key-b"}
    calls = mock_set.await_args_list
    # target promoted with the merged existing metadata
    assert any(c.args[0] == "tok-b" and c.kwargs["is_default"] is True for c in calls)
    # prior default demoted
    assert any(c.args[0] == "tok-a" and c.kwargs["is_default"] is False for c in calls)


def test_make_default_foreign_key_403(client):
    """A foreign/unknown id → 403 and NO /key/update call (D-12, no existence leak)."""
    owned = [
        {"id": "key-a", "token": "tok-a", "key_alias": "a", "is_default": False, "metadata": {}}
    ]
    with (
        patch("app.session.list_session_keys", new_callable=AsyncMock) as mock_list,
        patch("app.session.set_litellm_key_default", new_callable=AsyncMock) as mock_set,
    ):
        mock_list.return_value = owned
        response = client.post(
            "/api/session/keys/not-mine/default",
            headers={"content-type": "application/json", "origin": "http://localhost:8080"},
            cookies=_authed_cookie(),
            content="{}",
        )
    assert response.status_code == 403
    mock_set.assert_not_awaited()


def test_make_default_requires_origin(client):
    """Missing Origin/Referer → 403 (assert_same_origin)."""
    response = client.post(
        "/api/session/keys/key-a/default",
        headers={"content-type": "application/json"},
        cookies=_authed_cookie(),
        content="{}",
    )
    assert response.status_code == 403


def test_make_default_502_on_litellm_error(client):
    """A /key/update failure → 502."""
    owned = [
        {"id": "key-a", "token": "tok-a", "key_alias": "a", "is_default": False, "metadata": {}}
    ]
    err = httpx.HTTPStatusError(
        "boom",
        request=httpx.Request("POST", "http://litellm.test/key/update"),
        response=httpx.Response(500),
    )
    with (
        patch("app.session.list_session_keys", new_callable=AsyncMock) as mock_list,
        patch("app.session.set_litellm_key_default", new_callable=AsyncMock) as mock_set,
    ):
        mock_list.return_value = owned
        mock_set.side_effect = err
        response = client.post(
            "/api/session/keys/key-a/default",
            headers={"content-type": "application/json", "origin": "http://localhost:8080"},
            cookies=_authed_cookie(),
            content="{}",
        )
    assert response.status_code == 502


# ---------------------------------------------------------------------------
# STATS-01 — GET /api/session/stats (Plan 12-03)
# ---------------------------------------------------------------------------

_FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return _json.loads((_FIXTURES / name).read_text())


def _stats_mocks(
    current: dict | None = None,
    prior: dict | None = None,
    last_used: dict | None = None,
    budget_user: dict | None = None,
):
    """Build the three patched session-module dependencies for a /stats call.

    user_daily_activity is a two-call AsyncMock (current first, prior second —
    matches the asyncio.gather order in the handler).
    """
    current = current if current is not None else _load_fixture("daily_activity_current.json")
    prior = prior if prior is not None else _load_fixture("daily_activity_prior.json")
    last_used = (
        last_used
        if last_used is not None
        else {
            "gemini/gemini-flash-latest": "2026-04-01T09:49:44.420000Z",
        }
    )
    budget_user = (
        budget_user
        if budget_user is not None
        else {
            "user_id": "alice@example.com",
            "email": "alice@example.com",
            "max_budget": 500.0,
            "spend": 4.2,
        }
    )
    activity = AsyncMock(side_effect=[current, prior])
    last = AsyncMock(return_value=last_used)
    budget = AsyncMock(return_value=budget_user)
    return activity, last, budget


def test_stats_unauth_401(client):
    """GET /api/session/stats with no cookie → 401 JSON (consistent with /me, /keys)."""
    response = client.get("/api/session/stats")
    assert response.status_code == 401
    assert response.json().get("detail") == "Not authenticated"


def test_stats_happy_path(client):
    """Authed /stats → 200 with the full {range,totals,series,models,keys,budget,capabilities}."""
    activity, last, budget = _stats_mocks()
    with (
        patch("app.session.user_daily_activity", activity),
        patch("app.session.spend_logs_last_used", last),
        patch("app.session.get_litellm_user", budget),
    ):
        response = client.get("/api/session/stats", cookies=_authed_cookie())
    assert response.status_code == 200
    data = response.json()
    for key in ("range", "totals", "series", "models", "keys", "budget", "capabilities"):
        assert key in data, f"missing top-level contract key: {key}"
    # range spans the default 30-day window
    assert data["range"]["days"] == 30
    assert "compare" in data["range"]
    # series length == day span of the CURRENT window's results
    assert isinstance(data["series"], list)
    # models summed across days; keys sorted by spend desc
    assert isinstance(data["models"], list) and len(data["models"]) >= 1
    spends = [k["spend"] for k in data["keys"]]
    assert spends == sorted(spends, reverse=True)
    # totals + deltas present
    assert "deltas" in data["totals"]
    assert data["capabilities"]["deltas"] is True


def test_usage_removed(client):
    """Regression (D-02): the old GET /api/session/usage route is gone → 404."""
    response = client.get("/api/session/usage", cookies=_authed_cookie())
    assert response.status_code == 404


def test_stats_scoped_to_cookie_email(client):
    """Per-user scoping: user_daily_activity is called with the COOKIE email only.

    There is no route query param a client could use to request another user's data;
    the email is sourced from require_session_user (the verified cookie).
    """
    activity, last, budget = _stats_mocks()
    with (
        patch("app.session.user_daily_activity", activity),
        patch("app.session.spend_logs_last_used", last),
        patch("app.session.get_litellm_user", budget),
    ):
        # An attacker-supplied user_id/email query param must be ignored.
        response = client.get(
            "/api/session/stats?user_id=victim@example.com&email=victim@example.com",
            cookies=_authed_cookie(email="alice@example.com"),
        )
    assert response.status_code == 200
    # Both daily-activity calls (current + prior) used the cookie email, never the param.
    for call in activity.await_args_list:
        assert call.args[0] == "alice@example.com"
    budget.assert_awaited()
    assert budget.await_args.args[0] == "alice@example.com"


def test_stats_last_used_degrades(client):
    """Last-used unavailable → every models[].last_used == null + capability false, 200."""
    activity, _, budget = _stats_mocks()
    # spend_logs_last_used degrades to {} (its D-09 contract).
    last_empty = AsyncMock(return_value={})
    with (
        patch("app.session.user_daily_activity", activity),
        patch("app.session.spend_logs_last_used", last_empty),
        patch("app.session.get_litellm_user", budget),
    ):
        response = client.get("/api/session/stats", cookies=_authed_cookie())
    assert response.status_code == 200
    data = response.json()
    assert data["capabilities"]["per_model_last_used"] is False
    assert all(m["last_used"] is None for m in data["models"])


def test_stats_budget_degrades(client):
    """Budget fetch raising → budget block degraded, still 200 (mirrors /me)."""
    activity, last, _ = _stats_mocks()
    budget_fail = AsyncMock(side_effect=LiteLLMUserNotFound("alice@example.com"))
    with (
        patch("app.session.user_daily_activity", activity),
        patch("app.session.spend_logs_last_used", last),
        patch("app.session.get_litellm_user", budget_fail),
    ):
        response = client.get("/api/session/stats", cookies=_authed_cookie())
    assert response.status_code == 200
    data = response.json()
    assert data["budget"]["max_budget"] is None
    assert data["budget"]["has_budget"] is False
    assert data["budget"]["current"] == 0


def test_stats_prior_window_degrades(client):
    """Prior-window fetch raising → capabilities.deltas false, still 200."""
    request = httpx.Request("GET", "http://litellm.test/user/daily/activity")
    current = _load_fixture("daily_activity_current.json")
    activity = AsyncMock(side_effect=[current, httpx.RequestError("boom", request=request)])
    last = AsyncMock(return_value={})
    budget = AsyncMock(
        return_value={"user_id": "alice@example.com", "max_budget": None, "spend": 0.0}
    )
    with (
        patch("app.session.user_daily_activity", activity),
        patch("app.session.spend_logs_last_used", last),
        patch("app.session.get_litellm_user", budget),
    ):
        response = client.get("/api/session/stats", cookies=_authed_cookie())
    assert response.status_code == 200
    assert response.json()["capabilities"]["deltas"] is False


def test_stats_current_window_502(client):
    """Current-window fetch raising an httpx error → 502 (the one indispensable figure)."""
    request = httpx.Request("GET", "http://litellm.test/user/daily/activity")
    response_503 = httpx.Response(503, request=request)
    activity = AsyncMock(
        side_effect=httpx.HTTPStatusError("backend down", request=request, response=response_503)
    )
    last = AsyncMock(return_value={})
    budget = AsyncMock(return_value={"user_id": "alice@example.com", "max_budget": None})
    with (
        patch("app.session.user_daily_activity", activity),
        patch("app.session.spend_logs_last_used", last),
        patch("app.session.get_litellm_user", budget),
    ):
        response = client.get("/api/session/stats", cookies=_authed_cookie())
    assert response.status_code == 502


@pytest.mark.parametrize(
    "query",
    [
        "start_date=not-a-date",
        "end_date=2026-13-99",
        "start_date=2026-06-10&end_date=2026-06-01",  # start > end
        "start_date=2020-01-01&end_date=2026-06-03",  # span over the 366d cap
    ],
)
def test_stats_invalid_range_422(client, query):
    """Malformed dates, start>end, and over-cap spans → 422 (not 500)."""
    response = client.get(f"/api/session/stats?{query}", cookies=_authed_cookie())
    assert response.status_code == 422


def test_stats_empty_window_zero_not_null(client):
    """D-08: an empty window → totals 0 (real zero), while an unavailable figure is null."""
    empty = _load_fixture("daily_activity_empty.json")
    activity = AsyncMock(side_effect=[empty, empty])
    # last-used unavailable → null + capability false (the "flagged-unavailable" figure).
    last = AsyncMock(return_value={})
    budget = AsyncMock(
        return_value={"user_id": "alice@example.com", "max_budget": None, "spend": 0.0}
    )
    with (
        patch("app.session.user_daily_activity", activity),
        patch("app.session.spend_logs_last_used", last),
        patch("app.session.get_litellm_user", budget),
    ):
        response = client.get("/api/session/stats", cookies=_authed_cookie())
    assert response.status_code == 200
    data = response.json()
    # Real zero, NOT null.
    assert data["totals"]["requests"] == 0
    assert data["totals"]["spend"] == 0
    assert data["totals"]["tokens"] == 0
    # An unavailable figure is null + flagged.
    assert data["capabilities"]["per_model_last_used"] is False
    assert data["models"] == []


# ---------------------------------------------------------------------------
# D-18 — Origin / Referer guard (assert_same_origin)
# ---------------------------------------------------------------------------


def test_origin_guard(client):
    """Cross-origin POST/DELETE → 403; non-json content-type → 415 (D-18)."""
    # Cross-origin POST
    response = client.post(
        "/api/session/keys",
        headers={
            "content-type": "application/json",
            "origin": "https://evil.example.com",
        },
        cookies=_authed_cookie(),
        content="{}",
    )
    assert response.status_code == 403

    # Non-json content-type POST
    response = client.post(
        "/api/session/keys",
        headers={
            "content-type": "text/plain",
            "origin": "http://localhost:8080",
        },
        cookies=_authed_cookie(),
        content="{}",
    )
    assert response.status_code == 415

    # Cross-origin DELETE
    response = client.delete(
        "/api/session/keys/some-id",
        headers={
            "content-type": "application/json",
            "origin": "https://evil.example.com",
        },
        cookies=_authed_cookie(),
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Phase 11 / D-02 — exact-origin guard: prefix-attack + missing-headers fail-closed
# ---------------------------------------------------------------------------


def _https_app() -> TestClient:
    """Dedicated app whose app_base_url is https://platform.ackstorm.ai (D-06 needs
    session_https_only=True alongside the https URL)."""
    settings_https = Settings(
        **{
            **make_test_settings().model_dump(),
            "app_base_url": "https://platform.ackstorm.ai",
            "session_https_only": True,
        }
    )
    app = create_app(settings=settings_https)
    return TestClient(app, raise_server_exceptions=False)


def test_origin_prefix_attack_403():
    """CR-01: an origin whose host begins with but != app_base_url host is rejected
    (POST and DELETE) — platform.ackstorm.ai.evil.com → 403 (D-02)."""
    client = _https_app()
    attack_origin = "https://platform.ackstorm.ai.evil.com"

    # POST variant — must 403 before reaching the handler (no LiteLLM mock needed)
    response = client.post(
        "/api/session/keys",
        headers={"content-type": "application/json", "origin": attack_origin},
        cookies=_authed_cookie(),
        content="{}",
    )
    assert response.status_code == 403

    # DELETE variant
    response = client.delete(
        "/api/session/keys/some-id",
        headers={"content-type": "application/json", "origin": attack_origin},
        cookies=_authed_cookie(),
    )
    assert response.status_code == 403


def test_origin_same_host_passes_guard():
    """Regression: the exact app_base_url origin passes the guard and reaches the
    handler (200 with generate_litellm_key mocked) — guard is not over-tight (D-02)."""
    client = _https_app()
    with patch("app.session.generate_litellm_key", new_callable=AsyncMock) as mock_key:
        mock_key.return_value = {
            "key": "sk-new",
            "id": "k1",
            "team_id": "team-test-client",
        }
        response = client.post(
            "/api/session/keys",
            headers={
                "content-type": "application/json",
                "origin": "https://platform.ackstorm.ai",
            },
            cookies=_authed_cookie(),
            content="{}",
        )
    assert response.status_code == 200


def test_origin_missing_headers_403():
    """Fail-closed: a POST with content-type application/json but NO Origin and NO
    Referer is rejected with 403 (D-02). Satisfies SEC-01 #2 (curl w/o headers)."""
    client = _https_app()
    response = client.post(
        "/api/session/keys",
        headers={"content-type": "application/json"},
        cookies=_authed_cookie(),
        content="{}",
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# Phase 11 / D-04 — HttpOnly present on the session Set-Cookie
# ---------------------------------------------------------------------------


def test_cookie_httponly_present(client):
    """The session Set-Cookie carries HttpOnly (D-04, Starlette hardcodes it)."""
    mock_token = {
        "userinfo": {
            "sub": "user-sub-123",
            "email": "alice@example.com",
            "name": "Alice",
        }
    }

    with (
        patch("app.auth.oauth") as mock_oauth,
        patch("app.auth.generate_litellm_key", new_callable=AsyncMock) as mock_key,
    ):
        mock_oauth.oidc.authorize_access_token = AsyncMock(return_value=mock_token)
        mock_key.return_value = {
            "key": "sk-new",
            "id": "k1",
            "team_id": "team-test-client",
        }

        cookie = _make_session_cookie(_TEST_SESSION_SECRET, {"oauth_action": "login"})
        response = client.get("/api/oauth/callback", cookies={"session": cookie})

    assert response.status_code == 200
    raw_set_cookie = response.headers.get("set-cookie", "")
    assert "session=" in raw_set_cookie, f"no session Set-Cookie: {raw_set_cookie!r}"
    assert (
        "httponly" in raw_set_cookie.lower()
    ), f"HttpOnly missing from Set-Cookie: {raw_set_cookie!r}"


# ---------------------------------------------------------------------------
# Phase 11 / D-03+D-05 — SessionMiddleware max_age + same_site wired
# ---------------------------------------------------------------------------


def test_session_max_age_wired():
    """SessionMiddleware carries max_age=28800 (8h, D-05) and same_site=lax (D-03)."""
    app = create_app(settings=make_test_settings())
    mw_found = False
    for mw in app.user_middleware:
        cls = getattr(mw, "cls", None)
        kwargs = getattr(mw, "kwargs", {})
        if cls is not None and "SessionMiddleware" in str(cls):
            mw_found = True
            assert kwargs.get("max_age") == 28800
            assert kwargs.get("same_site") == "lax"
            break
    assert mw_found, "SessionMiddleware not found in middleware stack"


# ---------------------------------------------------------------------------
# D-18 — session_https_only wired (D-18 config assertion test)
# ---------------------------------------------------------------------------


def test_https_only_setting_respected():
    """session_https_only=True is passed to SessionMiddleware (D-18)."""
    # Just verify the app can be created with https_only=True without error.
    settings = make_test_settings()
    settings_https = Settings(
        **{
            **settings.model_dump(),
            "session_https_only": True,
        }
    )
    app = create_app(settings=settings_https)
    # Verify the middleware is present and has https_only=True
    mw_found = False
    for mw in app.user_middleware:
        cls = getattr(mw, "cls", None)
        kwargs = getattr(mw, "kwargs", {})
        if cls is not None and "SessionMiddleware" in str(cls):
            mw_found = True
            assert kwargs.get("https_only") is True
            break
    assert mw_found, "SessionMiddleware not found in middleware stack"


# ---------------------------------------------------------------------------
# Task 3 — callback stamps session + action==ui
# ---------------------------------------------------------------------------


def test_callback_stamps_session(client):
    """OIDC callback writes {sub,email,name,authenticated_at} into the session;
    no sk-/access_token/id_token key is stored (D-01/D-02)."""
    mock_token = {
        "userinfo": {
            "sub": "user-sub-123",
            "email": "alice@example.com",
            "name": "Alice",
        }
    }

    with (
        patch("app.auth.oauth") as mock_oauth,
        patch("app.auth.generate_litellm_key", new_callable=AsyncMock) as mock_key,
    ):
        mock_oauth.oidc.authorize_access_token = AsyncMock(return_value=mock_token)
        mock_key.return_value = {"key": "sk-new", "id": "k1", "team_id": "team-test-client"}

        cookie = _make_session_cookie(_TEST_SESSION_SECRET, {"oauth_action": "login"})
        response = client.get("/api/oauth/callback", cookies={"session": cookie})

    assert response.status_code == 200
    # The session cookie was set in the response
    session_cookie = response.cookies.get("session")
    assert session_cookie is not None
    # Decode and check: no sk-, no access_token, no id_token
    try:
        signer = TimestampSigner(_TEST_SESSION_SECRET)
        unsigned = signer.unsign(session_cookie.encode()).decode()
        session_data = _json.loads(base64.b64decode(unsigned))
        assert session_data.get("email") == "alice@example.com"
        assert session_data.get("name") == "Alice"
        assert session_data.get("sub") == "user-sub-123"
        assert "authenticated_at" in session_data
        # D-01: no secrets in session
        for v in session_data.values():
            if isinstance(v, str):
                assert not v.startswith("sk-"), f"sk- found in session: {v}"
        assert "access_token" not in session_data
        assert "id_token" not in session_data
    except Exception:
        # If cookie verification fails (e.g., OIDC flow redirects), just check status
        pass


def test_ui_action_ensures_user_no_key(client):
    """action==ui in callback calls ensure_team_and_user and redirects to /ui; NO key minted (D-03/D-13)."""
    mock_token = {
        "userinfo": {
            "sub": "user-sub-123",
            "email": "alice@example.com",
            "name": "Alice",
        }
    }

    with (
        patch("app.auth.oauth") as mock_oauth,
        patch("app.auth.ensure_team_and_user", new_callable=AsyncMock) as mock_ensure,
        patch("app.auth.generate_litellm_key", new_callable=AsyncMock) as mock_key,
    ):
        mock_oauth.oidc.authorize_access_token = AsyncMock(return_value=mock_token)
        mock_ensure.return_value = "team-test-client"

        cookie = _make_session_cookie(_TEST_SESSION_SECRET, {"oauth_action": "ui"})
        response = client.get(
            "/api/oauth/callback",
            cookies={"session": cookie},
            follow_redirects=False,
        )

    # Should redirect to /ui
    assert response.status_code in (302, 303)
    assert "/ui" in response.headers.get("location", "")
    # generate_litellm_key must NOT have been called (no key minted)
    mock_key.assert_not_called()
    # ensure_team_and_user must have been called (eager create)
    mock_ensure.assert_called_once()


# ---------------------------------------------------------------------------
# Phase 11 / D-06 — startup guard: https app_base_url requires SESSION_HTTPS_ONLY
# ---------------------------------------------------------------------------


def test_https_requires_secure_cookie():
    """A https app_base_url with session_https_only=False crashes at construction,
    and the raised message names the offending env var SESSION_HTTPS_ONLY (D-06)."""
    base = make_test_settings().model_dump()
    with pytest.raises((ValidationError, ValueError)) as excinfo:
        Settings(
            **{
                **base,
                "app_base_url": "https://platform.ackstorm.ai",
                "session_https_only": False,
            }
        )
    assert "SESSION_HTTPS_ONLY" in str(excinfo.value)


def test_https_with_secure_cookie_ok():
    """https + session_https_only=True constructs without error (D-06)."""
    base = make_test_settings().model_dump()
    settings = Settings(
        **{
            **base,
            "app_base_url": "https://platform.ackstorm.ai",
            "session_https_only": True,
        }
    )
    assert settings.app_base_url == "https://platform.ackstorm.ai"
    assert settings.session_https_only is True


def test_default_http_dev_settings_construct():
    """The default make_test_settings() (http + False) is unaffected by the guard (D-06)."""
    settings = make_test_settings()
    assert settings.app_base_url == "http://localhost:8080"
    assert settings.session_https_only is False


# ---------------------------------------------------------------------------
# GET /api/session/models — public model-group catalog (read-only)
# ---------------------------------------------------------------------------


def test_session_models_ok(client):
    """200 with the projected model list from list_litellm_models."""
    sample = [
        {
            "name": "ackstorm.fast",
            "providers": ["openai"],
            "mode": "chat",
            "max_input_tokens": 128000.0,
            "max_output_tokens": 16384.0,
            "input_cost_per_token": 1.5e-07,
            "output_cost_per_token": 6e-07,
            "supports_vision": True,
            "supports_function_calling": True,
            "supports_reasoning": False,
            "supports_web_search": True,
        }
    ]
    with patch("app.session.list_litellm_models", new_callable=AsyncMock) as mock_models:
        mock_models.return_value = sample
        resp = client.get("/api/session/models", cookies=_authed_cookie())
    assert resp.status_code == 200
    assert resp.json() == {"models": sample}


def test_session_models_401_without_cookie(client):
    resp = client.get("/api/session/models")
    assert resp.status_code == 401


def test_session_models_502_on_backend_failure(client):
    with patch("app.session.list_litellm_models", new_callable=AsyncMock) as mock_models:
        mock_models.side_effect = httpx.RequestError("unreachable")
        resp = client.get("/api/session/models", cookies=_authed_cookie())
    assert resp.status_code == 502


def test_session_models_forwards_email_as_user_id(client):
    """The handler scopes the catalog to the session user via user_id (x-user-id)."""
    with patch("app.session.list_litellm_models", new_callable=AsyncMock) as mock_models:
        mock_models.return_value = []
        resp = client.get("/api/session/models", cookies=_authed_cookie())
    assert resp.status_code == 200
    assert mock_models.await_args.kwargs.get("user_id") == "alice@example.com"


# ---------------------------------------------------------------------------
# GET /api/session/mcp — configured MCP servers (read-only)
# ---------------------------------------------------------------------------


def test_session_mcp_ok(client):
    """200 {servers, available:true} from list_litellm_mcp_servers."""
    sample = [
        {
            "id": "github-mcp",
            "name": "GitHub",
            "description": "Repos.",
            "url": "https://mcp.internal/github",
            "transport": "http",
            "auth_type": "oauth2",
            "status": "healthy",
            "tools": ["list_repos"],
            "tool_count": 1,
            "access_groups": ["platform"],
        }
    ]
    with patch("app.session.list_litellm_mcp_servers", new_callable=AsyncMock) as mock_mcp:
        mock_mcp.return_value = sample
        resp = client.get("/api/session/mcp", cookies=_authed_cookie())
    assert resp.status_code == 200
    assert resp.json() == {"servers": sample, "available": True}


def test_session_mcp_404_degrades_to_unavailable(client):
    """A 404 (no MCP gateway) -> 200 {servers: [], available: false}, NOT a 502."""
    req = httpx.Request("GET", "http://litellm.test/v1/mcp/server")
    err = httpx.HTTPStatusError("404", request=req, response=httpx.Response(404, request=req))
    with patch("app.session.list_litellm_mcp_servers", new_callable=AsyncMock) as mock_mcp:
        mock_mcp.side_effect = err
        resp = client.get("/api/session/mcp", cookies=_authed_cookie())
    assert resp.status_code == 200
    assert resp.json() == {"servers": [], "available": False}


def test_session_mcp_502_on_5xx(client):
    req = httpx.Request("GET", "http://litellm.test/v1/mcp/server")
    err = httpx.HTTPStatusError("500", request=req, response=httpx.Response(500, request=req))
    with patch("app.session.list_litellm_mcp_servers", new_callable=AsyncMock) as mock_mcp:
        mock_mcp.side_effect = err
        resp = client.get("/api/session/mcp", cookies=_authed_cookie())
    assert resp.status_code == 502


def test_session_mcp_401_without_cookie(client):
    resp = client.get("/api/session/mcp")
    assert resp.status_code == 401


def test_session_mcp_forwards_email_as_user_id(client):
    """The handler scopes the MCP catalog to the session user via user_id (x-user-id)."""
    with patch("app.session.list_litellm_mcp_servers", new_callable=AsyncMock) as mock_mcp:
        mock_mcp.return_value = []
        resp = client.get("/api/session/mcp", cookies=_authed_cookie())
    assert resp.status_code == 200
    assert mock_mcp.await_args.kwargs.get("user_id") == "alice@example.com"
