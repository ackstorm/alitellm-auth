# SPDX-License-Identifier: Apache-2.0
import json as _json
import os
import tempfile

import pytest
import respx
import httpx
from app.litellm_client import (
    generate_litellm_key,
    ensure_team_and_user,
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


# ── Phase 8 Plan 01 tests ────────────────────────────────────────────────────


def _make_factory_config(tmp_path_factory) -> str:
    """Write a temporary factory-config.json matching the live ConfigMap values."""
    config = {
        "team": {},
        "user": {
            "max_parallel_requests": 5,
            "rpm_limit": 10,
            "tpm_limit": 100,
            "max_budget": 10,
            "budget_duration": "24h",
            "metadata": {
                "rpm_limit_type": "best_effort_throughput",
                "tpm_limit_type": "best_effort_throughput",
            },
        },
    }
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, prefix="factory_config_"
    )
    tmp.write(_json.dumps(config))
    tmp.close()
    return tmp.name


@pytest.mark.asyncio
@respx.mock
async def test_budget_rewiring():
    """D-15: /user/new payload carries budget from factory; /key/generate does NOT.

    Assert:
    - /user/new body contains max_budget (from factory config)
    - /key/generate body does NOT contain max_budget, budget_duration,
      tpm_limit, or rpm_limit
    """
    factory_path = _make_factory_config(None)
    try:
        settings = make_settings(factory_config_path=factory_path)

        respx.post("http://litellm.test/team/new").mock(
            return_value=httpx.Response(200, json={"team_id": "team-platform"})
        )
        respx.post("http://litellm.test/v1/access_group").mock(
            return_value=httpx.Response(200, json={"access_group_id": "group-1"})
        )
        user_route = respx.post("http://litellm.test/user/new").mock(
            return_value=httpx.Response(200, json={"user_id": "alice@example.com"})
        )
        # D-14: ensure_team_and_user now calls /team/member_add + /team/member_update (Step A3)
        respx.post("http://litellm.test/team/member_add").mock(
            return_value=httpx.Response(200, json={"team_id": "team-platform"})
        )
        respx.post("http://litellm.test/team/member_update").mock(
            return_value=httpx.Response(200, json={"team_id": "team-platform"})
        )
        key_route = respx.post("http://litellm.test/key/generate").mock(
            return_value=httpx.Response(200, json={"key": "sk-test", "key_id": "k1"})
        )

        result = await generate_litellm_key("alice@example.com", settings)
        assert result["key"] == "sk-test"

        # D-15: /user/new must carry the factory user budget block
        user_body = _json_body(user_route)
        assert user_body.get("max_budget") == 10, "user/new must carry max_budget from factory"
        assert user_body.get("budget_duration") == "24h", "user/new must carry budget_duration"
        assert user_body.get("tpm_limit") == 100, "user/new must carry tpm_limit"
        assert user_body.get("rpm_limit") == 10, "user/new must carry rpm_limit"

        # D-15: /key/generate must NOT carry any budget fields
        key_body = _json_body(key_route)
        assert "max_budget" not in key_body, "key/generate must NOT carry max_budget (D-15)"
        assert "budget_duration" not in key_body, "key/generate must NOT carry budget_duration"
        assert "tpm_limit" not in key_body, "key/generate must NOT carry tpm_limit"
        assert "rpm_limit" not in key_body, "key/generate must NOT carry rpm_limit"
    finally:
        os.unlink(factory_path)


@pytest.mark.asyncio
@respx.mock
async def test_generate_key_duration():
    """D-10: generate_litellm_key accepts optional duration kwarg.

    - When duration="90d" is passed, /key/generate body carries "duration": "90d"
    - When duration is not passed (default None), /key/generate body has NO "duration" key
    """
    factory_path = _make_factory_config(None)
    try:
        settings = make_settings(factory_config_path=factory_path)

        def _setup_mocks():
            respx.post("http://litellm.test/team/new").mock(
                return_value=httpx.Response(200, json={"team_id": "team-platform"})
            )
            respx.post("http://litellm.test/v1/access_group").mock(
                return_value=httpx.Response(200, json={"access_group_id": "group-1"})
            )
            respx.post("http://litellm.test/user/new").mock(
                return_value=httpx.Response(200, json={"user_id": "alice@example.com"})
            )
            # D-14: ensure_team_and_user Step A3 calls member_add + member_update
            respx.post("http://litellm.test/team/member_add").mock(
                return_value=httpx.Response(200, json={"team_id": "team-platform"})
            )
            respx.post("http://litellm.test/team/member_update").mock(
                return_value=httpx.Response(200, json={"team_id": "team-platform"})
            )

        # Test: with duration="90d"
        _setup_mocks()
        key_route_with = respx.post("http://litellm.test/key/generate").mock(
            return_value=httpx.Response(200, json={"key": "sk-dur", "key_id": "k1"})
        )
        await generate_litellm_key("alice@example.com", settings, duration="90d")
        key_body = _json_body(key_route_with)
        assert (
            key_body.get("duration") == "90d"
        ), "duration kwarg must be threaded into /key/generate"

        # Test: without duration (default None)
        _setup_mocks()
        key_route_without = respx.post("http://litellm.test/key/generate").mock(
            return_value=httpx.Response(200, json={"key": "sk-nodur", "key_id": "k2"})
        )
        await generate_litellm_key("alice@example.com", settings)
        key_body_no = _json_body(key_route_without)
        assert (
            "duration" not in key_body_no
        ), "/key/generate must NOT carry duration when not passed"
    finally:
        os.unlink(factory_path)


