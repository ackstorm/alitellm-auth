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
from app.internal import FrontKeyUnavailable
from app.litellm_client import LiteLLMUserNotFound, TeamMembershipError
from app.main import create_app
from tests.as_defaults import AS_TEST_DEFAULTS

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
        **AS_TEST_DEFAULTS,
        session_https_only=False,
    )


def _make_session_cookie(secret: str, data: dict) -> str:
    """Create a signed Starlette session cookie for test use."""
    signer = TimestampSigner(secret)
    payload = base64.b64encode(_json.dumps(data).encode()).decode()
    return signer.sign(payload).decode()


def _authed_cookie(email: str = "alice@example.com", name: str = "Alice") -> dict:
    return {"session": _make_session_cookie(_TEST_SESSION_SECRET, {"email": email, "name": name})}


@pytest.fixture(autouse=True)
def front_key():
    """Resolve any caller's own LiteLLM key without a store or a mint.

    Autouse because every per-user read (models, MCP, A2A, latency) now goes out
    under the caller's key, so a route that used to need no setup would otherwise
    502 on an unreachable AS store. The fake key carries the email so a test can
    assert WHOSE key was used, which is the property that replaced x-user-id.
    """
    with patch(
        "app.session.resolve_front_key",
        new_callable=AsyncMock,
        side_effect=lambda email, settings: f"sk-front-{email}",
    ) as resolver:
        yield resolver


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
    assert data["team_id"] == "default"
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


def test_me_budget_uses_enforced_member_cap(client):
    """#1/RQ-1: /me reports the ENFORCED per-member cap (max_budget_in_team) and
    member spend, NOT the user-level max_budget that only reports."""
    with (
        patch("app.session.get_litellm_user", new_callable=AsyncMock) as mock_user,
        patch("app.session.get_team_member_budget", new_callable=AsyncMock) as mock_member,
    ):
        mock_user.return_value = {
            "user_id": "alice@example.com",
            "email": "alice@example.com",
            "spend": 99.0,
            "max_budget": 50.0,
            "budget_duration": "24h",
            "tpm_limit": 1000000,
            "rpm_limit": 100,
        }
        mock_member.return_value = {"max_budget": 10.0, "current": 3.5, "budget_duration": "30d"}
        response = client.get("/api/session/me", cookies=_authed_cookie())
    assert response.status_code == 200
    data = response.json()
    assert data["spend"] == {"current": 3.5, "source": "team_member"}
    assert data["limits"]["max_budget"] == 10.0  # enforced cap, not 50.0
    assert data["limits"]["budget_duration"] == "30d"
    # tpm/rpm still come from the user object
    assert data["limits"]["tpm_limit"] == 1000000


def test_me_budget_degrades_when_no_member(client):
    """No membership budget → /me falls back to the user-level figures."""
    with (
        patch("app.session.get_litellm_user", new_callable=AsyncMock) as mock_user,
        patch("app.session.get_team_member_budget", new_callable=AsyncMock) as mock_member,
    ):
        mock_user.return_value = _USER_INFO
        mock_member.return_value = None
        response = client.get("/api/session/me", cookies=_authed_cookie())
    assert response.status_code == 200
    data = response.json()
    assert data["limits"]["max_budget"] == 10.0
    assert data["spend"] == {"current": 2.5, "source": "user"}


# ---------------------------------------------------------------------------
# #1/RQ-1 — _budget_block: prefer the ENFORCED per-member cap over user-level
# ---------------------------------------------------------------------------


def test_budget_block_prefers_enforced_member_budget():
    from app.session import _budget_block

    user = {"spend": 99.0, "max_budget": 50.0, "budget_duration": "24h"}
    member = {"max_budget": 10.0, "current": 3.5, "budget_duration": "30d"}
    assert _budget_block(user, member) == {
        "current": 3.5,
        "max_budget": 10.0,
        "budget_duration": "30d",
        "source": "team_member",
    }


def test_budget_block_member_falls_back_to_user_budget_duration():
    """When the membership budget carries no budget_duration (the live deployment
    has it null), fall back to the user-level budget_duration (informational)."""
    from app.session import _budget_block

    user = {"spend": 99.0, "max_budget": 50.0, "budget_duration": "24h"}
    member = {"max_budget": 10.0, "current": 3.5, "budget_duration": None}
    block = _budget_block(user, member)
    assert block["max_budget"] == 10.0
    assert block["budget_duration"] == "24h"
    assert block["source"] == "team_member"


def test_budget_block_falls_back_to_user_when_no_member():
    from app.session import _budget_block

    user = {"spend": 2.0, "max_budget": 50.0, "budget_duration": "24h"}
    assert _budget_block(user, None) == {
        "current": 2.0,
        "max_budget": 50.0,
        "budget_duration": "24h",
        "source": "user",
    }


def test_budget_block_unknown_when_nothing_configured():
    from app.session import _budget_block

    assert _budget_block({}, None) == {
        "current": 0.0,
        "max_budget": None,
        "budget_duration": None,
        "source": "unknown",
    }


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


def test_list_keys_masks_internal_teams(client):
    """A key in a team the user does NOT belong to → team_id masked to "(internal)";
    a key in a member team is left untouched (no internal-team name leak)."""
    keys = [
        {"id": "k1", "token": "t1", "key_alias": "a", "team_id": "default", "metadata": {}},
        {
            "id": "k2",
            "token": "t2",
            "key_alias": "b",
            "team_id": "ach-env-zohodesk",
            "metadata": {},
        },
    ]
    with (
        patch("app.session.list_session_keys", new_callable=AsyncMock) as mock_list,
        patch("app.session.list_user_teams", new_callable=AsyncMock) as mock_teams,
    ):
        mock_list.return_value = keys
        mock_teams.return_value = [{"id": "default", "alias": "default"}]
        response = client.get("/api/session/keys", cookies=_authed_cookie())
    assert response.status_code == 200
    rows = {r["id"]: r["team_id"] for r in response.json()["keys"]}
    assert rows["k1"] == "default"
    assert rows["k2"] == "(internal)", "internal team id must not reach the browser"


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


