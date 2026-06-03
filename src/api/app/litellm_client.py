# SPDX-License-Identifier: Apache-2.0
"""Async LiteLLM admin API client."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


def _extract_litellm_error(resp: httpx.Response) -> str:
    """Try to extract error.message from LiteLLM JSON response."""
    try:
        data = resp.json()
        if isinstance(data, dict):
            # Try error.message (standard LiteLLM/OpenAI)
            err = data.get("error")
            if isinstance(err, dict):
                msg = err.get("message")
                if msg:
                    return str(msg)
            # Try top-level detail or message
            msg = data.get("detail") or data.get("message")
            if msg:
                return str(msg)
    except Exception:
        pass
    return resp.text


def _parse_metadata(raw_metadata: Any) -> dict:
    """Safely parse LiteLLM metadata, handling stringified JSON."""
    if isinstance(raw_metadata, str):
        try:
            return json.loads(raw_metadata) or {}
        except Exception:
            logger.warning("Could not parse metadata string: %r", raw_metadata)
            return {}
    if isinstance(raw_metadata, dict):
        return raw_metadata
    return {}


def _get_key_id(
    data: dict,
    fallback_alias: str | None = None,
    metadata: dict | None = None,
) -> str | None:
    """
    Extract the hash/ID.
    PRIORITY: Generate hash from key_alias (to ensure consistency across /me and /list).
    Fallback: Use existing ID fields from LiteLLM.
    """
    # 1. Preferred: Generate stable hash from key_alias
    alias = data.get("key_alias") or fallback_alias
    if not alias and metadata:
        alias = metadata.get("key_alias")

    if alias:
        return hashlib.sha256(alias.encode()).hexdigest()

    # 2. Fallback: Check explicit ID fields
    for field in ["key_id", "token_id"]:
        val = data.get(field)
        if val:
            return val

    # 3. Fallback: Check if key/token holds a hash (not sk-...)
    for field in ["key", "token"]:
        val = data.get(field)
        if isinstance(val, str) and not val.startswith("sk-"):
            return val

    return None


def _get_token(data: dict) -> str | None:
    """Extract the actual sk-... token. Prioritize values starting with sk-."""
    for field in ["token", "key"]:
        val = data.get(field)
        if isinstance(val, str) and val.startswith("sk-"):
            return val
    return data.get("token") or data.get("key")


def _load_factory_config(path: str | None) -> dict:
    """Load team/user param overrides from the mounted ConfigMap JSON file."""
    if not path:
        return {}
    try:
        return json.loads(Path(path).read_text())
    except Exception as exc:
        logger.warning("Could not load factory config from %s: %s", path, exc)
        return {}


async def _ensure_access_group(client: httpx.AsyncClient, headers: dict, name: str) -> str | None:
    """Create the named access group if it doesn't exist; return its ID (or None on failure)."""
    resp = await client.post("/v1/access_group", headers=headers, json={"access_group_name": name})
    if resp.is_success:
        return resp.json().get("access_group_id")
    already_exists = resp.status_code == 409 or (
        resp.status_code == 400 and "already exists" in resp.text
    )
    if already_exists:
        list_resp = await client.get("/v1/access_group", headers=headers)
        if list_resp.is_success:
            for group in list_resp.json():
                if group.get("access_group_name") == name:
                    return group.get("access_group_id")
    logger.warning("Could not ensure access group %r: %s", name, resp.text)
    return None


def _admin_headers(settings: Settings) -> dict:
    """Build LiteLLM admin authorization headers."""
    return {
        "Authorization": f"Bearer {settings.litellm_master_key}",
        "Content-Type": "application/json",
    }