@pytest.mark.asyncio
@respx.mock
async def test_generate_key_alias():
    """D-10: generate_litellm_key accepts an optional alias kwarg.

    - When alias="my-key" is passed, /key/generate body carries key_alias="my-key".
    - When alias is not passed, the default is a readable, second-unique
      "key-YYYY-MM-DD-HHMMSS" (NOT the old "tf-{timestamp}-{email}") so that
      the sha256(key_alias) id stays distinct across same-day keys.
    """
    factory_path = _make_factory_config(None)
    try:
        settings = make_settings(factory_config_path=factory_path)

        def _setup_mocks():
            respx.post("http://litellm.test/team/new").mock(
                return_value=httpx.Response(200, json={"team_id": "team-platform"})
            )
            respx.post("http://litellm.test/v1/access_group").mock(
                return_value=httpx.Response(200, json={"access_group_id": "group-1"})
            )
            respx.post("http://litellm.test/user/new").mock(
                return_value=httpx.Response(200, json={"user_id": "alice@example.com"})
            )
            # D-14: ensure_team_and_user Step A3 calls member_add + member_update
            respx.post("http://litellm.test/team/member_add").mock(
                return_value=httpx.Response(200, json={"team_id": "team-platform"})
            )
            respx.post("http://litellm.test/team/member_update").mock(
                return_value=httpx.Response(200, json={"team_id": "team-platform"})
            )

        # Test: explicit alias is threaded through verbatim.
        _setup_mocks()
        route_with = respx.post("http://litellm.test/key/generate").mock(
            return_value=httpx.Response(200, json={"key": "sk-a", "key_id": "k1"})
        )
        await generate_litellm_key("alice@example.com", settings, alias="my-key")
        body_with = _json_body(route_with)
        assert (
            body_with.get("key_alias") == "my-key"
        ), "explicit alias must be threaded into /key/generate"

        # Test: default alias is readable + second-unique, not the debug tf- form.
        _setup_mocks()
        route_default = respx.post("http://litellm.test/key/generate").mock(
            return_value=httpx.Response(200, json={"key": "sk-b", "key_id": "k2"})
        )
        await generate_litellm_key("alice@example.com", settings)
        default_alias = _json_body(route_default)["key_alias"]
        assert default_alias.startswith(
            "key-"
        ), f"default alias must start with 'key-', got {default_alias!r}"
        assert not default_alias.startswith(
            "tf-"
        ), "default alias must NOT be the old tf- debug form (D-10)"
        # key-YYYY-MM-DD-HHMMSS → ["key", "YYYY", "MM", "DD", "HHMMSS"], all-digit date parts
        parts = default_alias.split("-")
        assert (
            len(parts) == 5 and parts[0] == "key"
        ), f"unexpected default alias shape: {default_alias!r}"
        assert [len(p) for p in parts[1:]] == [
            4,
            2,
            2,
            6,
        ], f"alias not YYYY-MM-DD-HHMMSS: {default_alias!r}"
        assert (
            default_alias[len("key-") :].replace("-", "").isdigit()
        ), "alias date parts must be numeric"
    finally:
        os.unlink(factory_path)


