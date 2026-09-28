# OpenCode client endpoints (server side) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Size note (CLAUDE.md "measure first")**: ~250 lines of production Python, one
> subsystem (alitellm-auth API), no CRD/migration. Execute INLINE, one review at the end.

**Goal:** Serve `GET /clients/opencode/config` (per-user OpenCode config, `ackstorm.opencode-config/1`) and `GET /clients/opencode/plugin` (plugin tgz carrying this deployment's `platform.json`).

**Architecture:** `Signer.verify` checks the front-door JWT this app issues. The config route reads the user's visible model groups under the user's own LiteLLM key, enriches each from a process-wide capability cache (deployments from `/v2/model/info` + alias map, both read with the master key; 1 h, stale-while-revalidate), adds `AS_SERVICES` as disabled remote MCP entries and the `mcp-setup` skill, and keeps the last good body per user in the AS store. The plugin route repacks the baked tgz with `package/platform.json`, deterministic bytes.

**Tech Stack:** FastAPI, authlib `JsonWebToken`, httpx, AS `Store`, stdlib `tarfile`/`gzip`, pytest + respx + `unittest.mock`.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-27-opencode-client-config-and-den.md`, **section "Rev 4" wins** over §4.2 where they differ; §4.7 T-S1..T-S6.
- Paths: `/clients/opencode/config`, `/clients/opencode/plugin`; `/public/opencode-auth` stays a permanent alias of the plugin route.
- Schema `ackstorm.opencode-config/1`; provider id `ackstorm` (= `PROVIDER` in `clients/opencode/index.mjs`).
- `config` top-level keys only `provider`, `mcp`, `instructions`. Never `plugin`, `permission`, `agent`, `command`, `enabled_providers`, `disabled_providers`, keys/tokens, `{env:…}`/`{file:…}`.
- 200 for any `Authorization: Bearer <non-empty>`; invalid token → baseline (`auth: "invalid"`, `user: null`, `config: {}`, `skills: []`). Missing/malformed header → 401. Never 5xx. `Cache-Control: no-store` on every config response.
- Visibility = `/model_group/info` under the user's key (`resolve_front_key`), `mode == "chat"` only. The master key ONLY enriches those names; it never adds a model.
- Upstream deadline 1.5 s total (plugin waits 2 s). Per-user cache: kind `opencode_config`, key = email, TTL 30 d. Capability cache (model_info + alias map): process-wide, TTL 1 h, stale-while-revalidate — a stale copy is served at once while a background refresh runs; only a cold start (no copy yet) waits, bounded by the deadline.
- `platform.json` = `{"api": "<API_PUBLIC_URL>/v1", "platform": "<origin of API_PUBLIC_URL>"}`.
- Never log tokens, skill bodies or the `/get/config/callbacks` payload. `ruff@0.8.4` clean. Tests use `create_app(settings=...)`, never env.
- Commits only after user approval, via `git:commit-push` subagent.

## File Structure

| File | Change |
|---|---|
| `src/api/app/oauth_as/tokens.py` | + `Signer.verify` |
| `src/api/app/litellm_client.py` | + `list_deployment_capabilities`, `get_model_group_aliases` (admin reads) |
| `src/api/app/opencode_config.py` | new: config route + capability cache + model mapping |
| `src/api/app/public.py` | plugin route at `/clients/opencode/plugin` (+ alias), repack with `platform.json` |
| `src/api/app/main.py` | register `opencode_config` router |
| `deploy/helm/alitellm-auth/values.yaml` | `/clients/*` in `istio.exemptPaths` |
| tests | `test_oauth_as_tokens.py`, `test_litellm_client.py`, `test_opencode_config.py` (new), `test_public.py` |
| `CHANGELOG.md`, `CLAUDE.md` | entries + rules |

---

### Task 1: `Signer.verify`

**Files:** Modify `src/api/app/oauth_as/tokens.py`; Test `src/api/tests/test_oauth_as_tokens.py`

**Interfaces:**
- Produces: `Signer.verify(token: str, *, issuer: str, audience: str) -> dict` — claims; raises `authlib.jose.errors.JoseError` on bad signature, non-RS256, wrong `iss`/`aud`, expired, missing `sub`, garbage.

- [ ] **Step 1: Failing tests** (append to `tests/test_oauth_as_tokens.py`)

```python
import pytest
from authlib.jose.errors import JoseError


def _issue(signer, **kw):
    args = dict(
        issuer="https://as.test", audience="alitellm", sub="u@x.com",
        scope="alitellm", client_id="c1", ttl=60,
    )
    args.update(kw)
    return signer.issue(**args)


def test_verify_returns_the_claims_of_a_valid_token():
    signer = Signer(_pem())
    claims = signer.verify(_issue(signer), issuer="https://as.test", audience="alitellm")
    assert claims["sub"] == "u@x.com" and claims["aud"] == "alitellm"


@pytest.mark.parametrize(
    "token_kw",
    [{"ttl": -60}, {"audience": "other"}, {"issuer": "https://evil.test"}],
    ids=["expired", "wrong-aud", "wrong-iss"],
)
def test_verify_rejects_bad_claims(token_kw):
    signer = Signer(_pem())
    with pytest.raises(JoseError):
        signer.verify(_issue(signer, **token_kw), issuer="https://as.test", audience="alitellm")


def test_verify_rejects_a_token_signed_by_another_key():
    token = _issue(Signer(_pem()))
    with pytest.raises(JoseError):
        Signer(_pem()).verify(token, issuer="https://as.test", audience="alitellm")


def test_verify_rejects_hs256_signed_with_the_public_key():
    signer = Signer(_pem())
    public_pem = signer._key.as_pem(is_private=False)
    forged = jwt.encode(
        {"alg": "HS256"},
        {"iss": "https://as.test", "aud": "alitellm", "sub": "u@x.com", "exp": int(time.time()) + 60},
        public_pem,
    ).decode()
    with pytest.raises(JoseError):
        signer.verify(forged, issuer="https://as.test", audience="alitellm")


@pytest.mark.parametrize("garbage", ["", "not-a-jwt", "a.b.c"])
def test_verify_rejects_garbage(garbage):
    with pytest.raises(JoseError):
        Signer(_pem()).verify(garbage, issuer="https://as.test", audience="alitellm")
```

- [ ] **Step 2: Run, expect FAIL** — `cd src/api && .venv/bin/pytest tests/test_oauth_as_tokens.py -q` → `AttributeError: 'Signer' object has no attribute 'verify'`.

- [ ] **Step 3: Implement** in `app/oauth_as/tokens.py`

Import line becomes `from authlib.jose import JsonWebKey, JsonWebToken, jwt`, then below the imports:

```python
# RS256 only: the default JsonWebToken also accepts HS256, which would let a
# token HMAC'd with our PUBLIC key pass as signed.
_RS256 = JsonWebToken(["RS256"])
```

Method on `Signer`, after `issue`:

```python
    def verify(self, token: str, *, issuer: str, audience: str) -> dict:
        """Claims of a token this signer issued. Raises JoseError otherwise.

        Checks the RS256 signature, `iss`, `aud`, `exp`, and that `sub` exists.
        Stateless: a token stays valid until `exp` even after its refresh token
        is revoked (the access-token TTL bounds that window).
        """
        claims = _RS256.decode(
            token,
            self._key,
            claims_options={
                "iss": {"essential": True, "value": issuer},
                "aud": {"essential": True, "value": audience},
                "exp": {"essential": True},
                "sub": {"essential": True},
            },
        )
        claims.validate()
        return dict(claims)
```

If Step 4 shows a garbage input raising a non-`JoseError` (e.g. `ValueError`), wrap the decode: `except (ValueError, TypeError) as exc: raise DecodeError(str(exc)) from exc` (`from authlib.jose.errors import DecodeError`). Only if needed.

- [ ] **Step 4: Run, expect PASS** — same command.

---

### Task 2: Admin capability reads in `litellm_client.py`

**Files:** Modify `src/api/app/litellm_client.py` (append after `list_litellm_models`); Test `src/api/tests/test_litellm_client.py`

**Interfaces:**
- Consumes: `_admin_headers(settings)`, `_raise_litellm(resp, endpoint)` (existing).
- Produces:
  - `DEPLOYMENT_CAPABILITY_KEYS: tuple[str, ...]`
  - `async list_deployment_capabilities(settings) -> dict[str, dict]` — `model_name` → allow-listed non-null `model_info` fields; first deployment of a name wins. Raises `httpx.HTTPStatusError`/`httpx.RequestError`.
  - `async get_model_group_aliases(settings) -> dict[str, str]` — alias → target model group. Raises the same.

- [ ] **Step 1: Failing tests** (append to `tests/test_litellm_client.py`)

```python
@pytest.mark.asyncio
@respx.mock
async def test_list_deployment_capabilities_pages_and_allow_lists():
    from app.litellm_client import list_deployment_capabilities

    settings = make_settings()
    route = respx.get("http://litellm.test/v2/model/info")
    route.side_effect = [
        httpx.Response(200, json={"total_pages": 2, "data": [
            {"model_name": "gemini.flash", "litellm_params": {"api_base": "https://up.test", "api_key": "sk-up"},
             "model_info": {"mode": "chat", "max_input_tokens": 1048576, "supports_pdf_input": True,
                            "cache_read_input_token_cost": 7.5e-08, "supports_audio_input": None,
                            "id": "dep-1", "db_model": True}},
        ]}),
        httpx.Response(200, json={"total_pages": 2, "data": [
            {"model_name": "gemini.flash", "model_info": {"mode": "chat", "max_input_tokens": 1}},
            {"model_name": "openai.gpt", "model_info": {"mode": "chat", "supports_vision": True}},
        ]}),
    ]
    caps = await list_deployment_capabilities(settings)
    assert caps == {
        "gemini.flash": {"mode": "chat", "max_input_tokens": 1048576, "supports_pdf_input": True,
                         "cache_read_input_token_cost": 7.5e-08},
        "openai.gpt": {"mode": "chat", "supports_vision": True},
    }
    assert route.calls[0].request.headers["authorization"] == "Bearer sk-test"
    assert [c.request.url.params["page"] for c in route.calls] == ["1", "2"]


@pytest.mark.asyncio
@respx.mock
async def test_get_model_group_aliases_keeps_only_the_alias_map():
    from app.litellm_client import get_model_group_aliases

    settings = make_settings()
    respx.get("http://litellm.test/get/config/callbacks").mock(
        return_value=httpx.Response(200, json={
            "callbacks": [{"name": "langfuse", "variables": {"LANGFUSE_SECRET_KEY": "x"}}],
            "router_settings": {"routing_strategy": "simple-shuffle", "model_group_alias": {
                "ackstorm.smart": "gemini.flash",
                "ackstorm.hidden": {"model": "openai.gpt", "hidden": True},
                "bad": 3,
            }},
        })
    )
    assert await get_model_group_aliases(settings) == {
        "ackstorm.smart": "gemini.flash",
        "ackstorm.hidden": "openai.gpt",
    }


@pytest.mark.asyncio
@respx.mock
async def test_get_model_group_aliases_without_router_settings():
    from app.litellm_client import get_model_group_aliases

    respx.get("http://litellm.test/get/config/callbacks").mock(
        return_value=httpx.Response(200, json={"callbacks": []})
    )
    assert await get_model_group_aliases(make_settings()) == {}
```

(Check `make_settings()` in that file sets `litellm_master_key="sk-test"`; adjust the header assertion to its value if not.)

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_litellm_client.py -q -k "deployment_capabilities or model_group_aliases"` → ImportError.

- [ ] **Step 3: Implement** (append after `list_litellm_models` in `app/litellm_client.py`)

```python
# Capability fields kept from a deployment's model_info (GET /v2/model/info).
# EXPLICIT allow-list: nothing else of the row is kept (litellm_params carries
# upstream URLs and, for an admin, credentials).
DEPLOYMENT_CAPABILITY_KEYS = (
    "mode",
    "max_input_tokens",
    "max_output_tokens",
    "input_cost_per_token",
    "output_cost_per_token",
    "cache_read_input_token_cost",
    "supports_vision",
    "supports_pdf_input",
    "supports_audio_input",
    "supports_video_input",
    "supports_function_calling",
    "supports_reasoning",
)
_MAX_MODEL_INFO_PAGES = 50  # ponytail: 100 rows/page → 5000 deployments; raise if a proxy outgrows it


async def list_deployment_capabilities(settings: Settings) -> dict[str, dict]:
    """Capabilities per deployment ``model_name`` from GET /v2/model/info, as ADMIN.

    Master key on purpose: this only DESCRIBES models. Which models a user may
    use is decided under the user's own key (list_litellm_models); callers must
    only look up names that list returned. First deployment of a name wins.
    """
    out: dict[str, dict] = {}
    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=15.0) as client:
        page, pages = 1, 1
        while page <= min(pages, _MAX_MODEL_INFO_PAGES):
            resp = await client.get(
                "/v2/model/info",
                params={"page": page, "size": 100},
                headers=_admin_headers(settings),
            )
            if not resp.is_success:
                _raise_litellm(resp, "/v2/model/info")
            body = resp.json()
            pages = int(body.get("total_pages") or 1)
            for row in body.get("data") or []:
                name = row.get("model_name")
                info = row.get("model_info") or {}
                if name and name not in out:
                    out[name] = {
                        k: info[k] for k in DEPLOYMENT_CAPABILITY_KEYS if info.get(k) is not None
                    }
            page += 1
    return out


async def get_model_group_aliases(settings: Settings) -> dict[str, str]:
    """``router_settings.model_group_alias`` (alias → target model group), as ADMIN.

    Read from GET /get/config/callbacks, the same source alitellm-operator writes
    through. That payload also carries callback configuration: ONLY the alias map
    is kept, and nothing of it is logged. LiteLLM accepts a target as a string or
    as ``{"model": target, ...}``.
    """
    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=15.0) as client:
        resp = await client.get("/get/config/callbacks", headers=_admin_headers(settings))
    if not resp.is_success:
        _raise_litellm(resp, "/get/config/callbacks")
    raw = ((resp.json() or {}).get("router_settings") or {}).get("model_group_alias") or {}
    out: dict[str, str] = {}
    for alias, target in raw.items():
        if isinstance(target, dict):
            target = target.get("model")
        if isinstance(target, str):
            out[alias] = target
    return out
```

- [ ] **Step 4: Run, expect PASS** — same command.

---

### Task 3: `GET /clients/opencode/config`

**Files:** Create `src/api/app/opencode_config.py`; Modify `src/api/app/main.py`; Test `src/api/tests/test_opencode_config.py`

**Interfaces:**
- Consumes: `Signer.verify` (Task 1); `list_deployment_capabilities`, `get_model_group_aliases` (Task 2); `app.oauth_as.routes._signer`, `._store`; `app.internal.resolve_front_key(sub, settings) -> str`; `app.litellm_client.list_litellm_models(settings, api_key) -> list[dict]` (rows: `name`, `mode`, `max_input_tokens`, `max_output_tokens`, `input_cost_per_token`, `output_cost_per_token`, `supports_vision`, `supports_function_calling`, `supports_reasoning`, …); `app.skills.MCP_SETUP`, `mcp_setup_body(settings)`.
- Produces: route `GET /clients/opencode/config`; `OPENCODE_PROVIDER_ID = "ackstorm"`; module state `_caps`, `_caps_task` (tests reset them).

- [ ] **Step 1: Failing tests** — `src/api/tests/test_opencode_config.py`

```python
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
ALLOWED_TOP = {"provider", "mcp", "instructions"}

# What the user's key sees (list_litellm_models projection).
GROUPS = [
    {"name": "ackstorm.smart", "mode": "chat", "max_input_tokens": 1048576.0, "max_output_tokens": 65536.0,
     "input_cost_per_token": 7.5e-07, "output_cost_per_token": 3.75e-06, "supports_vision": True,
     "supports_function_calling": True, "supports_reasoning": True},
    {"name": "openai.gpt", "mode": "chat", "max_input_tokens": 1.0, "supports_vision": False},
    {"name": "ackstorm.router", "mode": "chat", "max_input_tokens": 200000.0, "max_output_tokens": 32000.0,
     "supports_function_calling": True},
    {"name": "openai.embed", "mode": "embedding"},
]
# Admin view: deployments (not aliases) and the alias map.
DEPLOYMENTS = {
    "gemini.flash": {"mode": "chat", "max_input_tokens": 1048576, "max_output_tokens": 65536,
                     "input_cost_per_token": 7.5e-07, "output_cost_per_token": 3.75e-06,
                     "cache_read_input_token_cost": 7.5e-08, "supports_vision": True,
                     "supports_pdf_input": True, "supports_audio_input": True,
                     "supports_function_calling": True, "supports_reasoning": True},
    "openai.gpt": {"mode": "chat", "max_input_tokens": 400000, "max_output_tokens": 128000,
                   "supports_vision": True, "supports_function_calling": True},
    "ackstorm.router": {"mode": "chat"},
    "secret.model": {"mode": "chat", "max_input_tokens": 1},
}
ALIASES = {"ackstorm.smart": "gemini.flash", "ackstorm.hidden": "secret.model"}


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
        issuer=settings.as_issuer, audience=settings.as_audience, sub="alice@example.com",
        scope="alitellm", client_id="c1", ttl=300,
    )
    args.update(kw)
    return as_routes._signer.issue(**args)


def _get(client, token):
    return client.get(URL, headers={"Authorization": f"Bearer {token}"})


def _models(body):
    return body["config"]["provider"]["ackstorm"]["models"]


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
    provider = body["config"]["provider"]["ackstorm"]
    assert provider["npm"] == "@ai-sdk/openai-compatible"
    assert provider["options"] == {"baseURL": "https://api.example.com/v1"}
    assert "env" not in provider
    # Visibility comes ONLY from the user's list: no embedding, no alias/deployment
    # the user cannot see (ackstorm.hidden, secret.model, gemini.flash).
    assert sorted(_models(body)) == ["ackstorm.router", "ackstorm.smart", "openai.gpt"]
    assert groups.await_args.args[1] == "sk-front-alice@example.com"
    assert body["config"]["mcp"] == {
        "mcp-aws-eks-ro": {"type": "remote", "url": "https://api.example.com/mcp/mcp-aws-eks-ro",
                           "enabled": False}
    }
    assert [s["name"] for s in body["skills"]] == ["mcp-setup"]
    assert body["skills"][0]["files"]["SKILL.md"].startswith("---\nname: mcp-setup\n")


def test_alias_takes_the_target_deployments_capabilities(client, settings, groups, admin):
    smart = _models(_get(client, _token(settings)).json())["ackstorm.smart"]
    assert smart == {
        "name": "ackstorm.smart",
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
    router = models["ackstorm.router"]
    assert router["limit"] == {"context": 200000, "output": 32000}
    assert router["tool_call"] is True and router["attachment"] is False
    assert router["cost"] == {"input": 0.0, "output": 0.0, "cache_read": 0.0}


def test_admin_read_failure_degrades_to_group_rows(client, settings, groups, admin):
    admin[0].side_effect = httpx.ConnectError("down")
    body = _get(client, _token(settings)).json()
    assert body["stale"] is False
    smart = _models(body)["ackstorm.smart"]
    assert smart["modalities"]["input"] == ["text", "image"]  # no pdf/audio without model_info
    assert smart["cost"]["cache_read"] == 0.0


def test_capabilities_are_cached_process_wide(client, settings, groups, admin):
    _get(client, _token(settings))
    _get(client, _token(settings, sub="bob@example.com"))
    assert admin[0].await_count == 1 and admin[1].await_count == 1


def test_stale_capabilities_are_served_without_waiting(client, settings, groups, admin, monkeypatch):
    # A copy older than CAPS_TTL: answer with it, refresh in the background.
    monkeypatch.setattr(
        opencode_config, "_caps", {"at": -10**9, "deployments": DEPLOYMENTS, "aliases": ALIASES}
    )

    async def slow(*_a, **_k):
        await asyncio.sleep(5)
        return {}

    admin[0].side_effect = slow
    body = _get(client, _token(settings)).json()
    assert body["stale"] is False
    assert "pdf" in _models(body)["ackstorm.smart"]["modalities"]["input"]


# T-S2
@pytest.mark.parametrize(
    "make_token",
    [
        lambda s: _token(s, ttl=-60),
        lambda s: _token(s, audience="other"),
        lambda s: Signer(AS_TEST_DEFAULTS["as_signing_key_pem"]).issue(
            issuer="https://evil.test", audience=s.as_audience, sub="alice@example.com",
            scope="alitellm", client_id="c1", ttl=300,
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
    assert "ackstorm.smart" not in resp.text and "mcp-aws-eks-ro" not in resp.text
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
    assert [s["name"] for s in body["skills"]] == ["mcp-setup"]


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
    for bad in ('"plugin"', '"permission"', '"agent"', '"env"', "api_key", "sk-", "{env:", "{file:"):
        assert bad not in text, bad
```

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_opencode_config.py -q` → `ImportError: cannot import name 'opencode_config'`.

- [ ] **Step 3: Implement** `src/api/app/opencode_config.py`

```python
# SPDX-License-Identifier: Apache-2.0
"""Per-user OpenCode client config: GET /clients/opencode/config.

Schema ackstorm.opencode-config/1, shared with ACH
(docs/superpowers/specs/2026-09-27-opencode-client-config-and-den.md, Rev 4).
The auth plugin calls it at every OpenCode start with its front-door access
token and merges `config` UNDER the user's own config.

Which models: exactly the chat model groups the user's OWN LiteLLM key sees.
What each is like: a process-wide admin view (deployments + alias map, master
key), used only to describe names the user's key already returned.

Hard rule: any request carrying a Bearer gets 200. An invalid token gets the
empty baseline with auth="invalid", so the plugin tells "sign in again" from
"platform down" by the body, never the status. An upstream failure gets the
last good body (stale) or skills only. Never 5xx.

Served on the API host under /clients/*, which the gateway exempts from
ext_authz: this route authenticates every request itself.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import UTC, datetime
from typing import Any

from authlib.jose.errors import JoseError
from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from app.config import Settings
from app.internal import resolve_front_key
from app.litellm_client import (
    get_model_group_aliases,
    list_deployment_capabilities,
    list_litellm_models,
)
from app.oauth_as import routes as as_routes
from app.skills import MCP_SETUP, mcp_setup_body

logger = logging.getLogger(__name__)
router = APIRouter()

SCHEMA = "ackstorm.opencode-config/1"
OPENCODE_PROVIDER_ID = "ackstorm"  # must equal PROVIDER in clients/opencode/index.mjs
CACHE_KIND = "opencode_config"
CACHE_TTL = 30 * 24 * 3600
CAPS_TTL = 3600  # model_info and aliases rarely change
UPSTREAM_DEADLINE = 1.5
DEFAULT_CONTEXT, DEFAULT_OUTPUT = 128000, 8192  # same fallbacks as alitellm-operator
_MODALITIES = (
    ("supports_vision", "image"),
    ("supports_audio_input", "audio"),
    ("supports_pdf_input", "pdf"),
    ("supports_video_input", "video"),
)
_NO_STORE = {"Cache-Control": "no-store"}

# Process-wide admin view. ponytail: per replica, no lock; two concurrent
# refreshes are harmless (same result).
_caps: dict[str, Any] = {"at": None, "deployments": {}, "aliases": {}}
_caps_task: asyncio.Task | None = None


async def _load_caps(settings: Settings) -> None:
    deployments, aliases = await asyncio.gather(
        list_deployment_capabilities(settings), get_model_group_aliases(settings)
    )
    _caps.update(at=time.monotonic(), deployments=deployments, aliases=aliases)


async def _capabilities(settings: Settings, wait: float) -> tuple[dict, dict]:
    """(deployments, aliases). Never raises.

    Stale-while-revalidate: older than CAPS_TTL → start ONE background refresh
    and answer with the copy we have. Only a cold start (no copy yet) waits for
    it, at most `wait`, then falls back to group-row values. The refresh is
    shielded so a timed-out wait does not cancel it.
    """
    global _caps_task
    if _caps["at"] is not None and time.monotonic() - _caps["at"] <= CAPS_TTL:
        return _caps["deployments"], _caps["aliases"]
    if _caps_task is None or _caps_task.done():
        _caps_task = asyncio.create_task(_load_caps(settings))
    if _caps["at"] is None:
        try:
            await asyncio.wait_for(asyncio.shield(_caps_task), wait)
        except Exception:  # noqa: BLE001 — enrichment is best effort
            logger.warning("opencode config: capability load failed or slow", exc_info=True)
    return _caps["deployments"], _caps["aliases"]


def _per_million(value: Any) -> float:
    return round(float(value or 0) * 1e6, 6)


def _model(name: str, info: dict) -> dict:
    inputs = ["text"] + [modality for flag, modality in _MODALITIES if info.get(flag)]
    return {
        "name": name,
        # attachment is what unlocks file/image attach in the OpenCode TUI.
        "attachment": len(inputs) > 1,
        "reasoning": bool(info.get("supports_reasoning")),
        "tool_call": bool(info.get("supports_function_calling")),
        "temperature": True,
        "modalities": {"input": inputs, "output": ["text"]},
        "limit": {
            "context": int(info.get("max_input_tokens") or DEFAULT_CONTEXT),
            "output": int(info.get("max_output_tokens") or DEFAULT_OUTPUT),
        },
        "cost": {
            "input": _per_million(info.get("input_cost_per_token")),
            "output": _per_million(info.get("output_cost_per_token")),
            "cache_read": _per_million(info.get("cache_read_input_token_cost")),
        },
    }


def _models(groups: list[dict], deployments: dict, aliases: dict) -> dict:
    """The user's chat groups → OpenCode model entries.

    Real model: its deployment's model_info. Alias: the target's. Router or
    unknown: the group row itself. Only names from `groups` (the user's own
    view) are ever looked up.
    """
    out = {}
    for group in groups:
        name = group.get("name")
        if not name or group.get("mode") != "chat":
            continue
        out[name] = _model(name, {**group, **deployments.get(aliases.get(name, name), {})})
    return out


def _provider(settings: Settings, models: dict) -> dict:
    base = settings.api_public_url.rstrip("/")
    if not base or not models:
        return {}
    return {
        OPENCODE_PROVIDER_ID: {
            "name": "ACKstorm",
            "npm": "@ai-sdk/openai-compatible",
            "options": {"baseURL": f"{base}/v1"},
            "models": models,
        }
    }


def _mcp(settings: Settings) -> dict:
    # ponytail: every AS_SERVICES key until spec Q-3 maps them to LiteLLM MCP
    # names; a user without access gets LiteLLM's 403 after sign-in, which the
    # mcp-setup skill explains.
    base = settings.api_public_url.rstrip("/")
    if not base:
        return {}
    return {
        svc: {"type": "remote", "url": f"{base}/mcp/{svc}", "enabled": False}
        for svc in sorted(settings.services)
    }


def _sha(value: Any) -> str:
    raw = value if isinstance(value, str) else json.dumps(value, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def _skills(settings: Settings) -> list[dict]:
    body = mcp_setup_body(settings)
    return [{"name": MCP_SETUP, "version": _sha(body), "files": {"SKILL.md": body}}]


def _body(
    user: str | None,
    provider: dict,
    mcp: dict,
    skills: list[dict],
    *,
    auth: str = "ok",
    stale: bool = False,
) -> dict:
    config = {k: v for k, v in (("provider", provider), ("mcp", mcp)) if v}
    return {
        "schema": SCHEMA,
        "version": _sha({"config": config, "skills": skills}),
        "user": user,
        "environment": None,
        "auth": auth,
        "stale": stale,
        "generatedAt": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "config": config,
        "skills": skills,
    }


async def _visible_groups(email: str, settings: Settings) -> list[dict]:
    # Under the user's own key: LiteLLM scopes the list by their team/groups.
    return await list_litellm_models(settings, await resolve_front_key(email, settings))


@router.get("/clients/opencode/config", response_model=None)
async def opencode_config(request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        return JSONResponse({"detail": "bearer token required"}, status_code=401, headers=_NO_STORE)

    signer, store = as_routes._signer, as_routes._store
    assert signer is not None and store is not None
    try:
        email = signer.verify(token, issuer=settings.as_issuer, audience=settings.as_audience)["sub"]
    except JoseError:
        # Nothing about the org leaks to a caller we cannot identify.
        return JSONResponse(_body(None, {}, {}, [], auth="invalid"), headers=_NO_STORE)

    skills = _skills(settings)
    try:
        groups, (deployments, aliases) = await asyncio.gather(
            asyncio.wait_for(_visible_groups(email, settings), UPSTREAM_DEADLINE),
            _capabilities(settings, UPSTREAM_DEADLINE),
        )
    except Exception:  # noqa: BLE001 — LiteLLM, Redis, key mint, deadline: degrade, never 5xx
        logger.warning("opencode config: upstream failed for %s, serving fallback", email, exc_info=True)
        try:
            cached = await store.get(CACHE_KIND, email)
        except Exception:  # noqa: BLE001
            cached = None
        body = {**cached, "stale": True} if cached else _body(email, {}, {}, skills, stale=True)
    else:
        models = _models(groups, deployments, aliases)
        body = _body(email, _provider(settings, models), _mcp(settings), skills)
        try:
            await store.put(CACHE_KIND, email, body, ttl=CACHE_TTL)
        except Exception:  # noqa: BLE001 — a cache write must not fail the answer
            logger.warning("opencode config: cache write failed for %s", email, exc_info=True)

    logger.info("opencode config user=%s version=%s stale=%s", email, body["version"], body["stale"])
    return JSONResponse(body, headers=_NO_STORE)
```

If `ruff check` flags the `# noqa: BLE001` markers as unused (`RUF100`), drop them.

- [ ] **Step 4: Register** in `app/main.py`, right after `app.include_router(internal_router)`:

```python
    # OpenCode client config for the auth plugin (verifies front-door tokens,
    # so it needs configure_as above).
    from app.opencode_config import router as opencode_config_router

    app.include_router(opencode_config_router)
```

- [ ] **Step 5: Run, expect PASS** — `.venv/bin/pytest tests/test_opencode_config.py -q`.

---

### Task 4: Plugin tgz at `/clients/opencode/plugin` with `platform.json`

**Files:** Modify `src/api/app/public.py`; Test `src/api/tests/test_public.py`; Modify `deploy/helm/alitellm-auth/values.yaml`

**Interfaces:**
- Consumes: baked `clients/opencode-auth.tgz` (cwd-relative, Dockerfile), `settings.api_public_url`.
- Produces: `GET /clients/opencode/plugin` and alias `GET /public/opencode-auth`, same bytes; `_plugin_tgz(api_public_url: str) -> bytes` (cached).

- [ ] **Step 1: Failing tests** — read `tests/test_public.py` first and reuse its app/settings factory and the existing plugin test's `monkeypatch.chdir` setup. Add:

```python
import gzip
import io
import json
import tarfile

from app import public


def _bake(tmp_path):
    src = io.BytesIO()
    with tarfile.open(fileobj=src, mode="w:gz") as tar:
        data = b"export const x = 1\n"
        info = tarfile.TarInfo("package/index.mjs")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    (tmp_path / "clients").mkdir()
    (tmp_path / "clients" / "opencode-auth.tgz").write_bytes(src.getvalue())
    public._plugin_tgz.cache_clear()


def _members(raw):
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        return {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}


@pytest.mark.parametrize("path", ["/clients/opencode/plugin", "/public/opencode-auth"])
def test_plugin_tgz_carries_platform_json(tmp_path, monkeypatch, path):
    monkeypatch.chdir(tmp_path)
    _bake(tmp_path)
    client = TestClient(create_app(settings=make_test_settings(api_public_url="https://api.example.com/")))
    resp = client.get(path)
    assert resp.status_code == 200
    files = _members(resp.content)
    assert files["package/index.mjs"] == b"export const x = 1\n"
    assert json.loads(files["package/platform.json"]) == {
        "api": "https://api.example.com/v1",
        "platform": "https://api.example.com",
    }


def test_plugin_tgz_bytes_are_deterministic(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _bake(tmp_path)
    first = public._plugin_tgz("https://api.example.com")
    public._plugin_tgz.cache_clear()
    assert public._plugin_tgz("https://api.example.com") == first


def test_plugin_tgz_without_api_public_url_is_the_baked_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _bake(tmp_path)
    assert public._plugin_tgz("") == (tmp_path / "clients" / "opencode-auth.tgz").read_bytes()
```

(If `make_test_settings` in `test_public.py` takes no overrides, build `Settings` the same way `test_skills.py::_settings` does.)

- [ ] **Step 2: Run, expect FAIL** — `.venv/bin/pytest tests/test_public.py -q` → 404 on `/clients/opencode/plugin` / `AttributeError: _plugin_tgz`.

- [ ] **Step 3: Implement** in `app/public.py` — replace the existing `opencode_plugin` route (keep `_OPENCODE_PLUGIN`); add imports `functools`, `gzip`, `io`, `json`, `tarfile`, `from urllib.parse import urlsplit`, `from fastapi.responses import Response` (keep whatever is still used):

```python
@functools.cache
def _plugin_tgz(api_public_url: str) -> bytes:
    """The baked plugin tarball plus package/platform.json for this deployment.

    platform.json tells the product-neutral plugin where its backend is:
    `api` for OAuth discovery and the fallback provider, `platform` (the origin
    serving /clients/*) for its config. Deterministic: baked members keep their
    metadata, platform.json gets mtime 0 and gzip mtime 0, so every replica and
    restart serves the same bytes. No API_PUBLIC_URL → the baked file as is.
    """
    baked = _OPENCODE_PLUGIN.read_bytes()
    base = api_public_url.rstrip("/")
    if not base:
        return baked
    parts = urlsplit(base)
    doc = json.dumps(
        {"api": f"{base}/v1", "platform": f"{parts.scheme}://{parts.netloc}"}, sort_keys=True
    ).encode()
    out = io.BytesIO()
    with (
        tarfile.open(fileobj=io.BytesIO(baked), mode="r:gz") as src,
        gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as gz,
        tarfile.open(fileobj=gz, mode="w") as dst,
    ):
        for member in src.getmembers():
            if member.name != "package/platform.json":
                dst.addfile(member, src.extractfile(member) if member.isfile() else None)
        info = tarfile.TarInfo("package/platform.json")
        info.size, info.mode, info.mtime = len(doc), 0o644, 0
        dst.addfile(info, io.BytesIO(doc))
    return out.getvalue()


# /public/opencode-auth is the original install URL, saved in users' opencode.json
# by `opencode plugin <url> -g`: a PERMANENT alias, never remove it.
@router.get("/clients/opencode/plugin", response_model=None)
@router.get("/public/opencode-auth", response_model=None)
async def opencode_plugin(request: Request) -> Response:
    """The OpenCode auth plugin as an npm tarball: `opencode plugin <this URL> -g`."""
    if not _OPENCODE_PLUGIN.is_file():
        raise HTTPException(status_code=404)
    body = _plugin_tgz(request.app.state.settings.api_public_url)
    return Response(
        body,
        media_type="application/gzip",
        headers={"Content-Disposition": 'attachment; filename="opencode-auth.tgz"'},
    )
```

Note: `public_router` is included before the `/public` StaticFiles mount, so the alias route still wins over the mount (as today).

- [ ] **Step 4: Chart** — `deploy/helm/alitellm-auth/values.yaml`, `istio.exemptPaths`, add after `"/.well-known/*"`:

```yaml
    # OpenCode client endpoints: the tarball is anonymous and the config route
    # verifies the front-door JWT itself (ext_authz would strip it). Anything
    # under /clients/ MUST authenticate its own requests.
    - "/clients/*"
```

Run `helm template deploy/helm/alitellm-auth --set istio.enabled=true --set istio.gateway.name=gw | grep -A6 notPaths` → `/clients/*` listed.

- [ ] **Step 5: Run, expect PASS** — `.venv/bin/pytest tests/test_public.py -q`.

---

### Task 5: Docs, gates, review

- [ ] **CHANGELOG.md** under `## [unreleased]` → `### Added` (below the mcp-setup entry):

```markdown
- **OpenCode client endpoints under `/clients/opencode/`** (spec Rev 4, shared
  with ACH). `GET /clients/opencode/config` (`ackstorm.opencode-config/1`):
  per-user config for the auth plugin, authenticated by the front-door access
  token (`Signer.verify`). Models = the chat model groups the user's own key
  sees, described from LiteLLM (`/v2/model/info` + the alias map, master key,
  cached 1 h, refreshed in the background): aliases take their target's context, costs incl. cache read,
  and image/pdf/audio input. Every `AS_SERVICES` MCP server as a disabled
  remote entry, plus the `mcp-setup` skill. Always 200 for a Bearer (invalid
  token → empty baseline); upstream failure serves the last good body
  (`stale: true`, 30 d). `GET /clients/opencode/plugin`: the plugin tarball
  with a per-deployment `package/platform.json`; `/public/opencode-auth` is a
  permanent alias. Chart: `/clients/*` added to `istio.exemptPaths`; the API
  host's HTTPRoute needs `PathPrefix /clients/` → alitellm-auth (gitops).
```

- [ ] **CLAUDE.md**:
  - Key files table, row after `openwork.py`:
    `| src/api/app/opencode_config.py | GET /clients/opencode/config — per-user OpenCode config (ackstorm.opencode-config/1, shared with ACH). Bearer = front-door JWT (Signer.verify). Always 200 for a Bearer; never 5xx. Spec Rev 4 |`
  - Under "Per-user key scoping", append: "**Exception by design — `/clients/opencode/config`**: visibility still comes from the user's own key; the master key only DESCRIBES those names (`/v2/model/info`, alias map). Never let the admin view add a model."
  - Under "Public Static Artifacts" (or a new short section): "`/clients/*` on the API host is exempt from ext_authz; every route there authenticates itself."
- [ ] **Gates**:

```bash
cd src/api && .venv/bin/pytest tests/ -q > /tmp/pt.log 2>&1; echo EXIT=$?; tail -3 /tmp/pt.log
uvx ruff@0.8.4 check app tests && uvx ruff@0.8.4 format --check app tests
helm template ../../deploy/helm/alitellm-auth > /dev/null && echo chart-ok
```

- [ ] **Smoke (docker-compose dev stack, optional)**: `curl -s http://localhost:8080/clients/opencode/plugin | tar -xzO package/platform.json`; config with a token minted via `opencode auth login -p ackstorm` against the stack.
- [ ] **One review** of the whole diff (`cavecrew-reviewer` or `/code-review`), fix, then commit via `git:commit-push` subagent after user approval: `feat(opencode): per-user client config and plugin endpoints`.

## Out of scope (next plans)

- Plugin (Node): `platform.json` discovery, minimal provider, `config` hook, cache, skills dir (spec T5), then a tagged release for ACH to vendor.
- T6 integration against a pinned `opencode` binary; T7 pilot; gitops HTTPRoute; How-To/README (install story).
- `variants`: none sent. OpenCode (1.18.31, v1 loader) auto-generates `low/medium/high` (`{reasoningEffort}`) for any `reasoning: true` openai-compatible model, which already works today. Add config variants (extra efforts from `supported_reasoning_efforts`, `{disabled: true}` for unsupported auto ones; config merges on top) only if a model rejects an auto effort.