async def ensure_team_member_budget(
    email: str,
    team_id: str,
    max_budget_in_team: float,
    settings: Settings,
) -> None:
    """Idempotently set the per-member budget cap for a team member.

    Adopts /team/member_add per the D-14 spike result (USER-V2-01 re-scoped from a
    Phase-2 greenfield exclusion): KEY_A (user-level max_budget) did NOT enforce for
    team-scoped keys on LiteLLM v1.85.1; KEY_B (max_budget_in_team) enforced.

    Flow (idempotent — running twice yields the same end state):
    1. POST /team/member_add with nested member body + max_budget_in_team.
       Treats 400/409 with "already" in the body as a no-op (member exists).
    2. POST /team/member_update with top-level user_id + max_budget_in_team
       to set/update the per-member cap (always called, even after member_add
       succeeds, so the cap is applied regardless of whether the add was new
       or a no-op).

    H3: caller must guard — only call when max_budget_in_team is not None/0.
    """
    headers = _admin_headers(settings)
    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=30.0) as client:
        # Step 1: Add member (nested body per TeamMemberAddRequest — v1.85.1 openapi.json).
        add_resp = await client.post(
            "/team/member_add",
            headers=headers,
            json={
                "team_id": team_id,
                "member": {"user_id": email, "role": "user"},  # nested, NOT top-level user_id
                "max_budget_in_team": max_budget_in_team,
            },
        )
        already_member = add_resp.status_code in (400, 409) and "already" in add_resp.text.lower()
        if not add_resp.is_success and not already_member:
            msg = _extract_litellm_error(add_resp)
            raise httpx.HTTPStatusError(
                f"LiteLLM /team/member_add failed: {msg}",
                request=add_resp.request,
                response=add_resp,
            )

        # Step 2: Update the per-member cap (top-level body per TeamMemberUpdateRequest).
        # Always called: sets/refreshes the cap whether the member was just added or already existed.
        update_resp = await client.post(
            "/team/member_update",
            headers=headers,
            json={
                "team_id": team_id,
                "user_id": email,  # top-level, NOT nested member object
                "max_budget_in_team": max_budget_in_team,
            },
        )
        if not update_resp.is_success:
            msg = _extract_litellm_error(update_resp)
            raise httpx.HTTPStatusError(
                f"LiteLLM /team/member_update failed: {msg}",
                request=update_resp.request,
                response=update_resp,
            )


async def ensure_team_and_user(
    email: str,
    settings: Settings,
    name: str | None = None,
) -> str:
    """Idempotently ensure the shared team, access group, and LiteLLM user exist.

    Performs Steps A (team), B (access group), A2 (user), and A3 (member budget)
    in that order. This is a shared prerequisite for both key minting
    (generate_litellm_key) and the eager /ui login path (D-13). Returns the team_id.

    D-16 lazy backfill: if the user already existed (409/400), fetches the
    current user and patches only null/missing factory budget fields via
    /user/update. Never overwrites a manually-set value; never sends null (H3).

    D-14 (USER-V2-01 re-scoped): Step A3 calls ensure_team_member_budget using
    the factory user max_budget as max_budget_in_team. The RQ-1 spike proved that
    user-level max_budget does NOT enforce for team-scoped keys on LiteLLM v1.85.1;
    max_budget_in_team via /team/member_add does enforce. H3: only called when a
    budget value exists (never send null/None).
    """
    team_id = f"team-{settings.oauth_client_id}"
    headers = _admin_headers(settings)

    factory = _load_factory_config(settings.factory_config_path)
    team_extra = {k: v for k, v in factory.get("team", {}).items() if k != "metadata"}
    team_meta_extra = factory.get("team", {}).get("metadata", {})

    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=30.0) as client:
        # Step A: Create shared team — 409 means it already exists, treat as success.
        # Lowercase the body before matching so "Team Already Exists" (WR-04) is handled.
        team_resp = await client.post(
            "/team/new",
            headers=headers,
            json={
                **team_extra,  # configmap overrides (D-20: team:{} so no team budget)
                "team_id": team_id,  # always wins — not overridable
                "team_alias": settings.oauth_client_id,
                "metadata": {"source": "token-factory", **team_meta_extra},
            },
        )
        team_exists = team_resp.status_code == 409 or (
            team_resp.status_code == 400 and "already exists" in team_resp.text.lower()
        )
        if team_resp.status_code != 200 and not team_exists:
            msg = _extract_litellm_error(team_resp)
            raise httpx.HTTPStatusError(
                f"LiteLLM /team/new failed: {msg}",
                request=team_resp.request,
                response=team_resp,
            )

        # Step B: Ensure shared access group exists (same name as team/client_id).
        await _ensure_access_group(client, headers, settings.oauth_client_id)

        # Step A2: Ensure user exists with D-15 factory user budget block.
        user_result = await ensure_litellm_user(
            email, settings, name=name, team_id=team_id, apply_budget=True
        )

        # D-16 lazy backfill: if user already existed, patch only null/missing budget fields.
        if user_result.get("existed"):
            try:
                existing_user = await get_litellm_user(email, settings)
                factory_user = {
                    k: v
                    for k, v in factory.get("user", {}).items()
                    if k != "metadata" and v is not None
                }
                # Find fields that are None or missing on the existing user
                missing = {
                    k: v
                    for k, v in factory_user.items()
                    if existing_user.get(k) is None
                }
                if missing:
                    resp = await client.post(
                        "/user/update",
                        headers=headers,
                        json={"user_id": email, **missing},
                    )
                    if not resp.is_success:
                        msg = _extract_litellm_error(resp)
                        raise httpx.HTTPStatusError(
                            f"LiteLLM /user/update (backfill) failed: {msg}",
                            request=resp.request,
                            response=resp,
                        )
                    logger.info(
                        "D-16 lazy backfill: updated %s with fields %s",
                        email,
                        list(missing.keys()),
                    )
            except LiteLLMUserNotFound:
                logger.warning("D-16 backfill: user %s not found after existed=True; skipping", email)
            except httpx.HTTPStatusError as exc:
                logger.error("D-16 backfill failed for %s: %s", email, exc)
                raise

    # Step A3 (D-14 USER-V2-01 re-scope): set per-member budget cap via /team/member_add.
    # Adopts max_budget_in_team because the RQ-1 spike proved user-level max_budget does
    # NOT enforce for team-scoped keys on LiteLLM v1.85.1 (KEY_A=200 beyond cap; KEY_B=429).
    # H3: only call when the factory provides a non-None, non-zero max_budget value.
    factory_user_budget = factory.get("user", {}).get("max_budget")
    if factory_user_budget is not None and factory_user_budget > 0:
        await ensure_team_member_budget(email, team_id, factory_user_budget, settings)

    return team_id


