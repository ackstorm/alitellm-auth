# SPDX-License-Identifier: Apache-2.0
"""Each user's own LiteLLM key, and the endpoint that hands it out.

`resolve_front_key(sub)` returns the LiteLLM key for a user. The key is minted
once under a per-user lock and kept Fernet-encrypted in the AS store. Before a
stored key is returned, LiteLLM is asked whether it still recognizes it; a
revoked or expired key is discarded and re-minted.

`POST /api/internal/front-key {"sub"}` is that function over HTTP, for the Go
authorization proxy. The session API calls the function directly -- both callers
end at the SAME key, which is the point: what the console reads about a user is
read with the very credential that user's clients present at the gateway.
"""

from __future__ import annotations

import asyncio
import hmac
import logging

import httpx
from cryptography.fernet import Fernet
from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from app.config import Settings
from app.litellm_client import generate_litellm_key, get_key_info
from app.oauth_as import routes as as_routes

logger = logging.getLogger(__name__)
router = APIRouter()

FRONT_ALIAS = "front"
MINT_LOCK_TTL = 10
MINT_WAIT_SECONDS = 0.5


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _authorized(request: Request, settings: Settings) -> bool:
    presented = request.headers.get("x-internal-token", "")
    return bool(settings.internal_token) and hmac.compare_digest(presented, settings.internal_token)


async def _key_alive(key: str, settings: Settings) -> bool:
    """Return false only when LiteLLM positively rejects the key."""
    try:
        await get_key_info(key, settings)
        return True
    except httpx.HTTPStatusError as exc:
        return exc.response.status_code >= 500
    except httpx.HTTPError:
        return True


class FrontKeyUnavailable(Exception):
    """LiteLLM could not mint the user's key."""


class FrontKeyMintInProgress(Exception):
    """Another request holds the mint lock; the caller should retry shortly."""


async def resolve_front_key(sub: str, settings: Settings) -> str:
    """The user's LiteLLM key, minted on first use and reused after.

    ``sub`` is a LiteLLM user id (an email here) and MUST come from an
    authenticated identity -- a session, or a token the authz proxy verified --
    never from client input. It selects whose credential is handed back.
    """
    store = as_routes._store
    assert store is not None
    fernet = Fernet(settings.as_key_encryption_key.encode())

    record = await store.get("frontkey", sub)
    if record is not None:
        key = fernet.decrypt(record["enc"].encode()).decode()
        if await _key_alive(key, settings):
            return key
        logger.warning(
            "Stored front key no longer accepted by LiteLLM (key id %s); re-minting",
            record.get("id"),
        )
        await store.pop("frontkey", sub)

    lock = f"mint:{sub}"
    if not await store.acquire(lock, ttl=MINT_LOCK_TTL):
        await asyncio.sleep(MINT_WAIT_SECONDS)
        record = await store.get("frontkey", sub)
        if record is not None:
            return fernet.decrypt(record["enc"].encode()).decode()
        raise FrontKeyMintInProgress(sub)

    try:
        # Re-read after acquiring the lock: a concurrent request may have minted
        # the user's key between our initial read and lock acquisition.
        record = await store.get("frontkey", sub)
        if record is not None:
            return fernet.decrypt(record["enc"].encode()).decode()
        try:
            minted = await generate_litellm_key(sub, settings, alias=FRONT_ALIAS)
        except httpx.HTTPError as exc:
            logger.error("Could not mint the front key for a user: %s", exc)
            raise FrontKeyUnavailable(sub) from exc
        await store.put(
            "frontkey",
            sub,
            {"enc": fernet.encrypt(minted["key"].encode()).decode(), "id": minted.get("id")},
        )
        logger.info("Minted the front key for a user (key id %s)", minted.get("id"))
        return minted["key"]
    finally:
        await store.release(lock)


@router.post("/api/internal/front-key")
async def front_key(request: Request) -> JSONResponse:
    settings = _settings(request)
    if not _authorized(request, settings):
        return JSONResponse({"error": "forbidden"}, status_code=403)

    body = await request.json()
    sub = str(body.get("sub") or "").strip().lower()
    if not sub:
        return JSONResponse({"error": "sub required"}, status_code=400)

    try:
        return JSONResponse({"key": await resolve_front_key(sub, settings)})
    except FrontKeyMintInProgress:
        return JSONResponse(
            {"error": "mint_in_progress"}, status_code=503, headers={"Retry-After": "1"}
        )
    except FrontKeyUnavailable:
        return JSONResponse({"error": "litellm_unavailable"}, status_code=502)