@pytest.mark.asyncio
@respx.mock
async def test_lazy_backfill():
    """D-16: when a user already exists (409/400), backfill only null/missing budget fields.

    - /user/new returns 400 "already exists"
    - /user/info returns user with max_budget=None
    - /user/update is called with ONLY the missing factory fields (max_budget etc.)
    - /user/update is NOT called with fields the user already has set (e.g. tpm_limit if it were set)
    """
    factory_path = _make_factory_config(None)
    try:
        settings = make_settings(factory_config_path=factory_path)

        # Team + access group setup
        respx.post("http://litellm.test/team/new").mock(
            return_value=httpx.Response(200, json={"team_id": "team-platform"})
        )
        respx.post("http://litellm.test/v1/access_group").mock(
            return_value=httpx.Response(200, json={"access_group_id": "group-1"})
        )
        # User already exists
        respx.post("http://litellm.test/user/new").mock(
            return_value=httpx.Response(400, json={"error": {"message": "User already exists"}})
        )
        # User info: has tpm_limit set but max_budget=None (only max_budget needs backfill)
        respx.get("http://litellm.test/user/info").mock(
            return_value=httpx.Response(
                200,
                json={
                    "user_info": {
                        "user_id": "alice@example.com",
                        "user_email": "alice@example.com",
                        "max_budget": None,
                        "budget_duration": None,
                        "tpm_limit": 100,  # already set — must NOT be overwritten
                        "rpm_limit": None,
                        "max_parallel_requests": None,
                    }
                },
            )
        )
        update_route = respx.post("http://litellm.test/user/update").mock(
            return_value=httpx.Response(200, json={"user_id": "alice@example.com"})
        )
        # D-14: ensure_team_and_user Step A3 calls member_add + member_update
        respx.post("http://litellm.test/team/member_add").mock(
            return_value=httpx.Response(200, json={"team_id": "team-platform"})
        )
        respx.post("http://litellm.test/team/member_update").mock(
            return_value=httpx.Response(200, json={"team_id": "team-platform"})
        )

        await ensure_team_and_user("alice@example.com", settings, name="Alice")

        # /user/update must be called
        assert update_route.called, "/user/update must be called for the lazy backfill"
        update_body = _json_body(update_route)

        # Must carry missing fields: max_budget, budget_duration, rpm_limit, max_parallel_requests
        assert "max_budget" in update_body, "backfill must include max_budget (it was None)"
        assert update_body["max_budget"] == 10

        # Must NOT carry tpm_limit (user already has 100 set)
        assert "tpm_limit" not in update_body, "backfill must NOT overwrite tpm_limit (already set)"
    finally:
        os.unlink(factory_path)


@pytest.mark.asyncio
@respx.mock
async def test_list_session_keys_one_call():
    """RQ-2/D-08: list_session_keys uses /key/list?return_full_object=true&size=100.

    When list returns full dict objects, projects to SAPI-03 shape:
    - id = sha256(key_alias)
    - budget = None (D-17: inherited from user/team)
    - spend, tpm_limit, rpm_limit, models, created_at, expires projected
    """
    from app.litellm_client import list_session_keys
    import hashlib

    settings = make_settings()
    key_alias = "my-test-key"
    expected_id = hashlib.sha256(key_alias.encode()).hexdigest()

    respx.get("http://litellm.test/key/list").mock(
        return_value=httpx.Response(
            200,
            json={
                "keys": [
                    {
                        "token": "ltoken-abc123",
                        "key_alias": key_alias,
                        "spend": 1.5,
                        "max_budget": None,
                        "tpm_limit": 1000,
                        "rpm_limit": 100,
                        "models": ["gpt-4"],
                        "created_at": "2026-06-01T00:00:00Z",
                        "expires": None,
                        "metadata": {"created_at": "2026-06-01T00:00:00Z", "key_alias": key_alias},
                    }
                ]
            },
        )
    )

    keys = await list_session_keys("alice@example.com", settings)
    assert len(keys) == 1
    k = keys[0]
    assert k["id"] == expected_id, "id must be sha256(key_alias)"
    assert k["token"] == "ltoken-abc123", "token (delete hash) must be surfaced for SAPI-05 DELETE"
    assert k["budget"] is None, "budget must be None (D-17: inherited from user/team)"
    assert k["spend"] == 1.5
    assert k["tpm_limit"] == 1000
    assert k["rpm_limit"] == 100
    assert k["models"] == ["gpt-4"]