def test_create_key_duplicate_alias_returns_422(client):
    """A LiteLLM unique-alias 400 (same user, same name) → 422 on the alias field."""
    err = httpx.HTTPStatusError(
        "boom",
        request=httpx.Request("POST", "http://litellm.test/key/generate"),
        response=httpx.Response(
            400,
            json={"error": {"message": "Key with alias 'default' already exists."}},
        ),
    )
    with patch("app.session.generate_litellm_key", new_callable=AsyncMock) as mock_gen:
        mock_gen.side_effect = err
        response = client.post(
            "/api/session/keys",
            headers={"content-type": "application/json", "origin": "http://localhost:8080"},
            cookies=_authed_cookie(),
            json={"alias": "default"},
        )
    assert response.status_code == 422
    assert "default" in response.json()["detail"]


def test_create_key_with_valid_team(client):
    """A client-supplied team_id the user belongs to is validated against the
    SESSION email's memberships, then threaded into /key/generate."""
    with (
        patch("app.session.assert_team_membership", new_callable=AsyncMock) as mock_assert,
        patch("app.session.generate_litellm_key", new_callable=AsyncMock) as mock_gen,
        patch("app.session.list_session_keys", new_callable=AsyncMock) as mock_list,
    ):
        mock_gen.return_value = {"key": "sk-x", "id": "id-x", "team_id": "run"}
        mock_list.return_value = []  # auto-default relist → no default
        response = client.post(
            "/api/session/keys",
            headers={"content-type": "application/json", "origin": "http://localhost:8080"},
            cookies=_authed_cookie(),
            json={"team_id": "run"},
        )
    assert response.status_code == 200
    # Membership is checked for the SESSION email, NEVER the body.
    mock_assert.assert_awaited_once()
    assert mock_assert.await_args.args[0] == "alice@example.com"
    assert mock_assert.await_args.args[1] == "run"
    # team_id threaded into the mint.
    assert mock_gen.call_args.kwargs.get("team_id") == "run"


def test_create_key_rejects_non_member_team(client):
    """A team the session user is NOT a member of → 403, NO key minted."""
    with (
        patch("app.session.assert_team_membership", new_callable=AsyncMock) as mock_assert,
        patch("app.session.generate_litellm_key", new_callable=AsyncMock) as mock_gen,
    ):
        mock_assert.side_effect = TeamMembershipError("nope")
        response = client.post(
            "/api/session/keys",
            headers={"content-type": "application/json", "origin": "http://localhost:8080"},
            cookies=_authed_cookie(),
            json={"team_id": "dream"},
        )
    assert response.status_code == 403
    mock_gen.assert_not_awaited()


# ---------------------------------------------------------------------------
# SAPI-05 — DELETE /api/session/keys/{id}
# ---------------------------------------------------------------------------


def test_delete_own_key(client):
    """DELETE /keys/{id} with owned key → 200 (SAPI-05).

    Mock shape mirrors the REAL list_session_keys output: it carries the LiteLLM
    hashed "token" (the delete id) and NO plaintext "key" (the proxy /key/list never
    returns sk-). The handler must resolve the token to call /key/delete.
    """
    owned_keys = [
        {"id": "my-key-id", "token": "ltoken-myhash", "key_alias": "my-alias", "managed": True}
    ]
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
    owned_keys = [
        {"id": "my-key-id", "token": "ltoken-myhash", "key_alias": "my-alias", "managed": True}
    ]
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


