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
    delete_litellm_key,
    generate_litellm_key,
    get_litellm_user,
    list_session_keys,
    spend_logs_last_used,
    user_daily_activity,
)
from app.stats import aggregate_window, build_stats_contract

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


# ---------------------------------------------------------------------------
# Helper: derive spend.source from LiteLLM user data (RESEARCH RQ-1 / D-09a)
# ---------------------------------------------------------------------------

_SPEND_SOURCE_UNKNOWN = "unknown"


def _derive_spend(user: dict[str, Any]) -> dict[str, Any]:
    """Derive {current, source} from the available LiteLLM user budget fields.

    RQ-1: user-level max_budget does NOT enforce for team-scoped keys (it only
    reports). The per-user-within-team cap is max_budget_in_team. We derive source
    from which budget field is populated, reading defensively from the user object.

    Priority (most specific to least specific):
      1. team_member_spend / max_budget_in_team → source="team_member"
      2. team_spend / team_max_budget → source="team"
      3. spend / max_budget → source="user"
      4. nothing → source="unknown"
    """
    # /key/list?return_full_object=true rows carry these bonus fields (RQ-2)
    team_member_spend = user.get("team_member_spend")
    max_budget_in_team = user.get("max_budget_in_team")
    team_spend = user.get("team_spend")
    team_max_budget = user.get("team_max_budget")
    user_spend = user.get("spend", 0.0)
    user_budget = user.get("max_budget")

    if team_member_spend is not None or max_budget_in_team is not None:
        return {"current": float(team_member_spend or 0), "source": "team_member"}
    if team_spend is not None or team_max_budget is not None:
        return {"current": float(team_spend or 0), "source": "team"}
    # `spend` defaults to 0.0 in _normalize_user even when absent, so it is NOT a
    # reliable "user has budget data" signal on its own. Gate the user branch on a
    # configured budget OR a genuinely non-zero spend; otherwise report "unknown"
    # so "no budget configured" users are not mislabeled as source="user" (WR-01).
    if user_budget is not None or user_spend:
        return {"current": float(user_spend or 0), "source": "user"}
    return {"current": 0.0, "source": _SPEND_SOURCE_UNKNOWN}


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
    team_id = f"team-{settings.oauth_client_id}"

    limits: dict | None = None
    spend: dict = {"current": 0, "source": _SPEND_SOURCE_UNKNOWN}

    try:
        litellm_user = await get_litellm_user(email, settings)
        limits = _build_limits(litellm_user)
        spend = _derive_spend(litellm_user)
    except LiteLLMUserNotFound:
        # D-09 graceful degrade — user not yet in LiteLLM; limits/spend degraded
        logger.info("session_me: user %s not found in LiteLLM, degrading", email)
    except (httpx.HTTPStatusError, httpx.RequestError) as exc:
        # D-09 graceful degrade — transient backend failure; do not 502
        logger.error("session_me: enrichment failed for %s: %s", email, exc)

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
    # D-17: never expose the raw sk- ("key") nor the server-side delete hash ("token") to the browser.
    safe_keys = [{k: v for k, v in kd.items() if k not in ("key", "token")} for kd in keys]
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
        raise HTTPException(status_code=502, detail="Key generation failed")
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="LiteLLM backend unreachable")

    # Return the sk- ONCE — it is never stored and cannot be recovered (SAPI-04)
    return JSONResponse(
        {
            "key": key_data["key"],
            "id": key_data["id"],
            "team_id": key_data.get("team_id"),
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

    # Find the token for this id — 403 for any id not in the user's list (D-12)
    target_token: str | None = None
    for k in user_keys:
        if k.get("id") == key_id:
            # /key/list returns the hashed "token" (not the sk- plaintext); /key/delete accepts it.
            target_token = k.get("token")
            break

    if target_token is None:
        # D-12: 403 regardless of whether the key exists elsewhere or nowhere
        raise HTTPException(status_code=403, detail="Not authorized")

    try:
        await delete_litellm_key(target_token, settings)
        logger.info("session_delete_key: user %s deleted key %s", email, key_id)
    except httpx.HTTPStatusError as exc:
        logger.error("session_delete_key: delete failed for key %s: %s", key_id, exc)
        raise HTTPException(status_code=502, detail="Failed to delete key")
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="LiteLLM backend unreachable")

    return JSONResponse({"status": "deleted", "id": key_id})


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
    cur_res, prev_res, budget_res, last_used_res = await asyncio.gather(
        user_daily_activity(email, settings, start.isoformat(), end.isoformat()),
        user_daily_activity(email, settings, prev_start.isoformat(), prev_end.isoformat()),
        get_litellm_user(email, settings),
        spend_logs_last_used(email, settings, start.isoformat(), end.isoformat()),
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

    # BUDGET failure → degrade the budget block (mirrors session_me), do NOT 502.
    budget: dict[str, Any] = {"current": 0, "max_budget": None, "source": _SPEND_SOURCE_UNKNOWN}
    if isinstance(budget_res, BaseException):
        logger.warning("session_stats: budget fetch failed for %s: %s", email, budget_res)
    else:
        spend = _derive_spend(budget_res)
        budget = {
            "current": spend["current"],
            "max_budget": budget_res.get("max_budget"),
            "source": spend["source"],
        }

    # LAST-USED failure → degrade to {} (null per model + flag flips in build_stats_contract).
    last_used: dict[str, str] = {}
    if isinstance(last_used_res, BaseException):
        logger.warning("session_stats: last-used fetch failed for %s: %s", email, last_used_res)
    elif isinstance(last_used_res, dict):
        last_used = last_used_res

    range_meta = {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "days": span,
        "compare": {"start": prev_start.isoformat(), "end": prev_end.isoformat()},
    }

    contract = build_stats_contract(cur_agg, prev_agg, budget, last_used, capabilities, range_meta)
    return JSONResponse(contract)