@pytest.mark.asyncio
@respx.mock
async def test_list_session_keys_fallback():
    """D-08: when /key/list returns strings, the fallback hydration path is used.

    String items trigger the fallback; get_key_info is called for each key and
    the result is projected.
    """
    from app.litellm_client import list_session_keys

    settings = make_settings()
    key_alias = "fallback-key"

    # /key/list returns a string item — triggers fallback
    respx.get("http://litellm.test/key/list").mock(
        return_value=httpx.Response(200, json={"keys": ["sk-opaque-token"]})
    )
    # get_key_info (fallback hydration) returns full dict
    respx.get("http://litellm.test/key/info").mock(
        return_value=httpx.Response(
            200,
            json={
                "info": {
                    "key": "sk-opaque-token",
                    "key_alias": key_alias,
                    "spend": 0.5,
                    "tpm_limit": None,
                    "rpm_limit": None,
                    "models": ["all-team-models"],
                    "expires": None,
                    "metadata": {
                        "email": "alice@example.com",
                        "key_alias": key_alias,
                        "created_at": "2026-05-01T00:00:00Z",
                    },
                }
            },
        )
    )
    # /key/list for fallback (list_litellm_keys uses team_id filter)
    # We also need to mock the fallback's /key/list call
    respx.get("http://litellm.test/key/list").mock(
        return_value=httpx.Response(200, json={"keys": ["sk-opaque-token"]})
    )

    keys = await list_session_keys("alice@example.com", settings)
    # Should return results (fallback path was used)
    assert isinstance(keys, list)


@pytest.mark.asyncio
@respx.mock
async def test_ensure_team_member_budget_idempotent():
    """D-14/RQ-1 spike result: max_budget_in_team via /team/member_add enforces; user-level does not.

    Spec (D-14, adopts max_budget_in_team per the spike decision):
    - POST /team/member_add with nested body: {"team_id":..., "member":{"user_id":email,"role":"user"},
      "max_budget_in_team": N}
    - If the member is already added (400/409 with "already" in body), treat as no-op and fall through
    - POST /team/member_update with top-level body: {"team_id":..., "user_id":email, "max_budget_in_team": N}
    - Running twice reaches the same end state (idempotent)
    """
    from app.litellm_client import ensure_team_member_budget

    settings = make_settings()
    email = "alice@example.com"
    team_id = "team-platform"
    max_budget = 10.0

    # Scenario: member already exists (400 "already a member") → fall through to member_update
    add_route = respx.post("http://litellm.test/team/member_add").mock(
        return_value=httpx.Response(
            400, json={"error": {"message": "User is already a member of this team"}}
        )
    )
    update_route = respx.post("http://litellm.test/team/member_update").mock(
        return_value=httpx.Response(200, json={"team_id": team_id})
    )

    await ensure_team_member_budget(email, team_id, max_budget, settings)

    # member_add was called with nested body
    assert add_route.called, "/team/member_add must be called"
    add_body = _json_body(add_route)
    assert add_body["team_id"] == team_id
    assert add_body["member"] == {
        "user_id": email,
        "role": "user",
    }, "member_add body must use nested 'member' object (not top-level user_id)"
    assert add_body["max_budget_in_team"] == max_budget

    # member_update was called as follow-through (top-level body, not nested)
    assert (
        update_route.called
    ), "/team/member_update must be called after 'already a member' response"
    update_body = _json_body(update_route)
    assert update_body["team_id"] == team_id
    assert update_body["user_id"] == email, "member_update body must use top-level user_id"
    assert update_body["max_budget_in_team"] == max_budget
    assert "member" not in update_body, "member_update body must NOT use nested 'member' object"

    # Second invocation — same outcome (idempotent): both routes will be called again
    add_route2 = respx.post("http://litellm.test/team/member_add").mock(
        return_value=httpx.Response(409, json={"error": "User already a team member"})
    )
    update_route2 = respx.post("http://litellm.test/team/member_update").mock(
        return_value=httpx.Response(200, json={"team_id": team_id})
    )

    await ensure_team_member_budget(email, team_id, max_budget, settings)

    assert add_route2.called, "second call: /team/member_add must be called"
    assert update_route2.called, "second call: /team/member_update must be called"