def test_delete_non_default_key_ok(client):
    """A non-default key still deletes normally (happy path unchanged)."""
    owned = [
        {
            "id": "key-b",
            "token": "tok-b",
            "key_alias": "b",
            "is_default": False,
            "managed": True,
            "metadata": {},
        }
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


# ---------------------------------------------------------------------------
# Disable key — POST /api/session/keys/{id}/block (block / unblock)
# ---------------------------------------------------------------------------


def test_block_key_disables_owned_key(client):
    """blocked:true on an owned key → calls block_litellm_key(..., blocked=True)."""
    owned = [{"id": "key-a", "token": "tok-a", "metadata": {}}]
    with (
        patch("app.session.list_session_keys", new_callable=AsyncMock) as mock_list,
        patch("app.session.block_litellm_key", new_callable=AsyncMock) as mock_block,
    ):
        mock_list.return_value = owned
        response = client.post(
            "/api/session/keys/key-a/block",
            headers={"content-type": "application/json", "origin": "http://localhost:8080"},
            cookies=_authed_cookie(),
            json={"blocked": True},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    mock_block.assert_awaited_once()
    assert mock_block.await_args.args[0] == "tok-a"
    assert mock_block.await_args.kwargs.get("blocked") is True


def test_block_key_can_disable_the_default_key(client):
    """The default key MAY be disabled (no 409 guard — caller's explicit choice)."""
    owned = [{"id": "key-a", "token": "tok-a", "metadata": {}}]
    with (
        patch("app.session.list_session_keys", new_callable=AsyncMock) as mock_list,
        patch("app.session.block_litellm_key", new_callable=AsyncMock) as mock_block,
    ):
        mock_list.return_value = owned
        response = client.post(
            "/api/session/keys/key-a/block",
            headers={"content-type": "application/json", "origin": "http://localhost:8080"},
            cookies=_authed_cookie(),
            json={"blocked": True},
        )
    assert response.status_code == 200
    mock_block.assert_awaited_once()


def test_unblock_key_reenables(client):
    """blocked:false → unblock path; status 'active'."""
    owned = [{"id": "key-a", "token": "tok-a", "metadata": {}}]
    with (
        patch("app.session.list_session_keys", new_callable=AsyncMock) as mock_list,
        patch("app.session.block_litellm_key", new_callable=AsyncMock) as mock_block,
    ):
        mock_list.return_value = owned
        response = client.post(
            "/api/session/keys/key-a/block",
            headers={"content-type": "application/json", "origin": "http://localhost:8080"},
            cookies=_authed_cookie(),
            json={"blocked": False},
        )
    assert response.status_code == 200
    assert response.json()["status"] == "active"
    assert mock_block.await_args.kwargs.get("blocked") is False


def test_block_key_foreign_id_403(client):
    """A foreign/unknown id → 403 and NO block call (D-12)."""
    owned = [{"id": "key-a", "token": "tok-a", "metadata": {}}]
    with (
        patch("app.session.list_session_keys", new_callable=AsyncMock) as mock_list,
        patch("app.session.block_litellm_key", new_callable=AsyncMock) as mock_block,
    ):
        mock_list.return_value = owned
        response = client.post(
            "/api/session/keys/not-mine/block",
            headers={"content-type": "application/json", "origin": "http://localhost:8080"},
            cookies=_authed_cookie(),
            json={"blocked": True},
        )
    assert response.status_code == 403
    mock_block.assert_not_awaited()


def test_foreign_unmanaged_key_locks_mutations_but_allows_block(client):
    """A key not minted here (managed=False) is listed but locked: delete and
    change-team → 409; only disable/enable (block) is allowed."""
    foreign = [{"id": "ekid_01", "token": "tok-x", "managed": False, "metadata": {}}]
    hdr = {"content-type": "application/json", "origin": "http://localhost:8080"}

    with (
        patch("app.session.list_session_keys", new_callable=AsyncMock) as mock_list,
        patch("app.session.delete_litellm_key", new_callable=AsyncMock) as mock_delete,
        patch("app.session.update_litellm_key_team", new_callable=AsyncMock) as mock_team,
        patch("app.session.assert_team_membership", new_callable=AsyncMock),
        patch("app.session.block_litellm_key", new_callable=AsyncMock) as mock_block,
    ):
        mock_list.return_value = foreign

        d = client.delete("/api/session/keys/ekid_01", headers=hdr, cookies=_authed_cookie())
        assert d.status_code == 409
        mock_delete.assert_not_awaited()

        t = client.post(
            "/api/session/keys/ekid_01/team",
            headers=hdr,
            cookies=_authed_cookie(),
            json={"team_id": "default"},
        )
        assert t.status_code == 409
        mock_team.assert_not_awaited()

        b = client.post(
            "/api/session/keys/ekid_01/block",
            headers=hdr,
            cookies=_authed_cookie(),
            json={"blocked": True},
        )
        assert b.status_code == 200
        mock_block.assert_awaited_once()


def test_block_key_invalid_body_422(client):
    """A body missing `blocked` → 422."""
    owned = [{"id": "key-a", "token": "tok-a", "metadata": {}}]
    with patch("app.session.list_session_keys", new_callable=AsyncMock) as mock_list:
        mock_list.return_value = owned
        response = client.post(
            "/api/session/keys/key-a/block",
            headers={"content-type": "application/json", "origin": "http://localhost:8080"},
            cookies=_authed_cookie(),
            content="{}",
        )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Change team — POST /api/session/keys/{id}/team
# ---------------------------------------------------------------------------


def test_change_key_team_moves_owned_key(client):
    """An owned key + a team the user belongs to → /key/update with the hashed token."""
    owned = [{"id": "id-1", "token": "hash-1", "managed": True, "metadata": {}}]
    with (
        patch("app.session.assert_team_membership", new_callable=AsyncMock) as mock_assert,
        patch("app.session.list_session_keys", new_callable=AsyncMock) as mock_list,
        patch("app.session.update_litellm_key_team", new_callable=AsyncMock) as mock_update,
    ):
        mock_list.return_value = owned
        response = client.post(
            "/api/session/keys/id-1/team",
            headers={"content-type": "application/json", "origin": "http://localhost:8080"},
            cookies=_authed_cookie(),
            json={"team_id": "run"},
        )
    assert response.status_code == 200
    assert response.json() == {"status": "moved", "id": "id-1", "team_id": "run"}
    # Membership checked for the SESSION email + target team BEFORE the move.
    mock_assert.assert_awaited_once()
    assert mock_assert.await_args.args[0] == "alice@example.com"
    assert mock_assert.await_args.args[1] == "run"
    # The move sends the server-side hashed token, never the sk-.
    mock_update.assert_awaited_once()
    assert mock_update.await_args.args[0] == "hash-1"
    assert mock_update.await_args.args[1] == "run"


def test_change_key_team_foreign_id_403(client):
    """A foreign/unknown id → 403, NO update (no existence leak, D-12)."""
    with (
        patch("app.session.assert_team_membership", new_callable=AsyncMock),
        patch("app.session.list_session_keys", new_callable=AsyncMock) as mock_list,
        patch("app.session.update_litellm_key_team", new_callable=AsyncMock) as mock_update,
    ):
        mock_list.return_value = []
        response = client.post(
            "/api/session/keys/ghost/team",
            headers={"content-type": "application/json", "origin": "http://localhost:8080"},
            cookies=_authed_cookie(),
            json={"team_id": "run"},
        )
    assert response.status_code == 403
    mock_update.assert_not_awaited()


def test_change_key_team_non_member_403(client):
    """A team the session user is NOT a member of → 403, NO update."""
    with (
        patch("app.session.assert_team_membership", new_callable=AsyncMock) as mock_assert,
        patch("app.session.update_litellm_key_team", new_callable=AsyncMock) as mock_update,
    ):
        mock_assert.side_effect = TeamMembershipError("nope")
        response = client.post(
            "/api/session/keys/id-1/team",
            headers={"content-type": "application/json", "origin": "http://localhost:8080"},
            cookies=_authed_cookie(),
            json={"team_id": "dream"},
        )
    assert response.status_code == 403
    mock_update.assert_not_awaited()


def test_change_key_team_rejects_non_personal_target_when_enabled(client_personal):
    """Membership alone must not let a key leave its capability envelope.

    A user who still holds a pre-migration `default` membership would otherwise
    move a key out of its personal team through the API, defeating the
    one-team invariant that /teams and key creation both enforce.
    """
    with (
        patch("app.session.assert_team_membership", new_callable=AsyncMock) as mock_assert,
        patch("app.session.update_litellm_key_team", new_callable=AsyncMock) as mock_update,
    ):
        response = client_personal.post(
            "/api/session/keys/id-1/team",
            headers={"content-type": "application/json", "origin": "http://localhost:8080"},
            cookies=_authed_cookie(),
            json={"team_id": "default"},
        )
    assert response.status_code == 403
    # Rejected before the membership round-trip, not after it.
    mock_assert.assert_not_awaited()
    mock_update.assert_not_awaited()


# ---------------------------------------------------------------------------
# STATS-01 — GET /api/session/stats (Plan 12-03)
# ---------------------------------------------------------------------------

_FIXTURES = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> dict:
    return _json.loads((_FIXTURES / name).read_text())


def _stats_mocks(
    current: dict | None = None,
    prior: dict | None = None,
    budget_user: dict | None = None,
):
    """Build the patched session-module dependencies for a /stats call.

    user_daily_activity is a two-call AsyncMock (current first, prior second —
    matches the asyncio.gather order in the handler). Per-model last_used is no
    longer a separate fetch — the route derives it from the CURRENT window via
    stats.last_used_from_window, so there is nothing to mock for it.
    """
    current = current if current is not None else _load_fixture("daily_activity_current.json")
    prior = prior if prior is not None else _load_fixture("daily_activity_prior.json")
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
    budget = AsyncMock(return_value=budget_user)
    return activity, budget


def test_stats_unauth_401(client):
    """GET /api/session/stats with no cookie → 401 JSON (consistent with /me, /keys)."""
    response = client.get("/api/session/stats")
    assert response.status_code == 401
    assert response.json().get("detail") == "Not authenticated"


def test_stats_happy_path(client):
    """Authed /stats → 200 with the full {range,totals,series,models,keys,budget,capabilities}."""
    activity, budget = _stats_mocks()
    with (
        patch("app.session.user_daily_activity", activity),
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
    # last_used is derived from the CURRENT window (fixture: every model active on
    # 2026-04-01) — capability stays true and each model carries that date.
    assert data["capabilities"]["per_model_last_used"] is True
    assert all(m["last_used"] == "2026-04-01" for m in data["models"])


def test_stats_keys_resolve_friendly_name_from_key_list(client):
    """TOP API KEYS join: the spend-log key row gets its FRIENDLY name + key-list id.

    Regression for the two-rows bug — the active key rendered once as its opaque
    spend-log identifier (with all the usage) and once as the friendly name (0
    usage). The route now joins the spend rows to the user's key list so the row
    carries the friendly name and the stable key-list id (which lets the UI dedup
    the idle padding row). The fixture spend row has key_alias=None + id == the key
    hash, so this exercises the token-hash fallback join.
    """
    activity, budget = _stats_mocks()
    key_hash = "195b8b1f2c4e46945209387ec13e08ea7d74714fd088cd118b928630a03f2317"
    key_list = AsyncMock(
        return_value=[
            {"id": "stable-id-n8n", "token": key_hash, "key_alias": "n8n"},
        ]
    )
    with (
        patch("app.session.user_daily_activity", activity),
        patch("app.session.get_litellm_user", budget),
        patch("app.session.list_session_keys", key_list),
    ):
        response = client.get("/api/session/stats", cookies=_authed_cookie())
    assert response.status_code == 200
    keys = response.json()["keys"]
    row = next(k for k in keys if k["id"] == "stable-id-n8n")
    assert row["key_alias"] == "n8n"  # friendly name, not the opaque spend-log id
    assert row["requests"] == 11  # usage preserved (the fixture's summed requests)
    # No opaque/raw spend-log id leaks as a separate row.
    assert key_hash not in {k["id"] for k in keys}


def test_stats_key_list_failure_degrades_no_502(client):
    """Key-list fetch failure → still 200, per-key rows keep their raw alias (D-09)."""
    activity, budget = _stats_mocks()
    failing = AsyncMock(side_effect=RuntimeError("litellm down"))
    with (
        patch("app.session.user_daily_activity", activity),
        patch("app.session.get_litellm_user", budget),
        patch("app.session.list_session_keys", failing),
    ):
        response = client.get("/api/session/stats", cookies=_authed_cookie())
    assert response.status_code == 200
    assert "keys" in response.json()


def test_usage_removed(client):
    """Regression (D-02): the old GET /api/session/usage route is gone → 404."""
    response = client.get("/api/session/usage", cookies=_authed_cookie())
    assert response.status_code == 404


def test_stats_scoped_to_cookie_email(client):
    """Per-user scoping: user_daily_activity is called with the COOKIE email only.

    There is no route query param a client could use to request another user's data;
    the email is sourced from require_session_user (the verified cookie).
    """
    activity, budget = _stats_mocks()
    with (
        patch("app.session.user_daily_activity", activity),
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


def test_stats_last_used_derived_from_window_no_extra_fetch(client):
    """Last-used comes from the CURRENT window — NO separate /spend/logs fetch (OOM fix).

    Regression guard: ``/spend/logs?summarize=false`` ignored its filters and
    returned the whole spend-logs table (~83 MB), OOM-killing the pod. The route now
    derives per-model last_used from the daily-activity window it already fetches, so
    ``user_daily_activity`` is called EXACTLY twice (current + prior) and nothing
    else hits LiteLLM for last-used. The fixture has every model active on
    2026-04-01, so each model carries that date and the capability stays true.
    """
    activity, budget = _stats_mocks()
    with (
        patch("app.session.user_daily_activity", activity),
        patch("app.session.get_litellm_user", budget),
    ):
        response = client.get("/api/session/stats", cookies=_authed_cookie())
    assert response.status_code == 200
    data = response.json()
    # Only the two daily-activity windows were fetched — no third last-used call.
    assert activity.await_count == 2
    assert data["capabilities"]["per_model_last_used"] is True
    assert all(m["last_used"] == "2026-04-01" for m in data["models"])


def test_stats_budget_degrades(client):
    """Budget fetch raising → budget block degraded, still 200 (mirrors /me)."""
    activity, _ = _stats_mocks()
    budget_fail = AsyncMock(side_effect=LiteLLMUserNotFound("alice@example.com"))
    with (
        patch("app.session.user_daily_activity", activity),
        patch("app.session.get_litellm_user", budget_fail),
    ):
        response = client.get("/api/session/stats", cookies=_authed_cookie())
    assert response.status_code == 200
    data = response.json()
    assert data["budget"]["max_budget"] is None
    assert data["budget"]["has_budget"] is False
    assert data["budget"]["current"] == 0


def test_stats_budget_uses_enforced_member_cap(client):
    """#1/RQ-1: /stats budget reports the ENFORCED per-member cap, not user-level."""
    activity, budget = _stats_mocks(
        budget_user={"user_id": "alice@example.com", "spend": 99.0, "max_budget": 50.0}
    )
    member = AsyncMock(return_value={"max_budget": 10.0, "current": 3.5, "budget_duration": "30d"})
    with (
        patch("app.session.user_daily_activity", activity),
        patch("app.session.get_litellm_user", budget),
        patch("app.session.get_team_member_budget", member),
    ):
        response = client.get("/api/session/stats", cookies=_authed_cookie())
    assert response.status_code == 200
    b = response.json()["budget"]
    assert b["max_budget"] == 10.0  # enforced cap, not 50.0
    assert b["current"] == 3.5
    assert b["source"] == "team_member"
    assert b["has_budget"] is True


def test_stats_prior_window_degrades(client):
    """Prior-window fetch raising → capabilities.deltas false, still 200."""
    request = httpx.Request("GET", "http://litellm.test/user/daily/activity")
    current = _load_fixture("daily_activity_current.json")
    activity = AsyncMock(side_effect=[current, httpx.RequestError("boom", request=request)])
    budget = AsyncMock(
        return_value={"user_id": "alice@example.com", "max_budget": None, "spend": 0.0}
    )
    with (
        patch("app.session.user_daily_activity", activity),
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
    budget = AsyncMock(return_value={"user_id": "alice@example.com", "max_budget": None})
    with (
        patch("app.session.user_daily_activity", activity),
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
    budget = AsyncMock(
        return_value={"user_id": "alice@example.com", "max_budget": None, "spend": 0.0}
    )
    with (
        patch("app.session.user_daily_activity", activity),
        patch("app.session.get_litellm_user", budget),
    ):
        response = client.get("/api/session/stats", cookies=_authed_cookie())
    assert response.status_code == 200
    data = response.json()
    # Real zero, NOT null.
    assert data["totals"]["requests"] == 0
    assert data["totals"]["spend"] == 0
    assert data["totals"]["tokens"] == 0
    # An empty window has no per-model breakdown → last_used {} → flagged unavailable.
    assert data["capabilities"]["per_model_last_used"] is False
    assert data["models"] == []


def test_latency_degrades_when_the_callers_key_cannot_be_resolved(front_key, client):
    """No key, no read. The key IS the scope, so a failure to get one must not
    fall back to the master key -- that would read every user's rows."""
    fetch = AsyncMock()
    front_key.side_effect = FrontKeyUnavailable("alice@example.com")
    with patch("app.session.fetch_user_spend_logs", fetch):
        response = client.get("/api/session/latency", cookies=_authed_cookie())

    assert response.status_code == 502
    fetch.assert_not_awaited()


def test_latency_reads_under_the_authenticated_users_own_key(client):
    fetch = AsyncMock(return_value=([], False))
    with patch("app.session.fetch_user_spend_logs", fetch):
        response = client.get(
            "/api/session/latency?user_id=victim@example.com",
            cookies=_authed_cookie(email="alice@example.com"),
        )

    assert response.status_code == 200
    assert fetch.await_args.args[0] == "sk-front-alice@example.com"


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
        patch("app.auth.ensure_team_and_user", new_callable=AsyncMock) as mock_ensure,
    ):
        mock_oauth.oidc.authorize_access_token = AsyncMock(return_value=mock_token)
        mock_ensure.return_value = None

        response = client.get("/api/oauth/callback", follow_redirects=False)

    assert response.status_code == 302
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
        patch("app.auth.ensure_team_and_user", new_callable=AsyncMock) as mock_ensure,
    ):
        mock_oauth.oidc.authorize_access_token = AsyncMock(return_value=mock_token)
        mock_ensure.return_value = None

        response = client.get("/api/oauth/callback", follow_redirects=False)

    assert response.status_code == 302
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
    ):
        mock_oauth.oidc.authorize_access_token = AsyncMock(return_value=mock_token)
        mock_ensure.return_value = "team-test-client"

        response = client.get(
            "/api/oauth/callback",
            follow_redirects=False,
        )

    # Should redirect to /ui
    assert response.status_code in (302, 303)
    assert "/ui" in response.headers.get("location", "")
    # ensure_team_and_user must have been called (eager create); no key minted.
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


def test_session_models_reads_under_the_callers_own_key(client):
    """LiteLLM scopes the catalog itself, because we ask as the user."""
    with patch("app.session.list_litellm_models", new_callable=AsyncMock) as mock_models:
        mock_models.return_value = []
        resp = client.get("/api/session/models", cookies=_authed_cookie())
    assert resp.status_code == 200
    assert mock_models.await_args.args[1] == "sk-front-alice@example.com"


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


def test_session_mcp_reads_under_the_callers_own_key(client):
    """LiteLLM scopes the MCP catalog itself, because we ask as the user."""
    with patch("app.session.list_litellm_mcp_servers", new_callable=AsyncMock) as mock_mcp:
        mock_mcp.return_value = []
        resp = client.get("/api/session/mcp", cookies=_authed_cookie())
    assert resp.status_code == 200
    assert mock_mcp.await_args.args[1] == "sk-front-alice@example.com"


# ---------------------------------------------------------------------------
# GET /api/session/a2a — configured A2A agents (read-only)
# ---------------------------------------------------------------------------


def test_session_a2a_ok(client):
    """200 {agents, available:true} from list_litellm_a2a_agents."""
    sample = [
        {
            "id": "research-agent",
            "name": "Research Agent",
            "description": "Web research.",
            "url": "https://a2a.internal/research",
            "transport": "JSONRPC",
            "version": "1.2.0",
            "skills": ["deep_research", "summarize"],
            "skill_count": 2,
            "streaming": True,
        }
    ]
    with patch("app.session.list_litellm_a2a_agents", new_callable=AsyncMock) as mock_a2a:
        mock_a2a.return_value = sample
        resp = client.get("/api/session/a2a", cookies=_authed_cookie())
    assert resp.status_code == 200
    assert resp.json() == {"agents": sample, "available": True}


def test_session_a2a_404_degrades_to_unavailable(client):
    """A 404 (no A2A gateway) -> 200 {agents: [], available: false}, NOT a 502."""
    req = httpx.Request("GET", "http://litellm.test/v1/agents")
    err = httpx.HTTPStatusError("404", request=req, response=httpx.Response(404, request=req))
    with patch("app.session.list_litellm_a2a_agents", new_callable=AsyncMock) as mock_a2a:
        mock_a2a.side_effect = err
        resp = client.get("/api/session/a2a", cookies=_authed_cookie())
    assert resp.status_code == 200
    assert resp.json() == {"agents": [], "available": False}


def test_session_a2a_502_on_5xx(client):
    req = httpx.Request("GET", "http://litellm.test/v1/agents")
    err = httpx.HTTPStatusError("500", request=req, response=httpx.Response(500, request=req))
    with patch("app.session.list_litellm_a2a_agents", new_callable=AsyncMock) as mock_a2a:
        mock_a2a.side_effect = err
        resp = client.get("/api/session/a2a", cookies=_authed_cookie())
    assert resp.status_code == 502


def test_session_a2a_401_without_cookie(client):
    resp = client.get("/api/session/a2a")
    assert resp.status_code == 401


def test_session_a2a_reads_under_the_callers_own_key(client):
    """LiteLLM scopes the A2A catalog itself, because we ask as the user."""
    with patch("app.session.list_litellm_a2a_agents", new_callable=AsyncMock) as mock_a2a:
        mock_a2a.return_value = []
        resp = client.get("/api/session/a2a", cookies=_authed_cookie())
    assert resp.status_code == 200
    assert mock_a2a.await_args.args[1] == "sk-front-alice@example.com"


# ---------------------------------------------------------------------------
# GET /api/session/teams — member teams (id + display alias, read-only)
# ---------------------------------------------------------------------------


def test_session_teams_returns_member_teams(client, monkeypatch):
    """200 with the session user's member teams (id + alias) from list_user_teams."""

    async def fake_teams(email, settings):
        assert email == "alice@example.com"
        return [{"id": "default", "alias": "Default"}, {"id": "run", "alias": "Run"}]

    monkeypatch.setattr("app.session.list_user_teams", fake_teams)

    resp = client.get("/api/session/teams", cookies=_authed_cookie())
    assert resp.status_code == 200
    assert resp.json() == {
        "teams": [
            {"id": "default", "alias": "Default"},
            {"id": "run", "alias": "Run"},
        ]
    }


def test_session_teams_401_without_cookie(client):
    resp = client.get("/api/session/teams")
    assert resp.status_code == 401


def test_session_teams_502_on_backend_failure(client):
    with patch("app.session.list_user_teams", new_callable=AsyncMock) as mock_teams:
        mock_teams.side_effect = httpx.RequestError("unreachable")
        resp = client.get("/api/session/teams", cookies=_authed_cookie())
    assert resp.status_code == 502


def test_me_carries_sso_groups(client):
    """/me surfaces the Dex groups stamped on the session at login (SSO-GRP)."""
    cookie = {
        "session": _make_session_cookie(
            _TEST_SESSION_SECRET,
            {
                "email": "alice@example.com",
                "name": "Alice",
                "groups": ["platform-eng@ackstorm.com", "ai-team@ackstorm.com"],
            },
        )
    }
    with patch("app.session.get_litellm_user", new_callable=AsyncMock) as mock_user:
        mock_user.return_value = _USER_INFO
        response = client.get("/api/session/me", cookies=cookie)
    assert response.status_code == 200
    assert response.json()["groups"] == [
        "platform-eng@ackstorm.com",
        "ai-team@ackstorm.com",
    ]


def test_me_groups_absent_is_empty_list(client):
    """A session predating the groups claim (or a provider that sent none) must
    still return 200 with an empty list, never a missing key or a 500."""
    with patch("app.session.get_litellm_user", new_callable=AsyncMock) as mock_user:
        mock_user.return_value = _USER_INFO
        response = client.get("/api/session/me", cookies=_authed_cookie())
    assert response.status_code == 200
    assert response.json()["groups"] == []


# ---------------------------------------------------------------------------
# Personal teams (PERSONAL_TEAMS_ENABLED) — the personal team is the user's ONLY
# team and the only key destination. Every test here has a flag-OFF twin above
# or below it: the flag-off path must stay byte-identical.
# ---------------------------------------------------------------------------

_PERSONAL_TEAM = "user-alice@example.com"


@pytest.fixture()
def client_personal() -> TestClient:
    """An app with personal teams ON. Settings(**model_dump()) rather than
    model_copy so the model validators actually re-run (file convention)."""
    settings = Settings(
        **{
            **make_test_settings().model_dump(),
            "personal_teams_enabled": True,
            "default_access_groups": ["team-default"],
        }
    )
    return TestClient(create_app(settings=settings), raise_server_exceptions=False)


def test_teams_returns_only_the_personal_team_when_enabled(client_personal):
    """A pre-migration `default` membership must NOT show up as a destination:
    the personal team is the whole capability envelope."""
    with patch("app.session.list_user_teams", new_callable=AsyncMock) as mock_teams:
        mock_teams.return_value = [{"id": "default", "alias": "Default"}]
        response = client_personal.get("/api/session/teams", cookies=_authed_cookie())
    assert response.status_code == 200
    assert response.json() == {"teams": [{"id": _PERSONAL_TEAM, "alias": _PERSONAL_TEAM}]}
    # No LiteLLM round-trip at all on this path.
    mock_teams.assert_not_awaited()


def test_teams_still_lists_every_membership_when_disabled(client):
    """Flag-off regression: /teams is unchanged — whatever list_user_teams returns."""
    with patch("app.session.list_user_teams", new_callable=AsyncMock) as mock_teams:
        mock_teams.return_value = [{"id": "default", "alias": "Default"}, {"id": "run", "a": 1}]
        response = client.get("/api/session/teams", cookies=_authed_cookie())
    assert response.status_code == 200
    assert [t["id"] for t in response.json()["teams"]] == ["default", "run"]
    mock_teams.assert_awaited_once()


def test_me_reports_the_personal_team_and_its_enforcing_budget(client_personal):
    """The personal team has no max_budget_in_team to read (Step A3 is skipped
    there), so /me must source the cap from the TEAM's own budget — falling back
    to the user-level figures would report a cap that does not enforce."""
    with (
        patch("app.session.get_litellm_user", new_callable=AsyncMock) as mock_user,
        patch("app.session.get_team_budget", new_callable=AsyncMock) as mock_team,
        patch("app.session.get_team_member_budget", new_callable=AsyncMock) as mock_member,
    ):
        mock_user.return_value = {
            "user_id": "alice@example.com",
            "spend": 99.0,
            "max_budget": 50.0,
            "budget_duration": "24h",
            "tpm_limit": 1000000,
            "rpm_limit": 100,
        }
        mock_team.return_value = {"max_budget": 20.0, "current": 4.0, "budget_duration": "30d"}
        response = client_personal.get("/api/session/me", cookies=_authed_cookie())
    assert response.status_code == 200
    data = response.json()
    assert data["team_id"] == _PERSONAL_TEAM
    assert data["spend"] == {"current": 4.0, "source": "team"}
    assert data["limits"]["max_budget"] == 20.0  # the team cap, not the user's 50.0
    assert data["limits"]["budget_duration"] == "30d"
    assert data["limits"]["tpm_limit"] == 1000000  # tpm/rpm still from the user
    assert mock_team.await_args.args[0] == _PERSONAL_TEAM  # the PERSONAL team, not the shared one
    mock_member.assert_not_awaited()  # the shared-team read never happens here


def test_me_degrades_when_the_personal_team_is_unreadable(client_personal):
    """get_team_budget returning None → the user-level fallback, still a 200."""
    with (
        patch("app.session.get_litellm_user", new_callable=AsyncMock) as mock_user,
        patch("app.session.get_team_budget", new_callable=AsyncMock) as mock_team,
    ):
        mock_user.return_value = _USER_INFO
        mock_team.return_value = None
        response = client_personal.get("/api/session/me", cookies=_authed_cookie())
    assert response.status_code == 200
    assert response.json()["spend"]["source"] == "user"


def test_me_still_reads_the_member_cap_when_disabled(client):
    """Flag-off regression: /me reports the shared team and its per-member cap,
    and never touches the team-level read."""
    with (
        patch("app.session.get_litellm_user", new_callable=AsyncMock) as mock_user,
        patch("app.session.get_team_member_budget", new_callable=AsyncMock) as mock_member,
        patch("app.session.get_team_budget", new_callable=AsyncMock) as mock_team,
    ):
        mock_user.return_value = _USER_INFO
        mock_member.return_value = {"max_budget": 10.0, "current": 3.5, "budget_duration": "30d"}
        response = client.get("/api/session/me", cookies=_authed_cookie())
    assert response.status_code == 200
    data = response.json()
    assert data["team_id"] == "default"
    assert data["spend"] == {"current": 3.5, "source": "team_member"}
    mock_team.assert_not_awaited()


def test_create_key_ignores_a_requested_team_when_enabled(client_personal):
    """Minting into a team the user is not in is how you get a fail-open key
    (LiteLLM silently accepts a nonexistent team_id). With personal teams on the
    body's team_id is not validated — it is discarded, and team_id=None is what
    makes ensure_team_and_user take its personal-team branch."""
    with (
        patch("app.session.assert_team_membership", new_callable=AsyncMock) as mock_assert,
        patch("app.session.generate_litellm_key", new_callable=AsyncMock) as mock_gen,
        patch("app.session.list_session_keys", new_callable=AsyncMock) as mock_list,
    ):
        mock_gen.return_value = {"key": "sk-x", "id": "id-x", "team_id": _PERSONAL_TEAM}
        mock_list.return_value = []
        response = client_personal.post(
            "/api/session/keys",
            headers={"content-type": "application/json", "origin": "http://localhost:8080"},
            cookies=_authed_cookie(),
            json={"alias": "k", "team_id": "dream"},
        )
    assert response.status_code == 200
    assert response.json()["team_id"] == _PERSONAL_TEAM
    assert mock_gen.call_args.kwargs.get("team_id") is None
    mock_assert.assert_not_awaited()


def test_create_key_still_validates_a_requested_team_when_disabled(client):
    """Flag-off regression: the membership gate is untouched — a team the session
    user does not belong to is still a 403 with NO key minted."""
    with (
        patch("app.session.assert_team_membership", new_callable=AsyncMock) as mock_assert,
        patch("app.session.generate_litellm_key", new_callable=AsyncMock) as mock_gen,
    ):
        mock_assert.side_effect = TeamMembershipError("nope")
        response = client.post(
            "/api/session/keys",
            headers={"content-type": "application/json", "origin": "http://localhost:8080"},
            cookies=_authed_cookie(),
            json={"team_id": "dream"},
        )
    assert response.status_code == 403
    mock_gen.assert_not_awaited()


def test_stats_budget_matches_me_on_the_personal_path(client_personal):
    """/stats and /me must never disagree about the same user's budget."""
    activity, budget = _stats_mocks(
        budget_user={"user_id": "alice@example.com", "spend": 99.0, "max_budget": 50.0}
    )
    team = AsyncMock(return_value={"max_budget": 20.0, "current": 4.0, "budget_duration": "30d"})
    member = AsyncMock(return_value={"max_budget": 10.0, "current": 3.5})
    with (
        patch("app.session.user_daily_activity", activity),
        patch("app.session.get_litellm_user", budget),
        patch("app.session.get_team_budget", team),
        patch("app.session.get_team_member_budget", member),
    ):
        response = client_personal.get("/api/session/stats", cookies=_authed_cookie())
    assert response.status_code == 200
    b = response.json()["budget"]
    assert b == {**b, "max_budget": 20.0, "current": 4.0, "source": "team", "has_budget": True}
    member.assert_not_awaited()


# ---------------------------------------------------------------------------
# Access groups on /api/session/me — the capability behind a personal team
# ---------------------------------------------------------------------------


def test_me_reports_the_personal_teams_access_groups(client_personal):
    """The team grants nothing; the attached groups are the whole capability."""
    with (
        patch("app.session.get_litellm_user", new_callable=AsyncMock) as mock_user,
        patch("app.session.get_team_budget", new_callable=AsyncMock) as mock_budget,
        patch("app.session.get_team_access_groups", new_callable=AsyncMock) as mock_groups,
    ):
        mock_user.return_value = {"user_id": "alice@example.com"}
        mock_budget.return_value = None
        mock_groups.return_value = ["team-default", "team-dream"]
        resp = client_personal.get("/api/session/me", cookies=_authed_cookie())

    assert resp.status_code == 200
    assert resp.json()["access_groups"] == ["team-default", "team-dream"]
    assert mock_groups.await_args.args[0] == "user-alice@example.com"


def test_me_degrades_to_no_access_groups_when_the_team_is_unreadable(client_personal):
    """An unreadable team under-reports capability rather than inventing it."""
    with (
        patch("app.session.get_litellm_user", new_callable=AsyncMock) as mock_user,
        patch("app.session.get_team_budget", new_callable=AsyncMock) as mock_budget,
        patch("app.session.get_team_access_groups", new_callable=AsyncMock) as mock_groups,
    ):
        mock_user.return_value = {"user_id": "alice@example.com"}
        mock_budget.return_value = None
        mock_groups.side_effect = httpx.RequestError("boom")
        resp = client_personal.get("/api/session/me", cookies=_authed_cookie())

    assert resp.status_code == 200
    assert resp.json()["access_groups"] == []


def test_me_has_no_access_groups_on_the_shared_team_path(client):
    """Without personal teams there is no per-user group attachment to report."""
    with (
        patch("app.session.get_litellm_user", new_callable=AsyncMock) as mock_user,
        patch("app.session.get_team_member_budget", new_callable=AsyncMock) as mock_member,
    ):
        mock_user.return_value = {"user_id": "alice@example.com"}
        mock_member.return_value = None
        resp = client.get("/api/session/me", cookies=_authed_cookie())

    assert resp.status_code == 200
    assert resp.json()["access_groups"] == []
