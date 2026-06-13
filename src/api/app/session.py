# SPDX-License-Identifier: Apache-2.0
"""Session-cookie-authenticated JSON API for the dashboard SPA.

Provides:
  - require_session_user: FastAPI dependency that resolves the current user
    from the signed session cookie or raises 401 (D-05/D-06).
  - assert_same_origin: Origin/Referer write-guard for POST/DELETE (D-18).
  - router (/api/session/*): /me, /keys GET/POST/DELETE, /stats.

The /ui route is served by a StaticFiles mount in main.py (D-03) — not here.

Security baseline (D-18):
  - Cookie auth via Starlette SessionMiddleware (signed, NOT encrypted — D-01).
  - POST/DELETE require same-origin Origin/Referer and application/json content-type.
  - Master key never reaches the browser — all LiteLLM calls are server-side.
  - D-01: session stores ONLY {sub, email, name, authenticated_at}; NEVER any secret.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from app.config import Settings
from app.litellm_client import (
    LiteLLMUserNotFound,
    block_litellm_key,
    delete_litellm_key,
    generate_litellm_key,
    get_litellm_user,
    get_team_member_budget,
    list_litellm_a2a_agents,
    list_litellm_mcp_servers,
    list_litellm_models,
    list_session_keys,
    set_litellm_key_default,
    spend_logs_last_used,
    user_daily_activity,
)
from app.stats import aggregate_window, build_stats_contract, resolve_key_display

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

# /api/session/* — JSON API for the SPA (401 on unauthenticated, D-05)
router = APIRouter(prefix="/api/session", tags=["session"])

# ---------------------------------------------------------------------------
# Stats range bounds (D-04 / RESEARCH §4)
# ---------------------------------------------------------------------------

# Default window: 30 days ending today (UTC), matching the removed /usage default.
_DEFAULT_RANGE_DAYS = 30
# Max custom range (RESEARCH §4): 366 days covers a full year; bounds abuse/cost
# (the prior window doubles the fetch to ~732 days across two calls — acceptable).
_MAX_RANGE_DAYS = 366

# Capability defaults baked from 12-SPIKE-FINDINGS.md (all true on prod v1.85.1).
# build_stats_contract flips per_model_last_used to false when last_used is empty.
_CAPABILITY_DEFAULTS = {
    "token_split": True,
    "per_model_last_used": True,
    "deltas": True,
    "per_key_spend": True,
}


# ---------------------------------------------------------------------------
# Security dependencies
# ---------------------------------------------------------------------------


def require_session_user(request: Request) -> dict:
    """Resolve {email, name} from the signed session cookie, or raise 401.

    For /api/session/* routes only (D-05). The SPA handles 401 by redirecting
    client-side. Page routes like /ui use an inline 302 check instead.
    """
    sess = request.session  # Starlette 1.2.1 populates scope["session"]
    email = sess.get("email")
    if not email:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"email": email, "name": sess.get("name") or email}


def assert_same_origin(request: Request, settings: Settings) -> None:
    """Cheap CSRF baseline for POST/DELETE writes (formal token → Phase 11, D-18).

    Rejects cross-origin requests (wrong Origin/Referer) with 403 and
    non-JSON content-type with 415. Call at the TOP of every POST/DELETE handler.

    D-18: this is a baseline, not a complete CSRF defense. A formal CSRF token
    and session-lifetime hardening are deferred to Phase 11 (SEC-01).
    """
    # D-02 (CR-01 fix): exact-origin compare, fail-closed when both headers absent.
    # Compare (scheme, hostname, port) tuples — hostname/port (NOT netloc) defeats
    # userinfo-spoof (...ai@evil) and the platform.ackstorm.ai.evil.com prefix attack.
    raw = request.headers.get("origin") or request.headers.get("referer")
    if not raw:
        raise HTTPException(status_code=403, detail="Missing Origin/Referer")
    allowed = urlparse(settings.app_base_url)
    got = urlparse(raw)
    if (got.scheme, got.hostname, got.port) != (
        allowed.scheme,
        allowed.hostname,
        allowed.port,
    ):
        raise HTTPException(status_code=403, detail="Cross-origin request rejected")
    content_type = request.headers.get("content-type", "").split(";")[0].strip()
    if content_type != "application/json":
        raise HTTPException(status_code=415, detail="application/json required")


# ---------------------------------------------------------------------------
# Pydantic models for request bodies
# ---------------------------------------------------------------------------


class CreateKeyBody(BaseModel):
    """Optional body for POST /api/session/keys (SAPI-04/D-10)."""

    alias: str | None = None
    duration: str | None = None


class BlockKeyBody(BaseModel):
    """Body for POST /api/session/keys/{id}/block — desired disabled state."""

    blocked: bool


# ---------------------------------------------------------------------------
# Helper: derive spend.source from LiteLLM user data (RESEARCH RQ-1 / D-09a)
# ---------------------------------------------------------------------------

_SPEND_SOURCE_UNKNOWN = "unknown"


def _derive_spend(user: dict[str, Any]) -> dict[str, Any]:
    """User-level {current, source} from the LiteLLM user budget fields.

    The team-member cap is owned by _budget_block (read from the live membership);
    the prior team_member/team branches here were unreachable because
    _normalize_user never carried those fields (#1), so they are dropped.

    `spend` defaults to 0.0 in _normalize_user even when absent, so it is NOT a
    reliable "user has budget data" signal on its own. Gate the user branch on a
    configured budget OR a genuinely non-zero spend; otherwise report "unknown"
    so "no budget configured" users are not mislabeled as source="user" (WR-01).
    """
    user_spend = user.get("spend", 0.0)
    user_budget = user.get("max_budget")
    if user_budget is not None or user_spend:
        return {"current": float(user_spend or 0), "source": "user"}
    return {"current": 0.0, "source": _SPEND_SOURCE_UNKNOWN}


def _budget_block(user: dict[str, Any], member: dict[str, Any] | None) -> dict[str, Any]:
    """Canonical {current, max_budget, budget_duration, source} for /me and /stats.

    Prefers the ENFORCED per-member team budget (#1/RQ-1, read via
    get_team_member_budget); falls back to the reporting-only user-level figures
    when no membership budget is available. budget_duration on the membership is
    usually null in this deployment, so it falls back to the user-level value
    (informational only).
    """
    if member is not None:
        return {
            "current": float(member.get("current") or 0),
            "max_budget": member.get("max_budget"),
            "budget_duration": member.get("budget_duration") or user.get("budget_duration"),
            "source": "team_member",
        }
    spend = _derive_spend(user)
    return {
        "current": spend["current"],
        "max_budget": user.get("max_budget"),
        "budget_duration": user.get("budget_duration"),
        "source": spend["source"],
    }


def _build_limits(user: dict[str, Any]) -> dict[str, Any] | None:
    """Build the limits block from the user object. Returns None if all fields absent."""
    limits = {
        "max_budget": user.get("max_budget"),
        "budget_duration": user.get("budget_duration"),
        "tpm_limit": user.get("tpm_limit"),
        "rpm_limit": user.get("rpm_limit"),
    }
    # If all limits are None, the user object is effectively empty
    if all(v is None for v in limits.values()):
        return None
    return limits


# ---------------------------------------------------------------------------
# /api/session/* routes
# ---------------------------------------------------------------------------


@router.get("/me", response_model=None)
async def session_me(
    request: Request,
    user: dict = Depends(require_session_user),
) -> JSONResponse:
    """Return identity + limits + spend for the session user (SAPI-02/D-09a).

    Gracefully degrades to null limits and spend=0/unknown when the LiteLLM
    user enrichment fails (D-09). Always returns a 200 with identity present.
    """
    settings: Settings = request.app.state.settings
    email = user["email"]
    name = user["name"]
    team_id = settings.team_id

    # Fetch the user object and the ENFORCED per-member budget concurrently;
    # each degrades independently and never 502s (D-09). The membership cap
    # (max_budget_in_team) is what actually enforces for team-scoped keys — it
    # wins over the user-level max_budget that only reports (#1/RQ-1).
    litellm_user: dict = {}
    member_budget: dict | None = None
    try:
        user_res, member_res = await asyncio.gather(
            get_litellm_user(email, settings),
            get_team_member_budget(email, settings),
            return_exceptions=True,
        )
        if isinstance(user_res, LiteLLMUserNotFound):
            logger.info("session_me: user %s not found in LiteLLM, degrading", email)
        elif isinstance(user_res, BaseException):
            logger.error("session_me: enrichment failed for %s: %s", email, user_res)
        else:
            litellm_user = user_res
        if isinstance(member_res, BaseException):
            logger.warning("session_me: member-budget fetch failed for %s: %s", email, member_res)
        else:
            member_budget = member_res
    except Exception as exc:  # defensive: gather itself should not raise
        logger.error("session_me: budget gather failed for %s: %s", email, exc)

    block = _budget_block(litellm_user, member_budget)
    spend = {"current": block["current"], "source": block["source"]}
    limits = _build_limits(litellm_user)
    # When the enforced membership budget is present, override the user-level
    # max_budget/budget_duration with it (tpm/rpm stay from the user object).
    if block["max_budget"] is not None or block["budget_duration"] is not None:
        limits = {
            **(limits or {"tpm_limit": None, "rpm_limit": None}),
            "max_budget": block["max_budget"],
            "budget_duration": block["budget_duration"],
        }

    return JSONResponse(
        {
            "email": email,
            "name": name,
            "team_id": team_id,
            "endpoint": settings.api_public_url,
            "limits": limits,
            "spend": spend,
        }
    )


@router.get("/keys", response_model=None)
async def session_list_keys(
    request: Request,
    user: dict = Depends(require_session_user),
) -> JSONResponse:
    """List the session user's virtual keys (SAPI-03/D-08).

    Uses the server master key only — the browser never sees the master key.
    Returns the SAPI-03 metadata shape per key (no sk- token).
    """
    settings: Settings = request.app.state.settings
    email = user["email"]
    try:
        keys = await list_session_keys(email, settings)
    except httpx.HTTPStatusError as exc:
        logger.error("session_list_keys: list failed for %s: %s", email, exc)
        raise HTTPException(status_code=502, detail="LiteLLM key listing failed")
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="LiteLLM backend unreachable")
    # D-17: never expose the raw sk- ("key"), the server-side delete hash ("token"),
    # nor the raw "metadata" (may hold factory user_meta_extra) to the browser.
    # The derived "is_default" bool DOES go to the browser.
    safe_keys = [
        {k: v for k, v in kd.items() if k not in ("key", "token", "metadata")} for kd in keys
    ]
    return JSONResponse({"keys": safe_keys})


@router.post("/keys", response_model=None)
async def session_create_key(
    request: Request,
    user: dict = Depends(require_session_user),
) -> JSONResponse:
    """Mint a new virtual key for the session user (SAPI-04/D-10/D-11).

    Accepts an optional JSON body {alias?, duration?}. No body is valid.
    Returns the sk- once in the response — it is NEVER stored server-side.
    D-10: a supplied duration is threaded into /key/generate (never null);
          a supplied alias overrides the readable+unique default.
    """
    settings: Settings = request.app.state.settings
    assert_same_origin(request, settings)

    email = user["email"]
    name = user["name"]

    # Parse optional body. WR-03: distinguish "no body" (valid → defaults) from a
    # "malformed body" (non-empty payload that fails schema coercion → 422). The
    # prior bare `except Exception: pass` silently dropped a client's requested
    # alias/duration when JSON coercion failed, minting a defaults key without error.
    body = CreateKeyBody()
    raw_body = await request.body()
    stripped = raw_body.strip() if raw_body else b""
    if stripped and stripped != b"{}":
        try:
            body = CreateKeyBody.model_validate_json(raw_body)
        except ValidationError:
            raise HTTPException(status_code=422, detail="invalid request body")

    # Validate alias (safe chars + length bound) if provided
    alias: str | None = body.alias
    if alias is not None:
        alias = alias.strip()
        if not alias or len(alias) > 128:
            raise HTTPException(status_code=422, detail="alias must be 1-128 characters")
        # Only allow alphanumeric, dash, underscore, dot
        if not all(c.isalnum() or c in "-_." for c in alias):
            raise HTTPException(
                status_code=422,
                detail="alias may only contain alphanumeric, dash, underscore, dot",
            )

    # Validate duration if provided (LiteLLM duration string, e.g. "90d", "30d", "7d")
    duration: str | None = body.duration
    if duration is not None:
        duration = duration.strip()
        if not duration:
            duration = None
        else:
            # Basic format check: number + d/h/m (e.g. "90d", "24h", "30m")
            import re

            if not re.match(r"^\d+[dhms]$", duration):
                raise HTTPException(
                    status_code=422,
                    detail="duration must be a LiteLLM duration string (e.g. '90d', '24h')",
                )

    try:
        key_data = await generate_litellm_key(
            email, settings, name=name, duration=duration, alias=alias
        )
    except httpx.HTTPStatusError as exc:
        logger.error("session_create_key: key generation failed for %s: %s", email, exc)
        # The stored key_alias is an opaque lk-{random} token, so name collisions
        # should never happen — but if LiteLLM ever returns a unique-alias 400,
        # surface it as a 422 on the name field (the create modal routes it there)
        # rather than a generic 502.
        resp = exc.response
        if resp is not None and resp.status_code == 400 and "already exists" in resp.text.lower():
            raise HTTPException(
                status_code=422,
                detail=f"A key named '{alias}' already exists. Choose a different name.",
            )
        raise HTTPException(status_code=502, detail="Key generation failed")
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="LiteLLM backend unreachable")

    # If the user has NO default key, make the key we JUST created the default.
    # This is a presence check, not a positional one — it does not matter whether
    # this is the 1st key or the 5th; whenever no default exists, the new key
    # becomes it (so the very first key is default, and the user is never left
    # without one). An existing default is never silently reassigned (that stays
    # explicit-only via the kebab). Non-fatal: the key is already minted, so any
    # failure here just leaves it un-defaulted (the user can set one manually).
    is_default = False
    try:
        user_keys = await list_session_keys(email, settings)
        if not any(k.get("is_default") for k in user_keys):
            new_key = next((k for k in user_keys if k.get("id") == key_data["id"]), None)
            if new_key is not None:
                await set_litellm_key_default(
                    new_key["token"],
                    settings,
                    is_default=True,
                    existing_metadata=new_key.get("metadata") or {},
                )
                is_default = True
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        logger.warning("session_create_key: auto-default failed for %s: %s", email, exc)

    # Return the sk- ONCE — it is never stored and cannot be recovered (SAPI-04)
    return JSONResponse(
        {
            "key": key_data["key"],
            "id": key_data["id"],
            "team_id": key_data.get("team_id"),
            "is_default": is_default,
        }
    )


@router.delete("/keys/{key_id}", response_model=None)
async def session_delete_key(
    request: Request,
    key_id: str,
    user: dict = Depends(require_session_user),
) -> JSONResponse:
    """Delete an owned key by id (SAPI-05/D-12).

    Relists the session user's keys and matches by id. If the id is not in the
    list (foreign key OR nonexistent), returns 403 with no existence leak (D-12).
    This is a deliberate divergence from auth.py:delete_token's 404.
    """
    settings: Settings = request.app.state.settings
    assert_same_origin(request, settings)

    email = user["email"]

    try:
        user_keys = await list_session_keys(email, settings)
    except httpx.HTTPStatusError as exc:
        logger.error("session_delete_key: relist failed for %s: %s", email, exc)
        raise HTTPException(status_code=502, detail="LiteLLM key listing failed")
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="LiteLLM backend unreachable")

    # Find the key for this id — 403 for any id not in the user's list (D-12)
    target = next((k for k in user_keys if k.get("id") == key_id), None)
    if target is None:
        # D-12: 403 regardless of whether the key exists elsewhere or nowhere
        raise HTTPException(status_code=403, detail="Not authorized")
    if target.get("is_default"):
        # The default key is undeletable until another key is promoted.
        raise HTTPException(
            status_code=409,
            detail="Cannot delete the default key. Make another key default first.",
        )
    # /key/list returns the hashed "token" (not the sk- plaintext); /key/delete accepts it.
    target_token = target.get("token")

    try:
        await delete_litellm_key(target_token, settings)
        logger.info("session_delete_key: user %s deleted key %s", email, key_id)
    except httpx.HTTPStatusError as exc:
        logger.error("session_delete_key: delete failed for key %s: %s", key_id, exc)
        raise HTTPException(status_code=502, detail="Failed to delete key")
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="LiteLLM backend unreachable")

    return JSONResponse({"status": "deleted", "id": key_id})


@router.post("/keys/{key_id}/default", response_model=None)
async def session_make_default(
    request: Request,
    key_id: str,
    user: dict = Depends(require_session_user),
) -> JSONResponse:
    """Promote an owned key to be the user's default (explicit-only).

    Sets is_default=True on the target and clears it on any other key that
    currently has it. 403 for a foreign/unknown id (no existence leak, D-12).
    The default is metadata-backed; session_create_key auto-assigns a newly
    created key ONLY when no default currently exists (presence check, not
    positional) — reassigning between existing keys is explicit (here).
    """
    settings: Settings = request.app.state.settings
    assert_same_origin(request, settings)
    email = user["email"]

    try:
        user_keys = await list_session_keys(email, settings)
    except httpx.HTTPStatusError as exc:
        logger.error("session_make_default: relist failed for %s: %s", email, exc)
        raise HTTPException(status_code=502, detail="LiteLLM key listing failed")
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="LiteLLM backend unreachable")

    target = next((k for k in user_keys if k.get("id") == key_id), None)
    if target is None:
        # D-12: 403 regardless of whether the key exists elsewhere or nowhere
        raise HTTPException(status_code=403, detail="Not authorized")

    try:
        # Demote any OTHER current default FIRST, then promote the target LAST.
        # Order matters (#5): if a demote fails mid-loop we 502 with the target
        # not yet promoted (≤1 default remains), never the two-default wedge that
        # would 409-block deletion of both keys.
        for k in user_keys:
            if k.get("id") != key_id and k.get("is_default"):
                await set_litellm_key_default(
                    k["token"],
                    settings,
                    is_default=False,
                    existing_metadata=k.get("metadata") or {},
                )
        await set_litellm_key_default(
            target["token"],
            settings,
            is_default=True,
            existing_metadata=target.get("metadata") or {},
        )
    except httpx.HTTPStatusError as exc:
        logger.error("session_make_default: update failed for %s: %s", key_id, exc)
        raise HTTPException(status_code=502, detail="Failed to set default key")
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="LiteLLM backend unreachable")

    logger.info("session_make_default: user %s set default key %s", email, key_id)
    return JSONResponse({"status": "default", "id": key_id})


@router.post("/keys/{key_id}/block", response_model=None)
async def session_block_key(
    request: Request,
    key_id: str,
    user: dict = Depends(require_session_user),
) -> JSONResponse:
    """Disable (block) or re-enable (unblock) an owned key — reversible, not a delete.

    Body: {"blocked": true|false}. 403 for a foreign/unknown id (no existence leak,
    D-12). Any key may be blocked, including the default — Chat/Models/MCPs stay
    gated on it, so disabling the default key disables those until it is re-enabled
    (the caller chose this over a 409 guard).
    """
    settings: Settings = request.app.state.settings
    assert_same_origin(request, settings)
    email = user["email"]

    try:
        body = BlockKeyBody.model_validate_json(await request.body())
    except ValidationError:
        raise HTTPException(status_code=422, detail="invalid request body")

    try:
        user_keys = await list_session_keys(email, settings)
    except httpx.HTTPStatusError as exc:
        logger.error("session_block_key: relist failed for %s: %s", email, exc)
        raise HTTPException(status_code=502, detail="LiteLLM key listing failed")
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="LiteLLM backend unreachable")

    target = next((k for k in user_keys if k.get("id") == key_id), None)
    if target is None:
        # D-12: 403 regardless of whether the key exists elsewhere or nowhere
        raise HTTPException(status_code=403, detail="Not authorized")

    try:
        await block_litellm_key(target["token"], settings, blocked=body.blocked)
    except httpx.HTTPStatusError as exc:
        logger.error("session_block_key: update failed for %s: %s", key_id, exc)
        raise HTTPException(status_code=502, detail="Failed to update key")
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="LiteLLM backend unreachable")

    logger.info("session_block_key: user %s set blocked=%s on key %s", email, body.blocked, key_id)
    return JSONResponse({"status": "blocked" if body.blocked else "active", "id": key_id})


def _parse_stats_range(start_date: str | None, end_date: str | None) -> tuple[date, date]:
    """Parse + bound the /stats date window (D-04). Raises HTTPException(422) on error.

    YYYY-MM-DD via date.fromisoformat (malformed -> 422). Defaults to a 30-day
    window ending today (UTC). Rejects start > end and any span over the max cap.
    All "today"/boundary math is UTC for determinism (RESEARCH §4 / RQ-C).
    """
    today = datetime.now(timezone.utc).date()
    try:
        end = date.fromisoformat(end_date) if end_date else today
        start = (
            date.fromisoformat(start_date)
            if start_date
            else end - timedelta(days=_DEFAULT_RANGE_DAYS - 1)
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="start_date/end_date must be YYYY-MM-DD")

    if start > end:
        raise HTTPException(status_code=422, detail="start_date must not be after end_date")

    span = (end - start).days + 1
    if span > _MAX_RANGE_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"date range too large (max {_MAX_RANGE_DAYS} days, got {span})",
        )

    return start, end


@router.get("/stats", response_model=None)
async def session_stats(
    request: Request,
    user: dict = Depends(require_session_user),
    start_date: str | None = None,
    end_date: str | None = None,
) -> JSONResponse:
    """Return the session user's aggregated usage/spend for a bounded window (STATS-01).

    Read-only GET (no assert_same_origin, D-13). The email is taken ONLY from the
    verified session cookie (require_session_user) — there is NO client-supplied
    user/email param, so a caller can never request another user's data.

    Fetches the current + prior equal-length windows concurrently (asyncio.gather,
    D-05 period-over-period deltas) plus the budget cap, folds them via app/stats.py
    into the page-ready {range, totals, series, models, keys, budget, capabilities}
    contract, and returns JSONResponse (response_model=None preserves D-08 null-vs-0).

    Degradation (D-06/D-09): only a CURRENT-window fetch failure 502s the request
    (that figure is indispensable). A PRIOR-window failure degrades deltas
    (capabilities.deltas=false, prior=None); a BUDGET failure degrades the budget
    block (mirrors /me); an unavailable last_used degrades to null + the
    per_model_last_used flag. A secondary failure never 502s the request.
    """
    settings: Settings = request.app.state.settings
    email = user["email"]

    start, end = _parse_stats_range(start_date, end_date)
    span = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)

    # Fetch all figures concurrently; degrade each independently (D-06).
    cur_res, prev_res, budget_res, last_used_res, keys_res, member_res = await asyncio.gather(
        user_daily_activity(email, settings, start.isoformat(), end.isoformat()),
        user_daily_activity(email, settings, prev_start.isoformat(), prev_end.isoformat()),
        get_litellm_user(email, settings),
        spend_logs_last_used(email, settings, start.isoformat(), end.isoformat()),
        list_session_keys(email, settings),
        get_team_member_budget(email, settings),
        return_exceptions=True,
    )

    capabilities = dict(_CAPABILITY_DEFAULTS)

    # CURRENT window is indispensable — a failure here is the one 502 (RESEARCH §6).
    if isinstance(cur_res, BaseException):
        logger.error("session_stats: current-window fetch failed for %s: %s", email, cur_res)
        if isinstance(cur_res, (httpx.HTTPStatusError, httpx.RequestError)):
            raise HTTPException(status_code=502, detail="Usage data unavailable")
        raise cur_res
    cur_agg = aggregate_window(cur_res)

    # PRIOR window failure → degrade deltas, do NOT 502 (RESEARCH §6 landmine 7).
    if isinstance(prev_res, BaseException):
        logger.warning("session_stats: prior-window fetch failed for %s: %s", email, prev_res)
        prev_agg: dict[str, Any] = {}
        capabilities["deltas"] = False
    else:
        prev_agg = aggregate_window(prev_res)

    # BUDGET → prefer the ENFORCED per-member cap (#1/RQ-1); degrade to user-level,
    # never 502 (mirrors session_me). Each read degrades independently.
    user_obj = {} if isinstance(budget_res, BaseException) else budget_res
    member = None if isinstance(member_res, BaseException) else member_res
    if isinstance(budget_res, BaseException):
        logger.warning("session_stats: budget fetch failed for %s: %s", email, budget_res)
    if isinstance(member_res, BaseException):
        logger.warning("session_stats: member-budget fetch failed for %s: %s", email, member_res)
    budget = _budget_block(user_obj, member)

    # LAST-USED failure → degrade to {} (null per model + flag flips in build_stats_contract).
    last_used: dict[str, str] = {}
    if isinstance(last_used_res, BaseException):
        logger.warning("session_stats: last-used fetch failed for %s: %s", email, last_used_res)
    elif isinstance(last_used_res, dict):
        last_used = last_used_res

    # KEY-LIST failure → skip friendly-name resolution; per-key rows keep the opaque
    # lk- alias (prior behaviour), never 502. The key list also carries the server-
    # side `token` hash, so it MUST stay server-side (resolve before serializing).
    key_list: list[dict[str, Any]] = []
    if isinstance(keys_res, BaseException):
        logger.warning("session_stats: key-list fetch failed for %s: %s", email, keys_res)
    elif isinstance(keys_res, list):
        key_list = keys_res

    range_meta = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": span,
        "compare": {"start": prev_start.isoformat(), "end": prev_end.isoformat()},
    }

    contract = build_stats_contract(cur_agg, prev_agg, budget, last_used, capabilities, range_meta)
    # Join the spend-log per-key rows (opaque lk- alias) to the user's key list so
    # the TOP API KEYS panel shows the FRIENDLY name and the UI dedups the idle-key
    # padding row (the active key was rendering twice: once as lk-… with all the
    # usage, once as the friendly name with 0). D-03: the server shapes this.
    contract["keys"] = resolve_key_display(contract["keys"], key_list)
    return JSONResponse(contract)


@router.get("/models", response_model=None)
async def session_models(
    request: Request,
    user: dict = Depends(require_session_user),
) -> JSONResponse:
    """Return the public model-group catalog for the session user (read-only).

    Server-side master-key call to LiteLLM /model_group/info — the safe public
    view (no upstream model / api_base / api_key). Scoped to the session user via
    an x-user-id header (resolved by the gateway's custom auth); the value is the
    authenticated email, NEVER client input. Read-only GET (no assert_same_origin,
    mirrors /stats). A backend failure 502s (the SPA renders its error+retry
    branch); an empty catalog is a valid 200 with models: [].
    """
    settings: Settings = request.app.state.settings
    try:
        models = await list_litellm_models(settings, user_id=user["email"])
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        logger.error("session_models: catalog fetch failed: %s", exc)
        raise HTTPException(status_code=502, detail="Model catalog unavailable")
    return JSONResponse({"models": models})


@router.get("/mcp", response_model=None)
async def session_mcp(
    request: Request,
    user: dict = Depends(require_session_user),
) -> JSONResponse:
    """Return the configured MCP servers for the session user (read-only).

    Server-side master-key call to LiteLLM /v1/mcp/server, projected to a PUBLIC
    subset (no credentials — see _project_mcp_server). Scoped to the session user
    via an x-user-id header (resolved by the gateway's custom auth); the value is
    the authenticated email, NEVER client input. Read-only GET.

    A 404 means the deployment's LiteLLM has no MCP gateway -> a calm
    {servers: [], available: false} 200 (the page shows a "not enabled" state).
    A 5xx / unreachable backend -> 502.
    """
    settings: Settings = request.app.state.settings
    try:
        servers = await list_litellm_mcp_servers(settings, user_id=user["email"])
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            logger.info("session_mcp: MCP gateway unavailable (404), degrading")
            return JSONResponse({"servers": [], "available": False})
        logger.error("session_mcp: server list failed: %s", exc)
        raise HTTPException(status_code=502, detail="MCP catalog unavailable")
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="LiteLLM backend unreachable")
    return JSONResponse({"servers": servers, "available": True})


@router.get("/a2a", response_model=None)
async def session_a2a(
    request: Request,
    user: dict = Depends(require_session_user),
) -> JSONResponse:
    """Return the configured A2A agents for the session user (read-only).

    Server-side master-key call to LiteLLM /v1/agents, projected to a PUBLIC subset
    (no headers/params — see _project_a2a_agent). Scoped to the session user via an
    x-user-id header (resolved by the gateway's custom auth, the same swap as MCP);
    the value is the authenticated email, NEVER client input. Read-only GET.

    A 404 means the deployment's LiteLLM has no A2A gateway -> a calm
    {agents: [], available: false} 200 (the page shows a "not enabled" state).
    A 5xx / unreachable backend -> 502.
    """
    settings: Settings = request.app.state.settings
    try:
        agents = await list_litellm_a2a_agents(settings, user_id=user["email"])
    except httpx.HTTPStatusError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            logger.info("session_a2a: A2A gateway unavailable (404), degrading")
            return JSONResponse({"agents": [], "available": False})
        logger.error("session_a2a: agent list failed: %s", exc)
        raise HTTPException(status_code=502, detail="A2A catalog unavailable")
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="LiteLLM backend unreachable")
    return JSONResponse({"agents": agents, "available": True})