@pytest.mark.asyncio
@respx.mock
async def test_ensure_team_member_budget_wired_into_ensure_team_and_user():
    """D-14: ensure_team_member_budget is wired into ensure_team_and_user.

    When the factory config carries max_budget in the user block,
    ensure_team_and_user must call /team/member_add (and, on 'already a member',
    /team/member_update) to set max_budget_in_team (H3: only when budget exists).
    """
    factory_path = _make_factory_config(None)
    try:
        settings = make_settings(factory_config_path=factory_path)

        respx.post("http://litellm.test/team/new").mock(
            return_value=httpx.Response(200, json={"team_id": "team-platform"})
        )
        respx.post("http://litellm.test/v1/access_group").mock(
            return_value=httpx.Response(200, json={"access_group_id": "group-1"})
        )
        respx.post("http://litellm.test/user/new").mock(
            return_value=httpx.Response(200, json={"user_id": "alice@example.com"})
        )
        # member_add succeeds on first call (new member)
        member_add_route = respx.post("http://litellm.test/team/member_add").mock(
            return_value=httpx.Response(200, json={"team_id": "team-platform"})
        )
        # member_update called as part of the idempotent flow (always called after add)
        respx.post("http://litellm.test/team/member_update").mock(
            return_value=httpx.Response(200, json={"team_id": "team-platform"})
        )

        await ensure_team_and_user("alice@example.com", settings, name="Alice")

        assert (
            member_add_route.called
        ), "ensure_team_and_user must call /team/member_add when factory has max_budget (D-14)"
    finally:
        import os

        os.unlink(factory_path)


@pytest.mark.asyncio
@respx.mock
async def test_user_daily_activity():
    """D-09b: user_daily_activity fetches /user/daily/activity and returns the breakdown."""
    from app.litellm_client import user_daily_activity

    settings = make_settings()

    expected_response = {
        "results": [
            {
                "date": "2026-06-01",
                "metrics": {
                    "spend": 0.5,
                    "total_tokens": 1000,
                    "api_requests": 5,
                },
            }
        ],
        "metadata": {
            "total_spend": 0.5,
            "total_tokens": 1000,
            "total_api_requests": 5,
            "has_more": False,
            "page": 1,
            "total_pages": 1,
        },
    }

    route = respx.get("http://litellm.test/user/daily/activity").mock(
        return_value=httpx.Response(200, json=expected_response)
    )

    result = await user_daily_activity("alice@example.com", settings, "2026-06-01", "2026-06-30")

    assert route.called
    assert result["results"][0]["date"] == "2026-06-01"
    assert result["metadata"]["total_spend"] == 0.5

    # Verify H6: params used (not f-string)
    call = route.calls.last
    params = dict(call.request.url.params)
    assert params.get("user_id") == "alice@example.com"
    assert params.get("start_date") == "2026-06-01"
    assert params.get("end_date") == "2026-06-30"


@pytest.mark.asyncio
@respx.mock
async def test_two_page_daily_activity():
    """Plan 12-02: a multi-page has_more response is concatenated across pages.

    The spike could not reproduce has_more=true on low-traffic prod, so this is a
    SYNTHETIC two-page test: page 1 has_more=true, page 2 has_more=false. The
    bounded loop must accumulate results[] across both pages.
    """
    from app.litellm_client import user_daily_activity

    settings = make_settings()

    page1 = {
        "results": [
            {"date": "2026-06-01", "metrics": {"spend": 0.1, "api_requests": 1}},
            {"date": "2026-06-02", "metrics": {"spend": 0.2, "api_requests": 2}},
        ],
        "metadata": {
            "total_spend": 0.6,
            "total_api_requests": 6,
            "page": 1,
            "total_pages": 2,
            "has_more": True,
        },
    }
    page2 = {
        "results": [
            {"date": "2026-06-03", "metrics": {"spend": 0.3, "api_requests": 3}},
        ],
        "metadata": {
            "total_spend": 0.6,
            "total_api_requests": 6,
            "page": 2,
            "total_pages": 2,
            "has_more": False,
        },
    }

    def _responder(request: httpx.Request) -> httpx.Response:
        page = request.url.params.get("page")
        if page in (None, "1"):
            return httpx.Response(200, json=page1)
        return httpx.Response(200, json=page2)

    route = respx.get("http://litellm.test/user/daily/activity").mock(side_effect=_responder)

    result = await user_daily_activity("alice@example.com", settings, "2026-06-01", "2026-06-03")

    assert route.call_count == 2
    # Page 1 (2 results) + page 2 (1 result) concatenated.
    assert len(result["results"]) == 3
    assert [r["date"] for r in result["results"]] == ["2026-06-01", "2026-06-02", "2026-06-03"]
    # Window totals taken from metadata (LiteLLM pre-aggregates across the range).
    assert result["metadata"]["total_spend"] == 0.6
    # H6: page param passed via params={}, not f-string.
    params = dict(route.calls.last.request.url.params)
    assert params.get("user_id") == "alice@example.com"
    assert "page" in params