async def generate_litellm_key(
    email: str,
    settings: Settings,
    name: str | None = None,
    duration: str | None = None,
    alias: str | None = None,
) -> dict:
    """
    Ensure the shared org team/user exist (idempotent) and generate a virtual key.

    Team is shared across all users — named after OAUTH_CLIENT_ID (e.g. "platform").

    Args:
        email: User's email address (used as user_id).
        settings: Application settings.
        name: Optional display name for the user/key.
        duration: Optional LiteLLM duration string (e.g. "90d"). When not None,
            the /key/generate payload carries this value. When None (default),
            no expiry is set and the "duration" key is omitted entirely (D-10).
        alias: Optional human-readable key_alias (D-10). When None (default),
            a readable, second-unique alias "key-YYYY-MM-DD-HHMMSS" is generated.
            Uniqueness matters because the returned id is sha256(key_alias) — a
            non-unique alias would collide ids and break DELETE/list ownership.

    Returns:
        {"key": "sk-...", "team_id": "..."}
    """
    headers = _admin_headers(settings)
    factory = _load_factory_config(settings.factory_config_path)
    user_meta_extra = factory.get("user", {}).get("metadata", {})

    # Steps A, B, A2: ensure team → access group → user (shared prerequisite, D-13).
    team_id = await ensure_team_and_user(email, settings, name=name)

    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=30.0) as client:
        # Re-resolve access_group_id for the key payload (needed for access_group_ids field).
        access_group_id = await _ensure_access_group(client, headers, settings.oauth_client_id)

        # Step C: Generate virtual key scoped to the shared team, with full model access.
        # D-15: keys carry NO budget fields (budget is at the user level).
        # D-10: caller-supplied alias wins; default is readable AND second-unique
        # so sha256(key_alias) ids stay distinct (no DELETE/list collision).
        key_alias = alias or f"key-{datetime.now(timezone.utc).strftime('%Y-%m-%d-%H%M%S')}"
        key_payload: dict = {
            "models": ["all-team-models"],  # default — configmap can override
            "allowed_routes": ["llm_api_routes"],  # default — configmap can override
            "team_id": team_id,  # always wins — not overridable
            "user_id": email,  # scope key to LiteLLM user (USER-02)
            "access_group_ids": [access_group_id] if access_group_id else [],
            "key_alias": key_alias,
            "metadata": {
                "email": email,
                "name": name or email,
                "source": "token-factory",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "key_alias": key_alias,
                **user_meta_extra,
            },
        }
        # D-10: include duration only when not None — never send "duration": null.
        if duration is not None:
            key_payload["duration"] = duration

        key_resp = await client.post("/key/generate", headers=headers, json=key_payload)

        if not key_resp.is_success:
            msg = _extract_litellm_error(key_resp)
            raise httpx.HTTPStatusError(
                f"LiteLLM /key/generate failed: {msg}",
                request=key_resp.request,
                response=key_resp,
            )

    key_data = key_resp.json()
    metadata = _parse_metadata(key_data.get("metadata"))
    token = _get_token(key_data)
    return {
        "key": token,
        "id": _get_key_id(key_data, key_alias, metadata=metadata),
        "team_id": team_id,
    }


