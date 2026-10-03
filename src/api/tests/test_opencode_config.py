# SPDX-License-Identifier: Apache-2.0
"""GET /clients/opencode/config — spec 2026-09-27-opencode-client-config-and-den.md (Rev 4, §4.2, §4.7)."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app import opencode_config
from app.main import create_app
from app.oauth_as import routes as as_routes
from app.oauth_as.tokens import Signer
from tests.as_defaults import AS_TEST_DEFAULTS

URL = "/clients/opencode/config"
ALLOWED_TOP = {"provider", "mcp", "instructions", "model", "small_model"}

# What the user's key sees (list_litellm_models projection).
GROUPS = [
    {
        "name": "acme.smart",
        "mode": "chat",
        "max_input_tokens": 1048576.0,
        "max_output_tokens": 65536.0,
        "input_cost_per_token": 7.5e-07,
        "output_cost_per_token": 3.75e-06,
        "supports_vision": True,
        "supports_function_calling": True,
        "supports_reasoning": True,
    },
    {"name": "openai.gpt", "mode": "chat", "max_input_tokens": 1.0, "supports_vision": False},
    {
        "name": "acme.router",
        "mode": "chat",
        "max_input_tokens": 200000.0,
        "max_output_tokens": 32000.0,
        "supports_function_calling": True,
    },
    {"name": "openai.embed", "mode": "embedding"},
]
# Admin view: deployments (not aliases) and the alias map.
DEPLOYMENTS = {
    "gemini.flash": {
        "mode": "chat",
        "max_input_tokens": 1048576,
        "max_output_tokens": 65536,
        "input_cost_per_token": 7.5e-07,
        "output_cost_per_token": 3.75e-06,
        "cache_read_input_token_cost": 7.5e-08,
        "supports_vision": True,
        "supports_pdf_input": True,
        "supports_audio_input": True,
        "supports_function_calling": True,
        "supports_reasoning": True,
    },
    "openai.gpt": {
        "mode": "chat",
        "max_input_tokens": 400000,
        "max_output_tokens": 128000,
        "supports_vision": True,
        "supports_function_calling": True,
    },
    "acme.router": {"mode": "chat"},
    "secret.model": {"mode": "chat", "max_input_tokens": 1},
}
ALIASES = {"acme.smart": "gemini.flash", "acme.hidden": "secret.model"}


def _settings(**overrides):
    from app.config import Settings

    base = dict(
        app_base_url="http://localhost:8080",
        session_secret_key="test-secret-32-chars-padding-xxxx",
        oauth_issuer_url="http://dex.test/dex",
        oauth_client_id="test-client",
        oauth_client_secret="test-secret",
        litellm_url="http://litellm.test",
        litellm_master_key="sk-test",
        api_public_url="https://api.example.com",
        as_services='{"mcp-aws-eks-ro": {"store": "aws-eks-ro", "broker": "https://b.test/a"}}',
        **AS_TEST_DEFAULTS,
    )
    base.update(overrides)
    return Settings(**base)


@pytest.fixture(autouse=True)
def fresh_caps(monkeypatch):
    monkeypatch.setattr(opencode_config, "_caps", {"at": None, "deployments": {}, "aliases": {}})
    monkeypatch.setattr(opencode_config, "_caps_task", None)


@pytest.fixture()
def settings():
    return _settings()


@pytest.fixture()
def client(settings):
    return TestClient(create_app(settings=settings), raise_server_exceptions=False)


@pytest.fixture(autouse=True)
def front_key():
    with patch(
        "app.opencode_config.resolve_front_key",
        new_callable=AsyncMock,
        side_effect=lambda email, settings: f"sk-front-{email}",
    ) as resolver:
        yield resolver


@pytest.fixture()
def groups():
    with patch("app.opencode_config.list_litellm_models", new_callable=AsyncMock) as m:
        m.return_value = GROUPS
        yield m


@pytest.fixture(autouse=True)
def mcp_servers():
    with patch("app.opencode_config.list_litellm_mcp_servers", new_callable=AsyncMock) as m:
        m.return_value = []
        yield m


@pytest.fixture()
def admin():
    with (
        patch("app.opencode_config.list_deployment_capabilities", new_callable=AsyncMock) as deps,
        patch("app.opencode_config.get_model_group_aliases", new_callable=AsyncMock) as aliases,
    ):
        deps.return_value = DEPLOYMENTS
        aliases.return_value = ALIASES
        yield deps, aliases


def _token(settings, **kw):
    args = dict(
        issuer=settings.as_issuer,
        audience=settings.as_audience,
        sub="alice@example.com",
        scope="alitellm",
        client_id="c1",
        ttl=300,
    )
    args.update(kw)
    return as_routes._signer.issue(**args)


def _get(client, token):
    return client.get(URL, headers={"Authorization": f"Bearer {token}"})


def _models(body, provider="ai-platform"):
    return body["config"]["provider"][provider]["models"]


def test_provider_id_and_name_follow_provider_name(groups, admin):
    settings = _settings(provider_name="acme")
    client = TestClient(create_app(settings=settings), raise_server_exceptions=False)
    provider = _get(client, _token(settings)).json()["config"]["provider"]
    assert list(provider) == ["acme"]
    assert provider["acme"]["name"] == "acme"
    body = _get(client, _token(settings)).json()
    assert [s["name"] for s in body["skills"]] == ["genai-api"]


# T-S1
def test_valid_token_gets_the_users_chat_models(client, settings, groups, admin):
    resp = _get(client, _token(settings))
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "no-store"
    body = resp.json()
    assert body["schema"] == "ackstorm.opencode-config/1"
    assert body["auth"] == "ok" and body["stale"] is False
    assert body["user"] == "alice@example.com" and body["environment"] is None
    assert set(body["config"]) <= ALLOWED_TOP
    provider = body["config"]["provider"]["ai-platform"]
    assert provider["npm"] == "@ai-sdk/openai-compatible"
    assert provider["options"] == {"baseURL": "https://api.example.com/v1"}
    assert "env" not in provider
    # Visibility comes ONLY from the user's list: no embedding, no alias/deployment
    # the user cannot see (acme.hidden, secret.model, gemini.flash).
    assert sorted(_models(body)) == ["acme.router", "acme.smart", "openai.gpt"]
    assert groups.await_args.args[1] == "sk-front-alice@example.com"
    assert body["config"]["mcp"] == {
        "mcp-aws-eks-ro": {
            "type": "remote",
            "url": "https://api.example.com/mcp/mcp-aws-eks-ro",
            "enabled": False,
        }
    }
    assert [s["name"] for s in body["skills"]] == ["genai-api"]
    assert body["skills"][0]["files"]["SKILL.md"].startswith("---\nname: genai-api\n")


def test_every_reachable_mcp_server_is_registered_disabled(
    client, settings, groups, admin, mcp_servers
):
    mcp_servers.return_value = [{"name": "github"}, {"name": None}, {"name": "mcp-aws-eks-ro"}]
    mcp = _get(client, _token(settings)).json()["config"]["mcp"]
    # Under the user's own key, like the models; AS_SERVICES added; no duplicates.
    assert mcp_servers.await_args.args[1] == "sk-front-alice@example.com"
    assert mcp == {
        name: {"type": "remote", "url": f"https://api.example.com/mcp/{name}", "enabled": False}
        for name in ("github", "mcp-aws-eks-ro")
    }


def test_mcp_list_failure_keeps_models_and_as_services(
    client, settings, groups, admin, mcp_servers
):
    mcp_servers.side_effect = httpx.HTTPStatusError(
        "no MCP gateway", request=httpx.Request("GET", "http://x"), response=httpx.Response(404)
    )
    body = _get(client, _token(settings)).json()
    assert body["stale"] is False
    assert sorted(_models(body)) == ["acme.router", "acme.smart", "openai.gpt"]
    assert list(body["config"]["mcp"]) == ["mcp-aws-eks-ro"]


def test_alias_takes_the_target_deployments_capabilities(client, settings, groups, admin):
    smart = _models(_get(client, _token(settings)).json())["acme.smart"]
    assert smart == {
        "name": "acme.smart",
        "attachment": True,
        "reasoning": True,
        "tool_call": True,
        "temperature": True,
        "modalities": {"input": ["text", "image", "audio", "pdf"], "output": ["text"]},
        "limit": {"context": 1048576, "output": 65536},
        "cost": {"input": 0.75, "output": 3.75, "cache_read": 0.075},
    }


def test_real_model_uses_its_deployment_and_router_falls_back_to_the_group_row(
    client, settings, groups, admin
):
    models = _models(_get(client, _token(settings)).json())
    assert models["openai.gpt"]["limit"] == {"context": 400000, "output": 128000}
    assert models["openai.gpt"]["attachment"] is True
    router = models["acme.router"]
    assert router["limit"] == {"context": 200000, "output": 32000}
    assert router["tool_call"] is True and router["attachment"] is False
    assert router["cost"] == {"input": 0.0, "output": 0.0, "cache_read": 0.0}


def test_admin_read_failure_degrades_to_group_rows(client, settings, groups, admin):
    admin[0].side_effect = httpx.ConnectError("down")
    body = _get(client, _token(settings)).json()
    assert body["stale"] is False
    smart = _models(body)["acme.smart"]
    assert smart["modalities"]["input"] == ["text", "image"]  # no pdf/audio without model_info
    assert smart["cost"]["cache_read"] == 0.0


def test_capabilities_are_cached_process_wide(client, settings, groups, admin):
    _get(client, _token(settings))
    _get(client, _token(settings, sub="bob@example.com"))
    assert admin[0].await_count == 1 and admin[1].await_count == 1


def test_stale_capabilities_are_served_without_waiting(
    client, settings, groups, admin, monkeypatch
):
    # A copy older than CAPS_TTL: answer with it, refresh in the background.
    monkeypatch.setattr(
        opencode_config, "_caps", {"at": -(10**9), "deployments": DEPLOYMENTS, "aliases": ALIASES}
    )

    async def slow(*_a, **_k):
        await asyncio.sleep(5)
        return {}

    admin[0].side_effect = slow
    body = _get(client, _token(settings)).json()
    assert body["stale"] is False
    assert "pdf" in _models(body)["acme.smart"]["modalities"]["input"]


# T-S2
@pytest.mark.parametrize(
    "make_token",
    [
        lambda s: _token(s, ttl=-60),
        lambda s: _token(s, audience="other"),
        lambda s: Signer(AS_TEST_DEFAULTS["as_signing_key_pem"]).issue(
            issuer="https://evil.test",
            audience=s.as_audience,
            sub="alice@example.com",
            scope="alitellm",
            client_id="c1",
            ttl=300,
        ),
        lambda s: "not-a-jwt",
    ],
    ids=["expired", "wrong-aud", "wrong-iss", "garbage"],
)
def test_invalid_token_gets_the_empty_baseline(client, settings, groups, admin, make_token):
    resp = _get(client, make_token(settings))
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth"] == "invalid"
    assert body["user"] is None and body["config"] == {} and body["skills"] == []
    assert "acme.smart" not in resp.text and "mcp-aws-eks-ro" not in resp.text
    groups.assert_not_awaited()


# T-S3
@pytest.mark.parametrize("header", [None, "Basic abc", "Bearer ", "Bearer"])
def test_missing_or_malformed_header_is_401(client, header):
    headers = {"Authorization": header} if header is not None else {}
    resp = client.get(URL, headers=headers)
    assert resp.status_code == 401
    assert resp.headers["cache-control"] == "no-store"


# T-S4
def test_litellm_down_serves_the_last_good_body_as_stale(client, settings, groups, admin):
    good = _get(client, _token(settings)).json()
    groups.side_effect = httpx.ConnectError("down")
    body = _get(client, _token(settings)).json()
    assert body["stale"] is True and body["auth"] == "ok"
    assert body["config"] == good["config"] and body["version"] == good["version"]


def test_litellm_down_without_cache_serves_skills_only(client, settings, groups, admin):
    groups.side_effect = httpx.ConnectError("down")
    resp = _get(client, _token(settings))
    assert resp.status_code == 200
    body = resp.json()
    assert body["stale"] is True and body["auth"] == "ok"
    assert body["config"] == {}
    assert [s["name"] for s in body["skills"]] == ["genai-api"]


def test_slow_user_list_hits_the_deadline(client, settings, groups, admin, monkeypatch):
    async def slow(*_a, **_k):
        await asyncio.sleep(1)
        return GROUPS

    monkeypatch.setattr("app.opencode_config.UPSTREAM_DEADLINE", 0.01)
    groups.side_effect = slow
    assert _get(client, _token(settings)).json()["stale"] is True


def test_front_key_failure_is_not_a_5xx(client, settings, groups, admin, front_key):
    front_key.side_effect = RuntimeError("redis down")
    resp = _get(client, _token(settings))
    assert resp.status_code == 200 and resp.json()["stale"] is True


# T-S5
def test_version_is_stable_for_unchanged_inputs(client, settings, groups, admin):
    a = _get(client, _token(settings)).json()
    b = _get(client, _token(settings)).json()
    assert a["version"] == b["version"] and a["version"].startswith("sha256:")


def test_version_changes_when_the_model_list_changes(client, settings, groups, admin):
    a = _get(client, _token(settings)).json()
    groups.return_value = GROUPS[:1]
    b = _get(client, _token(settings)).json()
    assert a["version"] != b["version"]


# T-S6
def test_forbidden_keys_never_reach_the_output(client, settings, groups, admin):
    admin[0].return_value = {
        name: {**caps, "plugin": ["x"], "permission": {"bash": "allow"}, "api_key": "sk-up"}
        for name, caps in DEPLOYMENTS.items()
    }
    text = json.dumps(_get(client, _token(settings)).json()["config"])
    for bad in (
        '"plugin"',
        '"permission"',
        '"agent"',
        '"env"',
        "api_key",
        "sk-",
        "{env:",
        "{file:",
    ):
        assert bad not in text, bad


def test_default_models_only_when_the_user_sees_them(groups, admin):
    def config(**kw):
        settings = _settings(**kw)
        client = TestClient(create_app(settings=settings), raise_server_exceptions=False)
        return _get(client, _token(settings)).json()["config"]

    assert "model" not in config() and "small_model" not in config()
    both = config(opencode_default_model="acme.smart", opencode_default_small_model="openai.gpt")
    assert both["model"] == "ai-platform/acme.smart"
    assert both["small_model"] == "ai-platform/openai.gpt"
    # Not in the user's list (hidden / embedding / unknown) → omitted, not dangling.
    hidden = config(
        opencode_default_model="acme.hidden", opencode_default_small_model="openai.embed"
    )
    assert "model" not in hidden and "small_model" not in hidden