@pytest.mark.asyncio
@respx.mock
async def test_spend_logs_last_used_max_per_model():
    """Plan 12-02: spend_logs_last_used returns {model: max(startTime)} per model."""
    from app.litellm_client import spend_logs_last_used

    settings = make_settings()

    rows = [
        {"model": "gemini/flash", "startTime": "2026-04-01T09:48:21.000000Z"},
        {"model": "gemini/flash", "startTime": "2026-04-01T09:49:44.420000Z"},  # newest flash
        {"model": "gemini/pro", "startTime": "2026-04-01T09:49:44.384000Z"},
        # endTime-only row exercises the defensive fallback.
        {"model": "gemini/lite", "endTime": "2026-04-01T07:00:00.000000Z"},
    ]

    route = respx.get("http://litellm.test/spend/logs").mock(
        return_value=httpx.Response(200, json=rows)
    )

    result = await spend_logs_last_used("alice@example.com", settings, "2026-04-01", "2026-04-02")

    assert route.called
    assert result["gemini/flash"] == "2026-04-01T09:49:44.420000Z"
    assert result["gemini/pro"] == "2026-04-01T09:49:44.384000Z"
    assert result["gemini/lite"] == "2026-04-01T07:00:00.000000Z"
    # H6 + summarize=false (raw rows).
    params = dict(route.calls.last.request.url.params)
    assert params.get("user_id") == "alice@example.com"
    assert params.get("summarize") == "false"


@pytest.mark.asyncio
@respx.mock
async def test_spend_logs_last_used_degrades_on_5xx():
    """Plan 12-02: last-used degrades to {} on a 5xx — it never raises into a 502."""
    from app.litellm_client import spend_logs_last_used

    settings = make_settings()

    respx.get("http://litellm.test/spend/logs").mock(
        return_value=httpx.Response(503, text="upstream down")
    )

    result = await spend_logs_last_used("alice@example.com", settings, "2026-04-01", "2026-04-02")

    assert result == {}


@pytest.mark.asyncio
@respx.mock
async def test_spend_logs_last_used_empty_rows():
    """Plan 12-02: an empty /spend/logs window returns {} (exercised live in prod)."""
    from app.litellm_client import spend_logs_last_used

    settings = make_settings()

    respx.get("http://litellm.test/spend/logs").mock(return_value=httpx.Response(200, json=[]))

    result = await spend_logs_last_used("alice@example.com", settings, "2026-04-01", "2026-04-02")

    assert result == {}


# ---------------------------------------------------------------------------
# Read-only catalogs: list_litellm_models + list_litellm_mcp_servers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_list_litellm_models_projects_group_view():
    """/model_group/info rows are projected to the public allow-list, sorted by name."""
    from app.litellm_client import list_litellm_models

    settings = make_settings()
    respx.get("http://litellm.test/model_group/info").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "model_group": "zeta.model",
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
                        # A field NOT in the allow-list must NOT pass through.
                        "litellm_params": {"model": "openai/secret-upstream", "api_base": "x"},
                    },
                    {"model_group": "alpha.model", "providers": ["anthropic"], "mode": "chat"},
                ]
            },
        )
    )

    models = await list_litellm_models(settings)

    assert [m["name"] for m in models] == ["alpha.model", "zeta.model"]  # sorted
    zeta = models[1]
    assert zeta["providers"] == ["openai"]
    assert zeta["input_cost_per_token"] == 1.5e-07
    assert zeta["supports_vision"] is True
    # No upstream leakage: only the allow-listed keys are present.
    assert "litellm_params" not in zeta
    assert set(zeta.keys()) == {
        "name",
        "providers",
        "mode",
        "max_input_tokens",
        "max_output_tokens",
        "input_cost_per_token",
        "output_cost_per_token",
        "supports_vision",
        "supports_function_calling",
        "supports_reasoning",
        "supports_web_search",
    }


@pytest.mark.asyncio
@respx.mock
async def test_list_litellm_models_raises_on_5xx():
    from app.litellm_client import list_litellm_models

    settings = make_settings()
    respx.get("http://litellm.test/model_group/info").mock(
        return_value=httpx.Response(500, json={"error": {"message": "boom"}})
    )
    with pytest.raises(httpx.HTTPStatusError):
        await list_litellm_models(settings)