async def _list_session_keys_fallback(email: str, settings: Settings) -> list[dict]:
    """Fallback: hydrate keys via list_litellm_keys + get_key_info when /key/list returns strings."""
    raw_keys = await list_litellm_keys(email, settings)
    # list_litellm_keys already handles string-item hydration + email filtering.
    # Project each key to the SAPI-03 shape.
    out = []
    for k in raw_keys:
        md = _parse_metadata(k.get("metadata") if isinstance(k, dict) else {})
        out.append(
            {
                "id": _get_key_id(k, metadata=md) if isinstance(k, dict) else None,
                "token": k.get("token") if isinstance(k, dict) else None,  # delete id; stripped before browser
                "key_alias": k.get("key_alias") if isinstance(k, dict) else None,
                "spend": k.get("spend", 0.0) if isinstance(k, dict) else 0.0,
                "budget": None,  # D-17: inherited from user/team
                "tpm_limit": k.get("tpm_limit") if isinstance(k, dict) else None,
                "rpm_limit": k.get("rpm_limit") if isinstance(k, dict) else None,
                "models": k.get("models") if isinstance(k, dict) else None,
                "created_at": (md.get("created_at") or (k.get("created_at") if isinstance(k, dict) else None)),
                "expires": k.get("expires") if isinstance(k, dict) else None,
            }
        )
    out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return out


async def list_session_keys(email: str, settings: Settings) -> list[dict]:
    """List all virtual keys for a user as SAPI-03 metadata objects.

    Uses the one-call /key/list?return_full_object=true&size=100 path (RQ-2/D-08).
    Falls back to the list_litellm_keys + get_key_info hydration path when the
    proxy returns string items (i.e. return_full_object was ignored).

    Pitfall 3: uses 'size' (not 'page_size') on /key/list — they are different params.
    D-17: 'budget' is always None (inherited from user/team; reported by /me).
    """
    headers = _admin_headers(settings)
    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=10.0) as client:
        resp = await client.get(
            "/key/list",
            headers=headers,
            params={"user_id": email, "return_full_object": True, "size": 100},
        )

    if not resp.is_success:
        msg = _extract_litellm_error(resp)
        raise httpx.HTTPStatusError(
            f"LiteLLM /key/list failed ({resp.status_code}): {msg}",
            request=resp.request,
            response=resp,
        )

    rows = resp.json().get("keys", [])
    if not isinstance(rows, list):
        logger.warning("LiteLLM /key/list returned non-list 'keys': %r", rows)
        return []

    out = []
    for k in rows:
        # If the proxy returned a string, return_full_object was ignored → trigger fallback.
        if isinstance(k, str):
            return await _list_session_keys_fallback(email, settings)
        if not isinstance(k, dict):
            logger.warning(
                "LiteLLM /key/list returned unexpected type (not str/dict): %r type=%s",
                k,
                type(k),
            )
            continue
        md = _parse_metadata(k.get("metadata"))
        out.append(
            {
                "id": _get_key_id(k, metadata=md),
                "token": k.get("token"),  # LiteLLM key hash — server-side delete id; stripped before browser
                "key_alias": k.get("key_alias"),
                "spend": k.get("spend", 0.0),
                "budget": None,  # D-17: budget inherited from user/team; never per-key
                "tpm_limit": k.get("tpm_limit"),
                "rpm_limit": k.get("rpm_limit"),
                "models": k.get("models"),
                "created_at": md.get("created_at") or k.get("created_at"),
                "expires": k.get("expires"),
            }
        )

    out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return out


