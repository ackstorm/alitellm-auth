# SPDX-License-Identifier: Apache-2.0
"""LiteLLM custom auth — the alitellm-auth <-> LiteLLM user-scoping contract.

CANONICAL SOURCE. This file is deployed onto the *LiteLLM* proxy (NOT alitellm-auth),
but the contract is OWNED here because alitellm-auth depends on it: the console's
per-user Models/MCPs pages call LiteLLM with the master key PLUS an ``x-user-id``
header, and this custom auth resolves that to the user's default key (impersonation),
so each user sees only their own entitlements instead of the global admin catalog.

Contract (what alitellm-auth relies on, and verifies at startup):
  * master key, NO x-user-id        -> genuine admin call        (native auth)
  * NOT the master key (a real sk-) -> normal virtual-key call   (native auth)
  * master key + x-user-id          -> IMPERSONATE that user's DEFAULT key; on ANY
                                       failure HARD-REJECT (403/503) and NEVER fall
                                       back to admin (that would be privilege escalation)

alitellm-auth verifies this at startup by calling ``/v1/models`` with the master key
and a deliberately non-existent ``x-user-id``: a 401/403 means the contract holds; a
2xx means this custom auth is NOT installed (the master key fell through to admin) and
alitellm-auth logs a CRITICAL banner. See app/contract.py + app/litellm_client.py
(verify_user_scoping_contract) and deploy/litellm/README.md.

Install: mount this file into the LiteLLM container and set, in the LiteLLM config:
    custom_auth: auth_user_map.sso_key_swapper
    custom_auth_settings:
      mode: "auto"   # required: a plain Exception falls back to native auth; a
                     # ProxyException hard-rejects (used here to block escalation)

`mode: "auto"` is load-bearing: the not-master / no-x-user-id branches raise a plain
Exception so native auth runs, while every impersonation failure raises ProxyException
(a FastAPI HTTPException would be SWALLOWED as a fallback in auto mode -> admin).
"""

import json
import os
from datetime import datetime, timezone

from fastapi import Request
from litellm.proxy import proxy_server
from litellm.proxy._types import ProxyException, UserAPIKeyAuth

MASTER_KEY = os.getenv("PROXY_MASTER_KEY")

if MASTER_KEY is None:
    # Fail CLOSED: without the master key the `api_key != MASTER_KEY` check below
    # matches every request, so the master+x-user-id impersonation branch is never
    # reached and those calls fall through to native auth as full admin — the
    # per-user scoping contract silently fails open. Refuse to start instead.
    raise RuntimeError(
        "PROXY_MASTER_KEY is not set. Refusing to start: the sso_key_swapper "
        "master-key check requires it, and without it per-user scoping fails open to admin."
    )


def _parse_metadata(meta) -> dict:
    if isinstance(meta, str):
        try:
            return json.loads(meta)
        except json.JSONDecodeError:
            return {}
    return meta if isinstance(meta, dict) else {}


def _key_is_usable(k, now_utc: datetime) -> bool:
    """Skip blocked or expired keys."""
    if getattr(k, "blocked", False) is True:
        return False

    if k.expires is not None:
        expires = k.expires
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if now_utc >= expires:
            return False
    return True


async def sso_key_swapper(request: Request, api_key: str):
    # ---- FALL BACK to native LiteLLM auth (plain Exception; auto-mode swallows it) ----
    # Not the master key => a real virtual key (sk-). Let native auth validate it.
    if api_key != MASTER_KEY:
        raise Exception("not master key -> native auth")
    # No x-user-id => a genuine master-key call (admin). Let native auth handle it.
    x_user_id = request.headers.get("x-user-id")
    if not x_user_id:
        raise Exception("no x-user-id -> native auth")

    # ---- From here it is an IMPERSONATION request (master key + x-user-id). ----
    # NEVER fall back now: a fallback would authenticate as the MASTER key = full
    # admin (privilege escalation). Every failure below HARD-REJECTS via
    # ProxyException (HTTPException would be swallowed as a fallback in auto mode).
    if not proxy_server.prisma_client or not proxy_server.prisma_client.db:
        raise ProxyException(
            message="Auth backend unavailable. Try again shortly.",
            type="auth_error",
            param="x-user-id",
            code=503,
        )
    db = proxy_server.prisma_client.db

    # 1) The user must exist. Missing => 403, NO fallback.
    user = await db.litellm_usertable.find_unique(where={"user_id": x_user_id})
    if user is None:
        raise ProxyException(
            message=f"Access denied: no LiteLLM user for '{x_user_id}'.",
            type="auth_error",
            param="x-user-id",
            code=403,
        )

    # 2) The user must have a usable DEFAULT key (metadata.is_default == True),
    #    skipping blocked/expired. None => 403, NO fallback.
    now_utc = datetime.now(timezone.utc)
    user_keys = await db.litellm_verificationtoken.find_many(
        where={"user_id": x_user_id}
    )
    target_key = None
    parsed_metadata: dict = {}
    for k in user_keys:
        if not _key_is_usable(k, now_utc):
            continue
        meta = _parse_metadata(k.metadata)
        if meta.get("is_default") is True:
            target_key = k
            parsed_metadata = meta
            break
    if target_key is None:
        raise ProxyException(
            message=(
                f"Access denied: no active default key for '{x_user_id}'. "
                "Set a default key in the console."
            ),
            type="auth_error",
            param="x-user-id",
            code=403,
        )

    # 3) Resolve the team's model access. Native auth populates
    #    UserAPIKeyAuth.team_models from the team row; we hand-build the object, so
    #    we must do the same. Without it, a key whose models is empty or
    #    ["all-team-models"] resolves to NO restriction, and the catalog routes
    #    (/v1/models, /model_group/info) fall through to the FULL proxy model list
    #    -> every user sees the global admin catalog (visibility leak / scoping
    #    silently degrades to admin).
    team_models: list = []
    if target_key.team_id:
        team = await db.litellm_teamtable.find_unique(
            where={"team_id": target_key.team_id}
        )
        if team is not None and team.models:
            team_models = list(team.models)

    # 4) Impersonate the default key.
    return UserAPIKeyAuth(
        api_key=target_key.token,
        key_name=target_key.key_name,
        token=target_key.token,
        key_alias=target_key.key_alias,
        user_id=target_key.user_id,
        team_id=target_key.team_id,
        models=target_key.models or [],
        team_models=team_models,
        max_budget=target_key.max_budget,
        spend=target_key.spend or 0.0,
        tpm_limit=target_key.tpm_limit,
        rpm_limit=target_key.rpm_limit,
        expires=target_key.expires,
        metadata=parsed_metadata,
        allowed_routes=target_key.allowed_routes,
    )