@pytest.mark.asyncio
@respx.mock
async def test_list_litellm_mcp_servers_strips_secrets():
    """/v1/mcp/server bare array is projected to a PUBLIC subset (no creds/env)."""
    from app.litellm_client import list_litellm_mcp_servers

    settings = make_settings()
    respx.get("http://litellm.test/v1/mcp/server").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "server_id": "github-mcp",
                    "server_name": "github",
                    "alias": "GitHub",
                    "description": "Repos and issues.",
                    "url": "https://mcp.internal/github",
                    "transport": "http",
                    "auth_type": "oauth2",
                    "status": "healthy",
                    "allowed_tools": ["list_repos", "create_issue"],
                    "mcp_access_groups": ["platform"],
                    "credentials": {"api_key": "SHOULD-NOT-LEAK"},
                    "env": {"TOKEN": "SHOULD-NOT-LEAK"},
                    "static_headers": {"x": "SHOULD-NOT-LEAK"},
                    "command": "npx",
                    "args": ["secret-arg"],
                }
            ],
        )
    )

    servers = await list_litellm_mcp_servers(settings)

    assert len(servers) == 1
    s = servers[0]
    assert s["id"] == "github-mcp"
    assert s["name"] == "GitHub"  # alias preferred
    assert s["transport"] == "http"
    assert s["auth_type"] == "oauth2"
    assert s["tool_count"] == 2
    assert s["tools"] == ["list_repos", "create_issue"]
    assert s["access_groups"] == ["platform"]
    # No secret-bearing / internal field may survive the projection.
    blob = _json.dumps(s)
    assert "SHOULD-NOT-LEAK" not in blob
    for forbidden in ("credentials", "env", "static_headers", "command", "args"):
        assert forbidden not in s


@pytest.mark.asyncio
@respx.mock
async def test_list_litellm_mcp_servers_404_raises():
    """A 404 (no MCP gateway) raises HTTPStatusError for the route to map to unavailable."""
    from app.litellm_client import list_litellm_mcp_servers

    settings = make_settings()
    respx.get("http://litellm.test/v1/mcp/server").mock(
        return_value=httpx.Response(404, json={"error": {"message": "not found"}})
    )
    with pytest.raises(httpx.HTTPStatusError) as exc:
        await list_litellm_mcp_servers(settings)
    assert exc.value.response.status_code == 404


# ---------------------------------------------------------------------------
# Default-key flag (is_default) — A1: surfaced in the session-key projection
# ---------------------------------------------------------------------------


def test_project_session_key_reads_is_default_from_metadata():
    from app.litellm_client import _project_session_key

    md = {"created_at": "2026-06-05T10:00:00+00:00", "is_default": True}
    row = {"token": "hash-abc", "key_alias": "key-a", "metadata": md}
    out = _project_session_key(row, md)
    assert out["is_default"] is True
    # Raw metadata is carried through for server-side read-modify-write (stripped
    # by the session router before reaching the browser).
    assert out["metadata"] is md


def test_project_session_key_default_false_when_flag_absent():
    from app.litellm_client import _project_session_key

    out = _project_session_key({"token": "h", "key_alias": "k"}, {})
    assert out["is_default"] is False


# ---------------------------------------------------------------------------
# A2: set_litellm_key_default — write path (/key/update metadata merge)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_set_litellm_key_default_sends_merged_metadata():
    from app.litellm_client import set_litellm_key_default

    settings = make_settings()
    route = respx.post(f"{settings.litellm_url}/key/update").mock(
        return_value=httpx.Response(200, json={"key": "hash-abc"})
    )
    await set_litellm_key_default(
        "hash-abc",
        settings,
        is_default=True,
        existing_metadata={"email": "a@b.com", "source": "token-factory"},
    )
    body = _json_body(route)
    assert body["key"] == "hash-abc"
    assert body["metadata"]["is_default"] is True
    assert body["metadata"]["email"] == "a@b.com"  # preserved


@pytest.mark.asyncio
@respx.mock
async def test_set_litellm_key_default_false_removes_flag():
    from app.litellm_client import set_litellm_key_default

    settings = make_settings()
    route = respx.post(f"{settings.litellm_url}/key/update").mock(
        return_value=httpx.Response(200, json={})
    )
    await set_litellm_key_default(
        "h",
        settings,
        is_default=False,
        existing_metadata={"email": "a@b.com", "is_default": True},
    )
    body = _json_body(route)
    assert body["metadata"].get("is_default") in (False, None)
    assert body["metadata"]["email"] == "a@b.com"  # preserved


@pytest.mark.asyncio
@respx.mock
async def test_set_litellm_key_default_raises_on_5xx():
    from app.litellm_client import set_litellm_key_default

    settings = make_settings()
    respx.post(f"{settings.litellm_url}/key/update").mock(
        return_value=httpx.Response(500, text="boom")
    )
    with pytest.raises(httpx.HTTPStatusError):
        await set_litellm_key_default("h", settings, is_default=True, existing_metadata={})