async def user_daily_activity(
    email: str,
    settings: Settings,
    start_date: str,
    end_date: str,
) -> dict:
    """Fetch the daily activity breakdown for a user from LiteLLM.

    Calls GET /user/daily/activity with params (H6: always params={}, never f-string).
    Returns the SpendAnalyticsPaginatedResponse shape:
        {results: [{date, metrics:{spend,total_tokens,...}, breakdown:{...}}],
         metadata: {total_spend, total_tokens, ..., has_more, page, total_pages}}

    Used by GET /api/session/usage (D-09b).

    Args:
        email: User identifier (user_id=email convention).
        settings: Application settings.
        start_date: ISO date string, e.g. "2026-05-01".
        end_date: ISO date string, e.g. "2026-05-31".
    """
    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=15.0) as client:
        resp = await client.get(
            "/user/daily/activity",
            headers=_admin_headers(settings),
            params={"user_id": email, "start_date": start_date, "end_date": end_date},
        )

    if not resp.is_success:
        msg = _extract_litellm_error(resp)
        raise httpx.HTTPStatusError(
            f"LiteLLM /user/daily/activity failed ({resp.status_code}): {msg}",
            request=resp.request,
            response=resp,
        )

    return resp.json()


async def list_litellm_keys(email: str, settings: Settings) -> list[dict]:
    """List all virtual keys for a specific user email."""
    headers = _admin_headers(settings)
    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=10.0) as client:
        # LiteLLM doesn't support filtering /key/list by metadata directly in all versions,
        # but we can filter by team_id and then client-side filter by email metadata.
        team_id = f"team-{settings.oauth_client_id}"
        resp = await client.get("/key/list", headers=headers, params={"team_id": team_id})

    if not resp.is_success:
        raise httpx.HTTPStatusError(
            f"LiteLLM /key/list failed ({resp.status_code}): {resp.text}",
            request=resp.request,
            response=resp,
        )

    all_keys = resp.json().get("keys", [])
    if not isinstance(all_keys, list):
        logger.warning("LiteLLM /key/list returned non-list 'keys': %r", all_keys)
        return []

    user_keys = []
    for k in all_keys:
        # If LiteLLM returns a string (token/hash), we must fetch details to filter by email
        if isinstance(k, str):
            try:
                # Hydrate the key details
                # We reuse get_key_info but need to be careful about recursion or overhead
                # get_key_info returns our standardized dict structure
                full_info = await get_key_info(k, settings)

                # IMPORTANT: If LiteLLM /key/info redacts the key, restore it from our source 'k'
                if not full_info.get("key"):
                    full_info["key"] = k

                # Check ownership
                if full_info.get("email") == email:
                    user_keys.append(full_info)
            except Exception as exc:
                # Do NOT silently drop keys: this listing feeds the ownership
                # check in delete_token, where a dropped key the user actually
                # owns surfaces as a spurious 404 (WR-06). Fail loudly instead
                # so callers see a real backend error, not an incomplete list.
                logger.error("Failed to hydrate key during ownership check: %s", exc)
                raise
            continue

        if not isinstance(k, dict):
            logger.warning(
                "LiteLLM /key/list returned UNKNOWN type (not str/dict): %r type=%s", k, type(k)
            )
            continue

        metadata = _parse_metadata(k.get("metadata"))

        if metadata.get("email") == email:
            token = _get_token(k)
            user_keys.append(
                {
                    "id": _get_key_id(k, metadata=metadata),
                    "key": token,
                    "key_alias": k.get("key_alias"),
                    "created_at": metadata.get("created_at"),
                    "expires": k.get("expires"),
                    "models": k.get("models"),
                }
            )

    # Sort by created_at descending if possible
    user_keys.sort(
        key=lambda x: (x.get("created_at") if isinstance(x, dict) else "") or "", reverse=True
    )
    return user_keys


