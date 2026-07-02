# SPDX-License-Identifier: Apache-2.0
"""Admin endpoints for LiteLLM user management."""

from __future__ import annotations

import hmac
import logging

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import Settings
from app.litellm_client import (
    LiteLLMUserNotFound,
    delete_litellm_user,
    get_litellm_user,
    list_litellm_keys,
    list_litellm_users,
    strip_bearer_prefix,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/users", tags=["admin"])


async def require_admin(api_key: str, settings: Settings) -> None:
    """Constant-time master-key comparison — never use == for secrets.

    Compare on UTF-8 bytes (not str): hmac.compare_digest raises TypeError on
    non-ASCII str inputs, and Starlette decodes raw header bytes as latin-1, so
    any byte 0x80-0xFF in the header would otherwise turn a should-be-403 into a
    500 for an unauthenticated caller (WR-03). bytes comparison stays
    constant-time for any input.
    """
    if not hmac.compare_digest(
        api_key.encode("utf-8"), settings.litellm_master_key.encode("utf-8")
    ):
        raise HTTPException(status_code=403, detail="Admin privileges required")


async def _guard(request: Request, header: str | None) -> Settings:
    if not header:
        raise HTTPException(status_code=401, detail="Missing x-alitellm-auth-api-key header")
    api_key = strip_bearer_prefix(header)
    settings: Settings = request.app.state.settings  # same as auth.py lines 70, 265
    await require_admin(api_key, settings)
    return settings


@router.get("", response_model=None)
async def list_users(
    request: Request,
    x_alitellm_auth_api_key: str | None = Header(default=None),
    page: int = 1,
    page_size: int = 100,
    role: str | None = None,
    email: str | None = None,
) -> JSONResponse:
    settings = await _guard(request, x_alitellm_auth_api_key)
    users = await list_litellm_users(
        settings, page=page, page_size=page_size, role=role, email=email
    )
    return JSONResponse({"users": users, "count": len(users)})


@router.get("/{email}", response_model=None)
async def get_user(
    request: Request,
    email: str,
    x_alitellm_auth_api_key: str | None = Header(default=None),
) -> JSONResponse:
    settings = await _guard(request, x_alitellm_auth_api_key)
    try:
        user = await get_litellm_user(email, settings)
    except LiteLLMUserNotFound:
        raise HTTPException(status_code=404, detail="User not found")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (400, 404):
            raise HTTPException(status_code=404, detail="User not found")
        raise HTTPException(status_code=502, detail="LiteLLM user lookup failed")
    except httpx.RequestError:
        # Backend unreachable → 502, not uncaught 500 (WR-01).
        raise HTTPException(status_code=502, detail="LiteLLM backend unreachable")
    try:
        raw_keys = await list_litellm_keys(email, settings)
        # Strip raw sk-... token from inspect output (security: T-03-07)
        keys = [{k: v for k, v in kd.items() if k != "key"} for kd in raw_keys]
    except (httpx.HTTPStatusError, httpx.RequestError, ValueError) as exc:
        # list_litellm_keys hydrates string-form keys via get_key_info, which
        # can raise ValueError on non-dict payloads and RequestError when the
        # backend is unreachable. All of these are backend failures, not 500s
        # (WR-04). Log server-side, return a generic 502.
        logger.error("Admin key lookup failed for %s: %s", email, exc)
        raise HTTPException(status_code=502, detail="LiteLLM key lookup failed")
    return JSONResponse({**user, "keys": keys})


@router.delete("/{email}", response_model=None)
async def remove_user(
    request: Request,
    email: str,
    x_alitellm_auth_api_key: str | None = Header(default=None),
) -> JSONResponse:
    settings = await _guard(request, x_alitellm_auth_api_key)
    # D-02: pre-check existence before destructive call
    try:
        await get_litellm_user(email, settings)
    except LiteLLMUserNotFound:
        raise HTTPException(status_code=404, detail="User not found")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (400, 404):
            raise HTTPException(status_code=404, detail="User not found")
        raise HTTPException(status_code=502, detail="LiteLLM user lookup failed")
    except httpx.RequestError:
        # Backend unreachable on the destructive pre-check → 502, never a
        # misleading 404 or uncaught 500 (WR-01/WR-05).
        raise HTTPException(status_code=502, detail="LiteLLM backend unreachable")
    try:
        await delete_litellm_user(email, settings)
    except httpx.HTTPStatusError as exc:
        # Never interpolate the raw backend exception (which carries resp.text
        # via _extract_litellm_error) into the client body. Mirror the auth.py
        # WR-05 delete_token treatment: log server-side, return generic detail
        # (WR-02).
        logger.error("Admin delete failed for user %s: %s", email, exc)
        raise HTTPException(status_code=502, detail="Failed to delete user")
    except httpx.RequestError:
        # Backend unreachable on the destructive call → 502 (WR-01).
        logger.error("Admin delete unreachable for user %s", email)
        raise HTTPException(status_code=502, detail="Failed to delete user")
    logger.info("Admin deleted LiteLLM user %s", email)
    return JSONResponse({"status": "deleted", "user_id": email})