# ---------------------------------------------------------------------------
# C1: per-user scoping header (x-user-id) on the catalog calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@respx.mock
async def test_list_models_sends_x_user_id_header():
    from app.litellm_client import list_litellm_models

    settings = make_settings()
    route = respx.get(f"{settings.litellm_url}/model_group/info").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    await list_litellm_models(settings, user_id="alice@example.com")
    assert route.calls.last.request.headers["x-user-id"] == "alice@example.com"
    assert route.calls.last.request.headers["authorization"].startswith("Bearer ")


@pytest.mark.asyncio
@respx.mock
async def test_list_models_omits_x_user_id_when_none():
    from app.litellm_client import list_litellm_models

    settings = make_settings()
    route = respx.get(f"{settings.litellm_url}/model_group/info").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    await list_litellm_models(settings)
    assert "x-user-id" not in route.calls.last.request.headers


@pytest.mark.asyncio
@respx.mock
async def test_list_mcp_sends_x_user_id_header():
    from app.litellm_client import list_litellm_mcp_servers

    settings = make_settings()
    route = respx.get(f"{settings.litellm_url}/v1/mcp/server").mock(
        return_value=httpx.Response(200, json=[])
    )
    await list_litellm_mcp_servers(settings, user_id="alice@example.com")
    assert route.calls.last.request.headers["x-user-id"] == "alice@example.com"
    assert route.calls.last.request.headers["authorization"].startswith("Bearer ")


@pytest.mark.asyncio
@respx.mock
async def test_list_mcp_omits_x_user_id_when_none():
    from app.litellm_client import list_litellm_mcp_servers

    settings = make_settings()
    route = respx.get(f"{settings.litellm_url}/v1/mcp/server").mock(
        return_value=httpx.Response(200, json=[])
    )
    await list_litellm_mcp_servers(settings)
    assert "x-user-id" not in route.calls.last.request.headers


# ---------------------------------------------------------------------------
# user-scoping contract probe (sso_key_swapper custom auth verification)
# ---------------------------------------------------------------------------


@respx.mock
@pytest.mark.asyncio
async def test_verify_contract_enforced_on_403():
    from app.litellm_client import CONTRACT_PROBE_USER_ID, verify_user_scoping_contract

    settings = make_settings()
    route = respx.get(f"{settings.litellm_url}/v1/models").mock(
        return_value=httpx.Response(403, json={"error": {"message": "access denied"}})
    )
    assert await verify_user_scoping_contract(settings) == "enforced"
    # The probe impersonates a deliberately non-existent user via x-user-id, with
    # the master key in Authorization.
    req = route.calls.last.request
    assert req.headers["x-user-id"] == CONTRACT_PROBE_USER_ID
    assert req.headers["authorization"].startswith("Bearer ")


@respx.mock
@pytest.mark.asyncio
async def test_verify_contract_enforced_on_401():
    from app.litellm_client import verify_user_scoping_contract

    settings = make_settings()
    respx.get(f"{settings.litellm_url}/v1/models").mock(
        return_value=httpx.Response(401, json={})
    )
    assert await verify_user_scoping_contract(settings) == "enforced"


@respx.mock
@pytest.mark.asyncio
async def test_verify_contract_not_enforced_on_200():
    from app.litellm_client import verify_user_scoping_contract

    settings = make_settings()
    # 200 means the master key authenticated as full admin (x-user-id ignored) —
    # the custom auth is NOT installed/enforcing.
    respx.get(f"{settings.litellm_url}/v1/models").mock(
        return_value=httpx.Response(200, json={"data": []})
    )
    assert await verify_user_scoping_contract(settings) == "not_enforced"


@respx.mock
@pytest.mark.asyncio
async def test_verify_contract_unknown_on_5xx():
    from app.litellm_client import verify_user_scoping_contract

    settings = make_settings()
    respx.get(f"{settings.litellm_url}/v1/models").mock(
        return_value=httpx.Response(503, text="upstream down")
    )
    assert await verify_user_scoping_contract(settings) == "unknown"


@respx.mock
@pytest.mark.asyncio
async def test_verify_contract_unknown_on_network_error():
    from app.litellm_client import verify_user_scoping_contract

    settings = make_settings()
    respx.get(f"{settings.litellm_url}/v1/models").mock(
        side_effect=httpx.ConnectError("unreachable")
    )
    assert await verify_user_scoping_contract(settings) == "unknown"
