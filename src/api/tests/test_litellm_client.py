# SPDX-License-Identifier: Apache-2.0
import json as _json

import pytest
import respx
import httpx
from app.litellm_client import (
    generate_litellm_key,
    LiteLLMUserNotFound,
    ensure_litellm_user,
    get_litellm_user,
    list_litellm_users,
    list_litellm_keys,
    delete_litellm_user,
    _normalize_teams,
)


def _json_body(route) -> dict:
    """Decode the JSON body of the last request captured by a respx route."""
    return _json.loads(route.calls.last.request.content)


def make_settings(**kwargs):
    from app.config import Settings

    defaults = dict(
        session_secret_key="x" * 32,
        oauth_issuer_url="http://oidc.test/dex",
        oauth_client_id="platform",
        oauth_client_secret="s",
        litellm_url="http://litellm.test",
        litellm_master_key="sk-admin",
        api_public_url="https://api.test",
    )
    return Settings(**{**defaults, **kwargs})


@pytest.mark.asyncio
@respx.mock
async def test_generate_litellm_key_success():
    settings = make_settings()
    team_id = f"team-{settings.oauth_client_id}"

    respx.post("http://litellm.test/team/new").mock(
        return_value=httpx.Response(200, json={"team_id": team_id})
    )
    respx.post("http://litellm.test/v1/access_group").mock(
        return_value=httpx.Response(200, json={"access_group_id": "group-123"})
    )
    respx.post("http://litellm.test/user/new").mock(
        return_value=httpx.Response(200, json={"user_id": "alice@example.com"})
    )
    respx.post("http://litellm.test/key/generate").mock(
        return_value=httpx.Response(200, json={"key": "sk-generated-key", "key_id": "key-123"})
    )

    result = await generate_litellm_key("alice@example.com", settings)

    assert result["key"] == "sk-generated-key"
    # The ID should now be a SHA256 hash, not the literal 'key-123'
    assert len(result["id"]) == 64
    assert result["id"] != "key-123"
    assert result["team_id"] == team_id


@pytest.mark.asyncio
@respx.mock
async def test_generate_litellm_key_team_id_is_shared():
    """All users get the same team_id, derived from oauth_client_id."""
    settings = make_settings()

    respx.post("http://litellm.test/team/new").mock(
        return_value=httpx.Response(200, json={"team_id": "team-platform"})
    )
    respx.post("http://litellm.test/v1/access_group").mock(
        return_value=httpx.Response(200, json={"access_group_id": "group-123"})
    )
    respx.post("http://litellm.test/user/new").mock(
        return_value=httpx.Response(200, json={"user_id": "alice@example.com"})
    )
    respx.post("http://litellm.test/key/generate").mock(
        return_value=httpx.Response(200, json={"key": "sk-key", "key_id": "key-1"})
    )

    r1 = await generate_litellm_key("alice@example.com", settings)

    # Second call for bob
    respx.post("http://litellm.test/team/new").mock(
        return_value=httpx.Response(409, json={"error": "already exists"})
    )
    respx.post("http://litellm.test/user/new").mock(
        return_value=httpx.Response(200, json={"user_id": "bob@example.com"})
    )
    respx.post("http://litellm.test/key/generate").mock(
        return_value=httpx.Response(200, json={"key": "sk-key2", "key_id": "key-2"})
    )
    r2 = await generate_litellm_key("bob@example.com", settings)

    assert r1["team_id"] == r2["team_id"] == "team-platform"


@pytest.mark.asyncio
@respx.mock
async def test_generate_litellm_key_handles_existing_team_409():
    settings = make_settings()

    respx.post("http://litellm.test/team/new").mock(
        return_value=httpx.Response(409, json={"error": "team already exists"})
    )
    respx.post("http://litellm.test/v1/access_group").mock(
        return_value=httpx.Response(200, json={"access_group_id": "group-123"})
    )
    respx.post("http://litellm.test/user/new").mock(
        return_value=httpx.Response(200, json={"user_id": "alice@example.com"})
    )
    respx.post("http://litellm.test/key/generate").mock(
        return_value=httpx.Response(200, json={"key": "sk-existing-team-key", "key_id": "key-ex"})
    )

    result = await generate_litellm_key("alice@example.com", settings)
    assert result["key"] == "sk-existing-team-key"


@pytest.mark.asyncio
@respx.mock
async def test_generate_litellm_key_handles_existing_team_capitalized_400():
    """WR-04: a 400 with capitalized 'Team Already Exists' is treated as idempotent success."""
    settings = make_settings()

    respx.post("http://litellm.test/team/new").mock(
        return_value=httpx.Response(400, json={"error": {"message": "Team Already Exists"}})
    )
    respx.post("http://litellm.test/v1/access_group").mock(
        return_value=httpx.Response(200, json={"access_group_id": "group-123"})
    )
    respx.post("http://litellm.test/user/new").mock(
        return_value=httpx.Response(200, json={"user_id": "alice@example.com"})
    )
    respx.post("http://litellm.test/key/generate").mock(
        return_value=httpx.Response(200, json={"key": "sk-cap-team-key", "key_id": "key-cap"})
    )

    result = await generate_litellm_key("alice@example.com", settings)
    assert result["key"] == "sk-cap-team-key"