async def delete_litellm_key(token: str, settings: Settings) -> None:
    """Delete a LiteLLM virtual key."""
    headers = _admin_headers(settings)
    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=10.0) as client:
        resp = await client.post("/key/delete", headers=headers, json={"keys": [token]})

    if not resp.is_success:
        msg = _extract_litellm_error(resp)
        raise httpx.HTTPStatusError(
            f"LiteLLM /key/list failed ({resp.status_code}): {msg}",
            request=resp.request,
            response=resp,
        )


async def get_key_info(api_key: str, settings: Settings) -> dict:
    """
    Look up a LiteLLM virtual key and return its metadata.

    Uses the master key to call GET /key/info?key=<api_key>.

    Returns:
        dict with keys: email, name, team_id, key_alias, models, created_at, expires

    Field default convention (IN-03): ``spend`` is zero-defaulted (``0.0`` when
    LiteLLM omits it) because "no recorded spend" is unambiguously zero and
    downstream consumers expect a number. The budget/limit fields
    (``max_budget``, ``budget_duration``, ``tpm_limit``, ``rpm_limit``) are left
    as ``None`` when absent, because there ``None`` means "no limit configured",
    which is semantically different from ``0`` (a zero limit). Consumers doing
    arithmetic across these (e.g. ``spend / max_budget``) must guard for ``None``
    on the budget side.

    Raises:
        httpx.HTTPStatusError: if key is invalid / not found (4xx) or server error (5xx)
    """
    headers = _admin_headers(settings)
    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=10.0) as client:
        resp = await client.get("/key/info", headers=headers, params={"key": api_key})

    if not resp.is_success:
        msg = _extract_litellm_error(resp)
        raise httpx.HTTPStatusError(
            f"LiteLLM /key/info failed ({resp.status_code}): {msg}",
            request=resp.request,
            response=resp,
        )

    data = resp.json()
    if not isinstance(data, dict):
        logger.error("LiteLLM /key/info returned non-dict: %r", data)
        raise ValueError(f"LiteLLM /key/info returned invalid data structure: {type(data)}")

    info = data.get("info", data)  # LiteLLM wraps in {"info": {...}}
    if not isinstance(info, dict):
        logger.error("LiteLLM /key/info 'info' field is not a dict: %r", info)
        raise ValueError(f"LiteLLM /key/info 'info' is {type(info)}")

    metadata = _parse_metadata(info.get("metadata"))

    return {
        "key": _get_token(info),  # The actual sk-... token
        "id": _get_key_id(info, metadata=metadata),
        "email": metadata.get("email"),
        "name": metadata.get("name"),
        "team_id": info.get("team_id"),
        "user_id": info.get("user_id"),
        "models": info.get("models"),
        "created_at": metadata.get("created_at"),
        "expires": info.get("expires"),
        "spend": info.get("spend", 0.0),
        "max_budget": info.get("max_budget"),
        "budget_duration": info.get("budget_duration"),
        "tpm_limit": info.get("tpm_limit"),
        "rpm_limit": info.get("rpm_limit"),
        "last_active": info.get("last_active"),
    }


# ── LiteLLM User lifecycle ──────────────────────────────────────────────────

# LiteLLM v1.83 returns this placeholder for unknown/ambiguous user lookups
# instead of a 404 (see hardening note H1).
LITELLM_PLACEHOLDER_USER_ID = "default_user_id"


class LiteLLMUserNotFound(Exception):
    """Raised when a LiteLLM user genuinely does not exist."""


def _normalize_teams(raw: Any) -> list[str] | None:
    """LiteLLM /user/info returns teams as [{team_id, team_alias}] objects (H2);
    /user/list may return plain strings. Project both to alias-preferred strings."""
    if raw is None:
        return None
    if not isinstance(raw, list):
        # Defend against LiteLLM versions that return 'teams' as a single dict,
        # a comma-joined string, or any other non-list shape (WR-03). Degrade
        # gracefully rather than raise TypeError on the whoami enrichment path.
        logger.warning("Unexpected 'teams' shape: %r", raw)
        return None
    out: list[str] = []
    for t in raw:
        if isinstance(t, str):
            out.append(t)
        elif isinstance(t, dict):
            out.append(t.get("team_alias") or t.get("team_id") or "")
    return [t for t in out if t]


