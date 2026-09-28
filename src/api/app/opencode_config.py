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
from app.skills import GENAI_API, genai_api_body

logger = logging.getLogger(__name__)
router = APIRouter()

SCHEMA = "ackstorm.opencode-config/1"
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
    # Swallow the failure here, not just at the cold-start awaiter: a stale-but-warm
    # cache skips awaiting this task entirely, and an unretrieved exception on a
    # background task logs an "exception was never retrieved" traceback on every
    # GC'd retry for as long as the upstream stays down.
    try:
        deployments, aliases = await asyncio.gather(
            list_deployment_capabilities(settings), get_model_group_aliases(settings)
        )
    except Exception:  # noqa: BLE001 — background refresh; caller already has a copy to serve
        logger.warning("opencode config: background capability refresh failed", exc_info=True)
        return
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
        settings.provider_name: {
            "name": settings.provider_name,
            "npm": "@ai-sdk/openai-compatible",
            "options": {"baseURL": f"{base}/v1"},
            "models": models,
        }
    }


def _mcp(settings: Settings) -> dict:
    # ponytail: every AS_SERVICES key until spec Q-3 maps them to LiteLLM MCP
    # names; a user without access gets LiteLLM's 403 after sign-in, which the
    # genai-api skill explains.
    base = settings.api_public_url.rstrip("/")
    if not base:
        return {}
    return {
        svc: {"type": "remote", "url": f"{base}/mcp/{svc}", "enabled": False}
        for svc in sorted(settings.services)
    }


def _sha(value: Any) -> str:
    raw = (
        value
        if isinstance(value, str)
        else json.dumps(value, sort_keys=True, separators=(",", ":"))
    )
    return "sha256:" + hashlib.sha256(raw.encode()).hexdigest()


def _skills(settings: Settings) -> list[dict]:
    body = genai_api_body(settings)
    return [{"name": GENAI_API, "version": _sha(body), "files": {"SKILL.md": body}}]


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
        email = signer.verify(token, issuer=settings.as_issuer, audience=settings.as_audience)[
            "sub"
        ]
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
        logger.warning(
            "opencode config: upstream failed for %s, serving fallback", email, exc_info=True
        )
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

    logger.info(
        "opencode config user=%s version=%s stale=%s", email, body["version"], body["stale"]
    )
    return JSONResponse(body, headers=_NO_STORE)