@pytest.mark.asyncio
@respx.mock
async def test_generate_litellm_key_raises_on_key_error():
    settings = make_settings()

    respx.post("http://litellm.test/team/new").mock(
        return_value=httpx.Response(200, json={"team_id": "team-platform"})
    )
    respx.post("http://litellm.test/v1/access_group").mock(
        return_value=httpx.Response(200, json={"access_group_id": "group-123"})
    )
    respx.post("http://litellm.test/user/new").mock(
        return_value=httpx.Response(200, json={"user_id": "alice@example.com"})
    )
    respx.post("http://litellm.test/key/generate").mock(
        return_value=httpx.Response(500, json={"error": "internal error"})
    )

    with pytest.raises(httpx.HTTPStatusError):
        await generate_litellm_key("alice@example.com", settings)


# ── User lifecycle tests ────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_ensure_litellm_user_creates():
    settings = make_settings()
    route = respx.post("http://litellm.test/user/new").mock(
        return_value=httpx.Response(200, json={"user_id": "alice@example.com"})
    )
    out = await ensure_litellm_user(
        "alice@example.com", settings, name="Alice", team_id="team-platform"
    )
    assert route.called
    body = _json_body(route)
    assert body["user_id"] == "alice@example.com"
    assert body["user_email"] == "alice@example.com"
    assert body["teams"] == ["team-platform"]
    assert body["auto_create_key"] is False
    assert out["user_id"] == "alice@example.com"


@pytest.mark.asyncio
@respx.mock
async def test_ensure_litellm_user_idempotent_on_already_exists():
    settings = make_settings()
    respx.post("http://litellm.test/user/new").mock(
        return_value=httpx.Response(400, json={"error": {"message": "User already exists"}})
    )
    out = await ensure_litellm_user("alice@example.com", settings)
    assert out["user_id"] == "alice@example.com"
    assert out.get("existed") is True


@pytest.mark.asyncio
@respx.mock
async def test_ensure_litellm_user_raises_on_real_error():
    settings = make_settings()
    respx.post("http://litellm.test/user/new").mock(
        return_value=httpx.Response(500, json={"error": {"message": "boom"}})
    )
    with pytest.raises(httpx.HTTPStatusError):
        await ensure_litellm_user("alice@example.com", settings)


@pytest.mark.asyncio
@respx.mock
async def test_get_litellm_user_normalizes():
    settings = make_settings()
    respx.get("http://litellm.test/user/info").mock(
        return_value=httpx.Response(
            200,
            json={
                "user_id": "alice@example.com",
                "user_info": {
                    "user_id": "alice@example.com",
                    "user_email": "alice@example.com",
                    "user_alias": "Alice",
                    "user_role": "internal_user",
                    "spend": 2.5,
                    "max_budget": 10.0,
                    "teams": ["team-platform"],
                },
            },
        )
    )
    user = await get_litellm_user("alice@example.com", settings)
    assert user["user_id"] == "alice@example.com"
    assert user["email"] == "alice@example.com"
    assert user["role"] == "internal_user"
    assert user["spend"] == 2.5


@pytest.mark.parametrize(
    "raw",
    [
        {"team_id": "team-platform", "team_alias": "platform"},  # single dict
        "team-platform,team-other",  # comma-joined string
        42,  # scalar
    ],
)
def test_normalize_teams_degrades_on_non_list(raw):
    """WR-03: non-list 'teams' shapes degrade to None instead of raising TypeError."""
    assert _normalize_teams(raw) is None


def test_normalize_teams_none_and_list():
    """Sanity: None stays None; a well-formed list is projected to alias-preferred strings."""
    assert _normalize_teams(None) is None
    assert _normalize_teams([{"team_id": "t1", "team_alias": "alias1"}, "t2"]) == ["alias1", "t2"]


@pytest.mark.asyncio
@respx.mock
async def test_get_litellm_user_teams_as_objects():
    """H2: /user/info returns teams as [{team_id, team_alias}] objects."""
    settings = make_settings()
    respx.get("http://litellm.test/user/info").mock(
        return_value=httpx.Response(
            200,
            json={
                "user_info": {
                    "user_id": "alice@example.com",
                    "user_email": "alice@example.com",
                    "teams": [{"team_id": "team-platform", "team_alias": "platform"}],
                },
            },
        )
    )
    user = await get_litellm_user("alice@example.com", settings)
    assert user["teams"] == ["platform"]  # alias preferred over id