def _normalize_user(info: dict, fallback_id: str | None = None) -> dict:
    """Project a LiteLLM user object into our stable shape.

    Field default convention (IN-03): mirrors get_key_info — ``spend`` is
    zero-defaulted (``0.0``) since "no recorded spend" is unambiguously zero,
    while ``max_budget``, ``budget_duration``, ``tpm_limit``, ``rpm_limit``, and
    ``max_parallel_requests`` stay ``None`` when absent because ``None`` means
    "no limit configured" (distinct from a ``0`` limit).
    """
    metadata = _parse_metadata(info.get("metadata"))
    return {
        "user_id": info.get("user_id") or fallback_id,
        "email": info.get("user_email") or metadata.get("email"),
        "name": info.get("user_alias") or metadata.get("name"),
        "role": info.get("user_role"),
        "spend": info.get("spend", 0.0),
        "max_budget": info.get("max_budget"),
        "budget_duration": info.get("budget_duration"),
        "tpm_limit": info.get("tpm_limit"),
        "rpm_limit": info.get("rpm_limit"),
        "max_parallel_requests": info.get("max_parallel_requests"),
        "models": info.get("models"),
        "teams": _normalize_teams(info.get("teams")),
        "created_at": info.get("created_at"),
    }


async def ensure_litellm_user(
    email: str,
    settings: Settings,
    name: str | None = None,
    team_id: str | None = None,
    apply_budget: bool = False,
) -> dict:
    """Idempotently create a LiteLLM internal user keyed by email (user_id=email).

    Mirrors the team-creation idempotency: 409, or 400 + "already exists",
    is treated as success. We never auto-create a key here — keys are minted
    separately by generate_litellm_key().

    D-15: budgets are now at the user level. When apply_budget=True, the factory
    user block (max_budget, budget_duration, tpm_limit, rpm_limit,
    max_parallel_requests) is merged into the /user/new payload.
    H3: only include fields when the factory provides a non-None value — never
    send max_budget: null which can overwrite LiteLLM defaults.
    """
    headers = _admin_headers(settings)
    payload: dict = {
        "user_id": email,
        "user_email": email,
        "user_alias": name or email,
        "user_role": "internal_user",
        "auto_create_key": False,
    }
    if team_id:
        payload["teams"] = [team_id]
    if apply_budget:
        factory = _load_factory_config(settings.factory_config_path)
        user_budget = {
            k: v
            for k, v in factory.get("user", {}).items()
            if k != "metadata" and v is not None
        }
        payload.update(user_budget)
    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=30.0) as client:
        resp = await client.post("/user/new", headers=headers, json=payload)
    exists = resp.status_code == 409 or (
        resp.status_code == 400 and "already exists" in resp.text.lower()
    )
    if not resp.is_success and not exists:
        msg = _extract_litellm_error(resp)
        raise httpx.HTTPStatusError(
            f"LiteLLM /user/new failed: {msg}", request=resp.request, response=resp
        )
    if exists:
        return {"user_id": email, "existed": True}
    return resp.json()


def _is_placeholder(info: dict) -> bool:
    """True if LiteLLM returned the v1.83 'unknown user' placeholder (H1)."""
    return info.get("user_id") == LITELLM_PLACEHOLDER_USER_ID or not (
        info.get("user_email") or info.get("user_id")
    )