@pytest.mark.asyncio
@respx.mock
async def test_get_litellm_user_placeholder_falls_back_to_list():
    """H1: /user/info answers 200 + default_user_id; /user/list is authoritative."""
    settings = make_settings()
    respx.get("http://litellm.test/user/info").mock(
        return_value=httpx.Response(
            200,
            json={
                "user_id": "default_user_id",
                "user_email": None,
            },
        )
    )
    respx.get("http://litellm.test/user/list").mock(
        return_value=httpx.Response(
            200,
            json={
                "users": [
                    {
                        "user_id": "alice@example.com",
                        "user_email": "alice@example.com",
                        "user_role": "internal_user",
                    },
                ]
            },
        )
    )
    user = await get_litellm_user("alice@example.com", settings)
    assert user["user_id"] == "alice@example.com"
    assert user["role"] == "internal_user"


@pytest.mark.asyncio
@respx.mock
async def test_get_litellm_user_not_found_raises():
    """H1: placeholder + empty /user/list → LiteLLMUserNotFound (not a bogus 200)."""
    settings = make_settings()
    respx.get("http://litellm.test/user/info").mock(
        return_value=httpx.Response(200, json={"user_id": "default_user_id", "user_email": None})
    )
    respx.get("http://litellm.test/user/list").mock(
        return_value=httpx.Response(200, json={"users": []})
    )
    with pytest.raises(LiteLLMUserNotFound):
        await get_litellm_user("ghost@example.com", settings)


@pytest.mark.asyncio
@respx.mock
async def test_list_litellm_users():
    settings = make_settings()
    respx.get("http://litellm.test/user/list").mock(
        return_value=httpx.Response(
            200,
            json={
                "users": [
                    {"user_id": "a@x.com", "user_email": "a@x.com", "user_role": "internal_user"},
                    {"user_id": "b@x.com", "user_email": "b@x.com", "user_role": "proxy_admin"},
                ]
            },
        )
    )
    users = await list_litellm_users(settings)
    assert {u["user_id"] for u in users} == {"a@x.com", "b@x.com"}


@pytest.mark.asyncio
@respx.mock
async def test_delete_litellm_user():
    settings = make_settings()
    route = respx.post("http://litellm.test/user/delete").mock(
        return_value=httpx.Response(200, json={"deleted_users": ["alice@example.com"]})
    )
    await delete_litellm_user("alice@example.com", settings)
    assert _json_body(route)["user_ids"] == ["alice@example.com"]


@pytest.mark.asyncio
@respx.mock
async def test_generate_litellm_key_scopes_key_to_user():
    """Generated key payload includes user_id=email (USER-02) and the user ensure call is made (USER-01)."""
    settings = make_settings()
    team_id = f"team-{settings.oauth_client_id}"

    respx.post("http://litellm.test/team/new").mock(
        return_value=httpx.Response(200, json={"team_id": team_id})
    )
    respx.post("http://litellm.test/v1/access_group").mock(
        return_value=httpx.Response(200, json={"access_group_id": "group-123"})
    )
    user_route = respx.post("http://litellm.test/user/new").mock(
        return_value=httpx.Response(200, json={"user_id": "alice@example.com"})
    )
    key_route = respx.post("http://litellm.test/key/generate").mock(
        return_value=httpx.Response(200, json={"key": "sk-scoped-key", "key_id": "key-scoped"})
    )

    result = await generate_litellm_key("alice@example.com", settings)

    assert result["key"] == "sk-scoped-key"
    assert user_route.called
    key_body = _json_body(key_route)
    assert key_body["user_id"] == "alice@example.com"
    assert key_body["team_id"] == team_id


@pytest.mark.asyncio
@respx.mock
async def test_list_litellm_keys_raises_when_string_key_hydration_fails():
    """WR-06: a hydration failure on a string key must not be silently swallowed.

    The listing feeds delete_token's ownership check, where a dropped key the
    user owns becomes a spurious 404. A backend error must propagate instead.
    """
    settings = make_settings()

    respx.get("http://litellm.test/key/list").mock(
        return_value=httpx.Response(200, json={"keys": ["sk-opaque-token"]})
    )
    # Hydration of the string token fails with a backend 5xx.
    respx.get("http://litellm.test/key/info").mock(
        return_value=httpx.Response(500, json={"error": {"message": "boom"}})
    )

    with pytest.raises(httpx.HTTPStatusError):
        await list_litellm_keys("alice@example.com", settings)


@pytest.mark.asyncio
@respx.mock
async def test_list_litellm_keys_hydrates_string_keys_on_success():
    """WR-06 regression guard: the happy string-hydration path still filters by email."""
    settings = make_settings()

    respx.get("http://litellm.test/key/list").mock(
        return_value=httpx.Response(200, json={"keys": ["sk-opaque-token"]})
    )
    respx.get("http://litellm.test/key/info").mock(
        return_value=httpx.Response(
            200,
            json={
                "info": {
                    "key": "sk-opaque-token",
                    "metadata": {"email": "alice@example.com", "name": "Alice"},
                }
            },
        )
    )

    keys = await list_litellm_keys("alice@example.com", settings)
    assert len(keys) == 1
    assert keys[0]["email"] == "alice@example.com"