async def get_litellm_user(email: str, settings: Settings) -> dict:
    """Fetch a LiteLLM user by user_id=email; normalized shape.

    Hardened for LiteLLM v1.83 (H1): /user/info can answer 200 + the
    'default_user_id' placeholder instead of 404. On placeholder we fall back
    to /user/list?user_email= and exact-match. Raises LiteLLMUserNotFound if
    the user truly does not exist.

    H6: email is always passed via httpx params={} — never f-string or string
    concatenation — so @ and + are encoded correctly.
    """
    headers = _admin_headers(settings)
    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=10.0) as client:
        resp = await client.get("/user/info", headers=headers, params={"user_id": email})
        if resp.status_code == 404:
            info: dict = {}
        elif not resp.is_success:
            msg = _extract_litellm_error(resp)
            raise httpx.HTTPStatusError(
                f"LiteLLM /user/info failed ({resp.status_code}): {msg}",
                request=resp.request,
                response=resp,
            )
        else:
            data = resp.json()
            # Unwrap user_info wrapper if present
            info = data.get("user_info", data) if isinstance(data, dict) else {}
            if not isinstance(info, dict):
                info = data if isinstance(data, dict) else {}

        # H1 fallback: placeholder/empty → authoritative lookup via /user/list
        if not info or _is_placeholder(info):
            list_resp = await client.get(
                "/user/list",
                headers=headers,
                params={"user_email": email, "page_size": 100},
            )
            if list_resp.is_success:
                payload = list_resp.json()
                users = payload.get("users", payload) if isinstance(payload, dict) else payload
                match = next(
                    (
                        u
                        for u in (users or [])
                        if isinstance(u, dict) and u.get("user_email") == email
                    ),
                    None,
                )
                if match is None:
                    raise LiteLLMUserNotFound(email)
                # /user/list is authoritative for user_id (H1)
                return _normalize_user(match, fallback_id=email)
            # A failed fallback lookup is a BACKEND failure, not a genuine
            # no-match. Raising LiteLLMUserNotFound here would misreport a
            # transient 5xx as "User not found" (404) — dangerous on the admin
            # DELETE path, which would report a real user as absent (WR-05).
            # Surface it as an HTTPStatusError so callers map it to 502.
            msg = _extract_litellm_error(list_resp)
            raise httpx.HTTPStatusError(
                f"LiteLLM /user/list fallback failed ({list_resp.status_code}): {msg}",
                request=list_resp.request,
                response=list_resp,
            )

    return _normalize_user(info, fallback_id=email)


async def list_litellm_users(
    settings: Settings,
    page: int = 1,
    page_size: int = 100,
    role: str | None = None,
    email: str | None = None,
) -> list[dict]:
    """List LiteLLM users (normalized), with bounded auto-pagination.

    D-10: loops pages until a short page returns OR max_pages cap (10) is hit.
    On cap, emits a warning — silent truncation is not acceptable for an admin
    listing that may be used for auditing.

    D-01: role is passed server-side as an exact-match enum filter; email is
    filtered client-side after normalization (server partial-match only).
    """
    headers = _admin_headers(settings)
    max_pages = 10
    current_page = page
    accumulated: list[dict] = []

    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=15.0) as client:
        while True:
            params: dict = {"page": current_page, "page_size": page_size}
            if role:
                params["role"] = role  # server-side exact-match enum filter (D-01)
            resp = await client.get(
                "/user/list",
                headers=headers,
                params=params,
            )
            if not resp.is_success:
                msg = _extract_litellm_error(resp)
                raise httpx.HTTPStatusError(
                    f"LiteLLM /user/list failed ({resp.status_code}): {msg}",
                    request=resp.request,
                    response=resp,
                )
            data = resp.json()
            page_users = data.get("users", data) if isinstance(data, dict) else data
            if not isinstance(page_users, list):
                logger.warning("LiteLLM /user/list returned non-list 'users': %r", page_users)
                break
            accumulated.extend(u for u in page_users if isinstance(u, dict))
            # Stop if this page was shorter than page_size (last page)
            if len(page_users) < page_size:
                break
            current_page += 1
            if current_page - page >= max_pages:
                logger.warning(
                    "list_litellm_users: reached max_pages cap (%d); "
                    "pagination truncated at ~%d users",
                    max_pages,
                    len(accumulated),
                )
                break

    result = [_normalize_user(u) for u in accumulated]
    if email:
        # D-01: server user_email is partial-match only; exact-match client-side.
        # Both user_id and email fields are checked because older LiteLLM rows
        # may use placeholder user_id values (D-01 Pitfall 3).
        result = [u for u in result if u.get("user_id") == email or u.get("email") == email]
    return result


async def delete_litellm_user(email: str, settings: Settings) -> None:
    """Delete a LiteLLM user (and, per LiteLLM, their keys) by user_id=email."""
    headers = _admin_headers(settings)
    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=10.0) as client:
        resp = await client.post("/user/delete", headers=headers, json={"user_ids": [email]})
    if not resp.is_success:
        msg = _extract_litellm_error(resp)
        raise httpx.HTTPStatusError(
            f"LiteLLM /user/delete failed ({resp.status_code}): {msg}",
            request=resp.request,
            response=resp,
        )
