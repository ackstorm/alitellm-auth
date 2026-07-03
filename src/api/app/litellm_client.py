# SPDX-License-Identifier: Apache-2.0
"""Async LiteLLM admin API client."""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, NoReturn

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


def _raise_litellm(resp: httpx.Response, endpoint: str) -> NoReturn:
    """Raise a uniform HTTPStatusError for a failed LiteLLM admin call."""
    msg = _extract_litellm_error(resp)
    raise httpx.HTTPStatusError(
        f"LiteLLM {endpoint} failed ({resp.status_code}): {msg}",
        request=resp.request,
        response=resp,
    )


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


def strip_bearer_prefix(value: str) -> str:
    """Normalize an `x-alitellm-auth-api-key` header value: accept both
    "sk-..." and "Bearer sk-...". Callers guard the None/empty case first.
    Strip first so a whitespace-padded "  Bearer sk-...  " also normalizes."""
    return value.strip().removeprefix("Bearer ").strip()


def _already_exists(resp) -> bool:
    """True if a LiteLLM create call reports the resource already exists.

    Older LiteLLM returns 409; newer returns 400 + "already exists" in the body
    (casing varies, e.g. "Team Already Exists" — WR-04). Centralized so all
    idempotent-create call sites agree (was copy-pasted, and the access-group
    copy had dropped the `.lower()`).
    """
    return resp.status_code == 409 or (
        resp.status_code == 400 and "already exists" in resp.text.lower()
    )


async def _ensure_access_group(client: httpx.AsyncClient, headers: dict, name: str) -> str | None:
    """Create the named access group if it doesn't exist; return its ID (or None on failure)."""
    resp = await client.post("/v1/access_group", headers=headers, json={"access_group_name": name})
    if resp.is_success:
        return resp.json().get("access_group_id")
    already_exists = _already_exists(resp)
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
            _raise_litellm(add_resp, "/team/member_add")

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
            _raise_litellm(update_resp, "/team/member_update")


async def get_team_member_budget(email: str, settings: Settings) -> dict | None:
    """Return the ENFORCED per-member-in-team budget for the user, or None.

    The cap that actually enforces for team-scoped keys is max_budget_in_team
    (set by ensure_team_member_budget); user-level max_budget does NOT enforce
    (RQ-1). Returns {"max_budget": float|None, "current": float,
    "budget_duration": str|None} read from the team membership, or None when no
    membership budget is available (caller degrades to the user-level figures).

    SOURCE (pinned by Phase-0 spike, LiteLLM v1.87.1): GET /team/info?team_id=
    team-<client_id>, member matched by user_id, budget read from
    litellm_budget_table. /key/list does NOT carry the membership budget on
    v1.87.1 (max_budget_in_team/team_member_spend come back null), so /team/info
    is the only source — and it works for keyless eager-created users too.
    H6: user_id/team_id always via httpx params={}, never f-string concat.
    """
    headers = _admin_headers(settings)
    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=10.0) as client:
        resp = await client.get("/team/info", headers=headers, params={"team_id": settings.team_id})
    if not resp.is_success:
        _raise_litellm(resp, "/team/info")
    data = resp.json()
    if not isinstance(data, dict):
        return None
    memberships = data.get("team_memberships") or []
    if not isinstance(memberships, list):
        return None
    member = next(
        (m for m in memberships if isinstance(m, dict) and m.get("user_id") == email),
        None,
    )
    if member is None:
        return None
    budget_table = member.get("litellm_budget_table")
    budget_table = budget_table if isinstance(budget_table, dict) else {}
    max_budget = budget_table.get("max_budget")
    if max_budget is None and member.get("spend") is None:
        # No membership budget configured for this user → let the caller degrade.
        return None
    return {
        "max_budget": max_budget,
        "current": float(member.get("spend") or 0),
        "budget_duration": budget_table.get("budget_duration"),
    }


async def ensure_team_and_user(
    email: str,
    settings: Settings,
    name: str | None = None,
    factory: dict | None = None,
    team_id: str | None = None,
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

    D-21: Step A3 runs ONLY when the user is first created (user_result not existed).
    On subsequent logins/key-mints the cap is left untouched so a manually-raised
    max_budget_in_team is not silently clobbered back to the factory default.
    """
    team_id = team_id or settings.team_id
    headers = _admin_headers(settings)

    if factory is None:
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
                "team_id": team_id,  # validated team choice, else default
                "team_alias": settings.litellm_default_team,
                "metadata": {"source": "token-factory", **team_meta_extra},
            },
        )
        team_exists = _already_exists(team_resp)
        if team_resp.status_code != 200 and not team_exists:
            _raise_litellm(team_resp, "/team/new")

        # Step B: Ensure shared access group exists (same name as team/client_id).
        await _ensure_access_group(client, headers, settings.oauth_client_id)

        # Step A2: Ensure user exists with D-15 factory user budget block.
        user_result = await ensure_litellm_user(
            email, settings, name=name, team_id=team_id, apply_budget=True, factory=factory
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
                missing = {k: v for k, v in factory_user.items() if existing_user.get(k) is None}
                if missing:
                    resp = await client.post(
                        "/user/update",
                        headers=headers,
                        json={"user_id": email, **missing},
                    )
                    if not resp.is_success:
                        _raise_litellm(resp, "/user/update (backfill)")
                    logger.info(
                        "D-16 lazy backfill: updated %s with fields %s",
                        email,
                        list(missing.keys()),
                    )
            except LiteLLMUserNotFound:
                logger.warning(
                    "D-16 backfill: user %s not found after existed=True; skipping", email
                )
            except httpx.HTTPStatusError as exc:
                logger.error("D-16 backfill failed for %s: %s", email, exc)
                raise

    # Step A3 (D-14 USER-V2-01 re-scope): set per-member budget cap via /team/member_add.
    # Adopts max_budget_in_team because the RQ-1 spike proved user-level max_budget does
    # NOT enforce for team-scoped keys on LiteLLM v1.85.1 (KEY_A=200 beyond cap; KEY_B=429).
    # D-21: set the cap ONLY when the user is first created — never overwrite on subsequent
    # logins/key-mints. Mirrors the D-16 "never clobber a manually-set value" philosophy so an
    # admin/gitops bump to max_budget_in_team survives re-logins (a re-applied factory value
    # would silently re-block a user who had a higher cap set by hand).
    # H3: only call when the factory provides a non-None, non-zero max_budget value.
    factory_user_budget = factory.get("user", {}).get("max_budget")
    if (
        not user_result.get("existed")
        and factory_user_budget is not None
        and factory_user_budget > 0
    ):
        await ensure_team_member_budget(email, team_id, factory_user_budget, settings)

    return team_id


async def generate_litellm_key(
    email: str,
    settings: Settings,
    name: str | None = None,
    duration: str | None = None,
    alias: str | None = None,
    team_id: str | None = None,
) -> dict:
    """
    Ensure the shared org team/user exist (idempotent) and generate a virtual key.

    Team is shared across all users — id + alias from LITELLM_DEFAULT_TEAM (default "default").

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
        {"key": "sk-...", "id": "...", "team_id": "..."}
    """
    headers = _admin_headers(settings)
    factory = _load_factory_config(settings.factory_config_path)
    user_meta_extra = factory.get("user", {}).get("metadata", {})
    # Deployment-provided key defaults (e.g. allowed_routes / models). By DEFAULT
    # we do NOT route-restrict the key: a generated key is a non-admin team key,
    # so LiteLLM already gates it by role (LLM + read/info routes; management
    # routes still require proxy_admin). The per-user Models/MCPs catalog needs
    # info routes like /model_group/info, so pinning allowed_routes=["llm_api_routes"]
    # broke it (403 once the sso_key_swapper impersonated the user's default key).
    # A security-conscious deployment can re-restrict via factory `key.allowed_routes`.
    factory_key_extra = {k: v for k, v in factory.get("key", {}).items() if k != "metadata"}

    # Steps A, B, A2: ensure team → access group → user (shared prerequisite, D-13).
    # Reuse the factory dict loaded above so the disk read happens once per mint (#11).
    team_id = await ensure_team_and_user(
        email, settings, name=name, factory=factory, team_id=team_id
    )

    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=30.0) as client:
        # Re-resolve access_group_id for the key payload (needed for access_group_ids field).
        access_group_id = await _ensure_access_group(client, headers, settings.oauth_client_id)

        # Step C: Generate virtual key scoped to the shared team, with full model access.
        # D-15: keys carry NO budget fields (budget is at the user level).
        # D-10: caller-supplied alias wins; default is readable AND second-unique
        # so sha256(key_alias) ids stay distinct (no DELETE/list collision).
        #
        # LiteLLM enforces a GLOBALLY-unique key_alias across ALL keys of ALL users
        # ("Key with alias 'default' already exists"). So the stored key_alias is an
        # OPAQUE, collision-proof token `lk-{random}` — never the user's name — which
        # also lets two keys share a friendly name. The friendly `display_alias` is
        # kept in metadata and is what the UI shows; the id is sha256(opaque alias),
        # stable across /me and /key/list.
        now = datetime.now(timezone.utc)
        display_alias = alias or f"key-{now.strftime('%Y-%m-%d-%H%M%S')}"
        key_alias = f"lk-{secrets.token_hex(8)}"
        key_payload: dict = {
            "models": ["all-team-models"],  # default — factory `key.models` may override
            # Deployment overrides (e.g. allowed_routes). NOT route-restricted by
            # default so the per-user catalog (/model_group/info) works; the
            # invariant fields below always win over anything factory supplies.
            **factory_key_extra,
            "team_id": team_id,  # validated team choice, else default
            "user_id": email,  # scope key to LiteLLM user (USER-02)
            "access_group_ids": [access_group_id] if access_group_id else [],
            "key_alias": key_alias,  # opaque lk-{random} (globally unique)
            "metadata": {
                "email": email,
                "name": name or email,
                "source": "token-factory",
                "created_at": now.isoformat(),
                "key_alias": display_alias,  # FRIENDLY name — what the UI shows
                **user_meta_extra,
            },
        }
        # D-10: include duration only when not None — never send "duration": null.
        if duration is not None:
            key_payload["duration"] = duration

        key_resp = await client.post("/key/generate", headers=headers, json=key_payload)

        if not key_resp.is_success:
            _raise_litellm(key_resp, "/key/generate")

    key_data = key_resp.json()
    metadata = _parse_metadata(key_data.get("metadata"))
    token = _get_token(key_data)
    return {
        "key": token,
        "id": _get_key_id(key_data, key_alias, metadata=metadata),
        "team_id": team_id,
    }


def _display_alias(k: dict, md: dict) -> str | None:
    """The FRIENDLY alias to show in the UI.

    The stored key_alias is an opaque `lk-{random}` token, so the friendly name
    lives in metadata.key_alias. Falls back to the raw key_alias for keys created
    outside this service (which carry a human alias directly).
    """
    return md.get("key_alias") or k.get("key_alias")


def _project_session_key(k: dict, md: dict) -> dict:
    """Project one raw /key/list item to the SAPI-03 metadata shape.

    D-17: 'budget' is always None (inherited from user/team; reported by /me).
    'token' is the LiteLLM key hash — the server-side delete id; the session
    router strips it (and any sk-) before returning to the browser.
    """
    return {
        "id": _get_key_id(k, metadata=md),
        "token": k.get("token"),
        # FRIENDLY alias for display; the id above keeps using the raw (namespaced)
        # key_alias so DELETE/list ids stay stable.
        "key_alias": _display_alias(k, md),
        "spend": k.get("spend", 0.0),
        "budget": None,
        "tpm_limit": k.get("tpm_limit"),
        "rpm_limit": k.get("rpm_limit"),
        "models": k.get("models"),
        "team_id": k.get("team_id"),  # NEW — which team this key is scoped to
        "created_at": md.get("created_at") or k.get("created_at"),
        "expires": k.get("expires"),
        # LiteLLM's per-key last-used timestamp (same field whoami surfaces). May be
        # null until the key is used / LiteLLM populates it; the UI shows "—" then.
        "last_used": k.get("last_active"),
        # Disabled state (LiteLLM /key/block sets this). Surfaced so the table can
        # show a "Disabled" status and the kebab offer Enable instead of Disable.
        "blocked": bool(k.get("blocked")),
        # Explicit "default key" flag (metadata-backed). Absent/false => not default.
        "is_default": bool(md.get("is_default")),
        # Raw metadata for SERVER-SIDE use only (Make-default read-modify-write).
        # The session router MUST strip this before returning to the browser
        # (it may hold factory user_meta_extra) — see session_list_keys strip set.
        "metadata": md,
    }


_EMPTY_SESSION_KEY = {
    "id": None,
    "token": None,
    "key_alias": None,
    "spend": 0.0,
    "budget": None,
    "tpm_limit": None,
    "rpm_limit": None,
    "models": None,
    "team_id": None,  # NEW
    "created_at": None,
    "expires": None,
    "last_used": None,
    "blocked": False,
    "is_default": False,
    "metadata": {},
}


def _is_key_dict(k: Any) -> bool:
    """Guard a /key/list row: log and reject anything that is not a dict.

    LiteLLM should only return dict rows (or str, handled separately); a non-dict
    is unexpected. Callers skip the row: ``if not _is_key_dict(k): continue``.
    """
    if isinstance(k, dict):
        return True
    logger.warning(
        "LiteLLM /key/list returned unexpected type (not str/dict): %r type=%s", k, type(k)
    )
    return False


async def _list_session_keys_fallback(email: str, settings: Settings) -> list[dict]:
    """Fallback: hydrate keys via list_litellm_keys + get_key_info when /key/list returns strings."""
    raw_keys = await list_litellm_keys(email, settings)
    # list_litellm_keys already handles string-item hydration + email filtering.
    # Project each key to the SAPI-03 shape.
    out = []
    for k in raw_keys:
        if not isinstance(k, dict):
            out.append(dict(_EMPTY_SESSION_KEY))
            continue
        out.append(_project_session_key(k, _parse_metadata(k.get("metadata"))))
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
        _raise_litellm(resp, "/key/list")

    rows = resp.json().get("keys", [])
    if not isinstance(rows, list):
        logger.warning("LiteLLM /key/list returned non-list 'keys': %r", rows)
        return []

    out = []
    for k in rows:
        # If the proxy returned a string, return_full_object was ignored → trigger fallback.
        if isinstance(k, str):
            return await _list_session_keys_fallback(email, settings)
        if not _is_key_dict(k):
            continue
        out.append(_project_session_key(k, _parse_metadata(k.get("metadata"))))

    out.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return out


async def user_daily_activity(
    email: str,
    settings: Settings,
    start_date: str,
    end_date: str,
) -> dict:
    """Fetch the daily activity breakdown for a user from LiteLLM (paginated).

    Calls GET /user/daily/activity with params (H6: always params={}, never f-string).
    Returns the SpendAnalyticsPaginatedResponse shape:
        {results: [{date, metrics:{spend,total_tokens,...}, breakdown:{...}}],
         metadata: {total_spend, total_tokens, ..., has_more, page, total_pages}}

    Follows pagination with a bounded page loop (mirrors list_litellm_users): a
    max-range window (RESEARCH §4: up to 366 days) must not be silently truncated
    when LiteLLM returns metadata.has_more=true. results[] are concatenated across
    pages; the returned metadata.total_* are SUMMED across every page. LiteLLM's
    per-response metadata.total_* is only a per-PAGE partial (it sums the day-rows on
    that page), NOT a full-range aggregate, so the window total must be accumulated
    page by page — see the summed_totals loop below.

    Used by GET /api/session/stats.

    Args:
        email: User identifier (user_id=email convention).
        settings: Application settings.
        start_date: ISO date string, e.g. "2026-05-01".
        end_date: ISO date string, e.g. "2026-05-31".
    """
    headers = _admin_headers(settings)
    # WR-02: results[] are per-DAY rows. Pin an explicit page_size so the 366-day
    # max range (RESEARCH §4) deterministically fits inside the page budget:
    # page_size=100 * max_pages=12 = 1200 day-rows >> 366, leaving large headroom
    # so series/per-model/per-key breakdowns are never silently truncated for any
    # in-range window (the prior implicit page size could truncate past page 12).
    page_size = 100
    max_pages = 12
    page = 1
    accumulated: list = []
    last_metadata: dict = {}
    # Window totals MUST be summed across pages. LiteLLM's metadata.total_* is a
    # PER-PAGE partial (it sums only the day-rows on THIS page), NOT the full-range
    # aggregate the old code assumed — verified live on v1.89.2: a multi-page window
    # returned the LAST page's partial as the "total" (MTD showed page 4 = 220 of
    # 10588 real requests; a single-page window like 7d was correct by luck). Days
    # that straddle a page boundary are SPLIT across pages, so the per-page partials
    # add up to the exact window total with no double-counting.
    summed_totals: dict[str, float] = {}

    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=15.0) as client:
        while True:
            resp = await client.get(
                "/user/daily/activity",
                headers=headers,
                params={
                    "user_id": email,
                    "start_date": start_date,
                    "end_date": end_date,
                    "page": page,
                    "page_size": page_size,
                },
            )
            if not resp.is_success:
                _raise_litellm(resp, "/user/daily/activity")
            data = resp.json()
            results = data.get("results", []) if isinstance(data, dict) else []
            if isinstance(results, list):
                accumulated.extend(results)
            metadata = data.get("metadata", {}) if isinstance(data, dict) else {}
            if isinstance(metadata, dict):
                last_metadata = metadata
                for field, value in metadata.items():
                    # Sum the numeric total_* counters only; total_pages is paging
                    # bookkeeping, not a window total, and bools must not coerce to 1.
                    if (
                        field.startswith("total_")
                        and field != "total_pages"
                        and isinstance(value, (int, float))
                        and not isinstance(value, bool)
                    ):
                        summed_totals[field] = summed_totals.get(field, 0) + value

            if not last_metadata.get("has_more"):
                break
            page += 1
            if page > max_pages:
                logger.warning(
                    "user_daily_activity: reached max_pages cap (%d) for %s; "
                    "pagination truncated at ~%d day-rows",
                    max_pages,
                    email,
                    len(accumulated),
                )
                break

    # Overlay the summed window totals on the last page's metadata so total_* reflect
    # the FULL range while page/has_more bookkeeping is preserved. For a single-page
    # window summed_totals == that page's totals, so behaviour is unchanged there.
    merged_metadata = {**last_metadata, **summed_totals}
    return {"results": accumulated, "metadata": merged_metadata}


async def list_litellm_keys(email: str, settings: Settings) -> list[dict]:
    """List all virtual keys for a specific user email."""
    headers = _admin_headers(settings)
    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=10.0) as client:
        # LiteLLM doesn't support filtering /key/list by metadata directly in all versions,
        # but we can filter by team_id and then client-side filter by email metadata.
        team_id = settings.team_id
        resp = await client.get("/key/list", headers=headers, params={"team_id": team_id})

    if not resp.is_success:
        _raise_litellm(resp, "/key/list")

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

        if not _is_key_dict(k):
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
                    # Preserved so the fallback projection can surface "last used"
                    # and the disabled state.
                    "last_active": k.get("last_active"),
                    "blocked": k.get("blocked"),
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
        _raise_litellm(resp, "/key/delete")


async def set_litellm_key_default(
    token: str,
    settings: Settings,
    *,
    is_default: bool,
    existing_metadata: dict,
) -> None:
    """Set/clear the is_default flag on a virtual key via /key/update.

    LiteLLM replaces the whole `metadata` field on update, so we merge into the
    existing metadata (read-modify-write) and send the full dict. `token` is the
    hashed token from /key/list (same value /key/delete accepts — LiteLLM only
    re-hashes values starting with `sk-`, so a stored hash passes through).
    """
    headers = _admin_headers(settings)
    merged = dict(existing_metadata or {})
    if is_default:
        merged["is_default"] = True
    else:
        merged.pop("is_default", None)
    payload = {"key": token, "metadata": merged}
    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=10.0) as client:
        resp = await client.post("/key/update", headers=headers, json=payload)
    if not resp.is_success:
        _raise_litellm(resp, "/key/update")


async def update_litellm_key_team(token: str, team_id: str, settings: Settings) -> None:
    """Move a virtual key to ``team_id`` via /key/update.

    Sends ONLY {key, team_id} so models/metadata/budget are untouched
    (LiteLLM replaces only the supplied fields). ``token`` is the hashed value
    from /key/list (same value /key/delete and /key/update accept). Caller MUST
    have validated the user's membership of ``team_id`` first (assert_team_membership).
    """
    headers = _admin_headers(settings)
    payload = {"key": token, "team_id": team_id}
    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=10.0) as client:
        resp = await client.post("/key/update", headers=headers, json=payload)
    if not resp.is_success:
        _raise_litellm(resp, "/key/update")


async def block_litellm_key(token: str, settings: Settings, *, blocked: bool) -> None:
    """Disable (block) or re-enable (unblock) a virtual key — reversible, NOT a delete.

    Calls POST /key/block | /key/unblock with {"key": token}. Blocking sets the
    key's `blocked` flag so LiteLLM rejects its requests; unblocking clears it.
    `token` is the hashed token from /key/list (the same value /key/delete and
    /key/update accept — LiteLLM only re-hashes `sk-` plaintext).
    """
    headers = _admin_headers(settings)
    route = "/key/block" if blocked else "/key/unblock"
    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=10.0) as client:
        resp = await client.post(route, headers=headers, json={"key": token})
    if not resp.is_success:
        _raise_litellm(resp, route)


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
        _raise_litellm(resp, "/key/info")

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
        # Raw (namespaced) alias — keeps sha256(key_alias) ids stable in the
        # string-item fallback projection path.
        "key_alias": info.get("key_alias"),
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
        "blocked": info.get("blocked"),
    }


# ── LiteLLM User lifecycle ──────────────────────────────────────────────────

# LiteLLM v1.83 returns this placeholder for unknown/ambiguous user lookups
# instead of a 404 (see hardening note H1).
LITELLM_PLACEHOLDER_USER_ID = "default_user_id"


class LiteLLMUserNotFound(Exception):
    """Raised when a LiteLLM user genuinely does not exist."""


class TeamMembershipError(Exception):
    """Raised when a user is asked to be scoped to a team they don't belong to."""


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


async def list_user_teams(email: str, settings: Settings) -> list[dict]:
    """Return the teams the user belongs to as ordered, de-duplicated
    ``[{"id", "alias"}]`` pairs.

    team_ids come from /user/info (H6: email via params, never f-string); the
    id→alias map comes from /team/list. Order follows first-seen in /user/info.
    An id with no /team/list match falls back to the id as its own alias.
    Never raises for an empty membership list — returns [].

    NOTE: we extract the raw team_id directly (NOT via _normalize_teams, which
    returns alias-preferred strings for object-shaped teams, H2) because the
    returned ``"id"`` is sent as ``team_id`` to /key/generate and /key/update —
    it must always be a real team_id, never an alias.
    """
    headers = _admin_headers(settings)
    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=10.0) as client:
        info_resp = await client.get("/user/info", headers=headers, params={"user_id": email})
        if not info_resp.is_success:
            _raise_litellm(info_resp, "/user/info")
        list_resp = await client.get("/team/list", headers=headers)

    user_info = info_resp.json().get("user_info") or {}
    raw_teams = user_info.get("teams") or []

    rows = list_resp.json() if list_resp.is_success else []
    if isinstance(rows, dict):
        rows = rows.get("teams", [])
    alias_by_id = {
        r.get("team_id"): (r.get("team_alias") or r.get("team_id"))
        for r in rows
        if isinstance(r, dict) and r.get("team_id")
    }

    out: list[dict] = []
    seen: set[str] = set()
    for t in raw_teams:
        tid = t if isinstance(t, str) else (t.get("team_id") if isinstance(t, dict) else None)
        if not tid or tid in seen:
            continue
        seen.add(tid)
        # prefer the object's own alias, then /team/list, then the id itself
        own_alias = t.get("team_alias") if isinstance(t, dict) else None
        out.append({"id": tid, "alias": own_alias or alias_by_id.get(tid, tid)})
    return out


async def assert_team_membership(email: str, team_id: str, settings: Settings) -> None:
    """Raise TeamMembershipError if ``email`` is not a member of ``team_id``.

    SECURITY: ``email`` MUST be the authenticated session email; ``team_id`` is
    untrusted client input. Memberships are read fresh from LiteLLM, never from
    the request. Callers map TeamMembershipError → HTTP 403.
    """
    teams = await list_user_teams(email, settings)
    if not any(t["id"] == team_id for t in teams):
        raise TeamMembershipError(f"{email} is not a member of team {team_id!r}")


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
    factory: dict | None = None,
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
        if factory is None:
            factory = _load_factory_config(settings.factory_config_path)
        user_budget = {
            k: v for k, v in factory.get("user", {}).items() if k != "metadata" and v is not None
        }
        payload.update(user_budget)
    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=30.0) as client:
        resp = await client.post("/user/new", headers=headers, json=payload)
    exists = _already_exists(resp)
    if not resp.is_success and not exists:
        _raise_litellm(resp, "/user/new")
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
            _raise_litellm(resp, "/user/info")
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
            _raise_litellm(list_resp, "/user/list fallback")

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
                _raise_litellm(resp, "/user/list")
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
        _raise_litellm(resp, "/user/delete")


# ---------------------------------------------------------------------------
# Read-only catalogs (model groups + MCP servers) for the SPA (GET /api/session/*)
# ---------------------------------------------------------------------------


async def _list_catalog(
    endpoint: str,
    projector: Callable[[dict], dict],
    unwrap: Callable[[Any], Any],
    settings: Settings,
    user_id: str | None,
) -> list[dict]:
    """Shared scaffold for the read-only per-user catalogs (models / MCP / A2A).

    Builds master-key headers PLUS the ``x-user-id`` scoping header (the value is
    ALWAYS the authenticated session email, NEVER client input — the user-scoping
    contract; see the public list_* callers), GETs ``endpoint``, raises uniformly
    on failure, then unwraps → allow-list-projects → sorts by name.

    ``unwrap`` maps the parsed JSON to the row list; it stays per-endpoint because
    the wrapper shape and bare-list tolerance differ across catalogs. A non-list
    result degrades to []. ``projector`` is the per-row EXPLICIT allow-list.
    """
    headers = _admin_headers(settings)
    if user_id:
        headers["x-user-id"] = user_id
    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=15.0) as client:
        resp = await client.get(endpoint, headers=headers)
    if not resp.is_success:
        _raise_litellm(resp, endpoint)
    rows = unwrap(resp.json())
    if not isinstance(rows, list):
        logger.warning("LiteLLM %s returned unexpected shape: %r", endpoint, rows)
        return []
    out = [projector(r) for r in rows if isinstance(r, dict)]
    out.sort(key=lambda x: (x.get("name") or "").lower())
    return out


def _project_model_group(m: dict) -> dict:
    """Allow-listed projection of one /model_group/info row.

    EXPLICIT allow-list (not a passthrough): only the public per-alias presentation
    fields are surfaced, so no future LiteLLM field can leak through. /model_group/info
    already omits litellm_params (the upstream model / api_base / api_key), which is
    why it — not /model/info — is the safe public catalog source.
    """
    providers = m.get("providers")
    return {
        "name": m.get("model_group"),
        "providers": [str(p) for p in providers] if isinstance(providers, list) else [],
        "mode": m.get("mode"),
        "max_input_tokens": m.get("max_input_tokens"),
        "max_output_tokens": m.get("max_output_tokens"),
        "input_cost_per_token": m.get("input_cost_per_token"),
        "output_cost_per_token": m.get("output_cost_per_token"),
        "supports_vision": bool(m.get("supports_vision")),
        "supports_function_calling": bool(m.get("supports_function_calling")),
        "supports_reasoning": bool(m.get("supports_reasoning")),
        "supports_web_search": bool(m.get("supports_web_search")),
    }


async def list_litellm_models(settings: Settings, user_id: str | None = None) -> list[dict]:
    """List the public model-group catalog (GET /model_group/info).

    Uses /model_group/info (NOT /model/info): the group view is the safe public
    projection — it carries cost/limits/capabilities per public alias and does NOT
    expose litellm_params (the real upstream model, api_base, or api_key). Each row
    is run through the explicit allow-list _project_model_group. Sorted by name.

    When ``user_id`` is set, sends ``x-user-id: <user_id>`` alongside the master-key
    Authorization so the deployment's LiteLLM custom auth scopes the catalog to that
    user. The value MUST come from the authenticated session, never client input.

    Raises httpx.HTTPStatusError / httpx.RequestError on failure (caller degrades).
    Used by GET /api/session/models.
    """
    # /model_group/info is a strict {"data": [...]} wrapper — no bare-list fallback.
    return await _list_catalog(
        "/model_group/info",
        _project_model_group,
        lambda d: d.get("data", []) if isinstance(d, dict) else [],
        settings,
        user_id,
    )


def _project_mcp_server(s: dict) -> dict:
    """Allow-listed PUBLIC projection of one MCP server row (LiteLLM_MCPServerTable).

    SECURITY: an EXPLICIT allow-list — it deliberately DROPS every secret-bearing or
    internal field (credentials, env, static_headers, extra_headers, command/args,
    authorization_url/token_url/registration_url, *_by). Only public presentation
    fields are surfaced. auth_type is the TYPE label only (e.g. "oauth2"), never a
    secret value.
    """
    tools = s.get("allowed_tools")
    tools = [str(t) for t in tools] if isinstance(tools, list) else []
    groups = s.get("mcp_access_groups")
    groups = [str(g) for g in groups] if isinstance(groups, list) else []
    return {
        "id": s.get("server_id"),
        "name": s.get("alias") or s.get("server_name"),
        "description": s.get("description"),
        "url": s.get("url"),
        "transport": s.get("transport"),
        "auth_type": s.get("auth_type"),
        "status": s.get("status"),
        "tools": tools,
        "tool_count": len(tools),
        "access_groups": groups,
    }


async def list_litellm_mcp_servers(settings: Settings, user_id: str | None = None) -> list[dict]:
    """List configured MCP servers from the LiteLLM MCP gateway (GET /v1/mcp/server).

    Returns a BARE JSON array of server objects (a {"data"|"servers": [...]} wrapper
    is tolerated defensively). Each row is run through the allow-list
    _project_mcp_server — NEVER credentials/env/headers/OAuth URLs. Sorted by name.

    When ``user_id`` is set, sends ``x-user-id: <user_id>`` alongside the master-key
    Authorization so the deployment's LiteLLM custom auth scopes the catalog to that
    user. The value MUST come from the authenticated session, never client input.

    Raises httpx.HTTPStatusError on a non-2xx (the caller maps a 404 — an older
    LiteLLM with no MCP gateway — to an "unavailable" empty state) and
    httpx.RequestError when unreachable. Used by GET /api/session/mcp.
    """
    # Bare JSON array, with a {"data"|"servers": [...]} wrapper tolerated defensively.
    return await _list_catalog(
        "/v1/mcp/server",
        _project_mcp_server,
        lambda d: (d.get("data") or d.get("servers") or []) if isinstance(d, dict) else d,
        settings,
        user_id,
    )


def _project_a2a_agent(a: dict) -> dict:
    """Allow-listed PUBLIC projection of one A2A agent row (LiteLLM AgentResponse).

    SECURITY: an EXPLICIT allow-list mirroring _project_mcp_server. It deliberately
    DROPS every secret-bearing or internal field (static_headers, extra_headers,
    litellm_params, object_permission, *_by, spend, limits). Only public agent-card
    presentation fields are surfaced.

    The rich metadata lives under ``agent_card_params`` (the A2A AgentCard):
    name/description/url/version/skills/capabilities. Skills are flattened to their
    names; ``streaming`` is read from capabilities. NEVER surface securitySchemes.
    """
    card = a.get("agent_card_params")
    card = card if isinstance(card, dict) else {}

    raw_skills = card.get("skills")
    skills: list[str] = []
    if isinstance(raw_skills, list):
        for s in raw_skills:
            if isinstance(s, dict):
                name = s.get("name") or s.get("id")
                if name:
                    skills.append(str(name))
            elif s:
                skills.append(str(s))

    caps = card.get("capabilities")
    streaming = bool(caps.get("streaming")) if isinstance(caps, dict) else False

    return {
        "id": a.get("agent_id"),
        "name": a.get("agent_name") or card.get("name"),
        "description": card.get("description"),
        "url": card.get("url"),
        "transport": card.get("preferredTransport"),
        "version": card.get("version"),
        "skills": skills,
        "skill_count": len(skills),
        "streaming": streaming,
    }


async def list_litellm_a2a_agents(settings: Settings, user_id: str | None = None) -> list[dict]:
    """List configured A2A agents from the LiteLLM agent gateway (GET /v1/agents).

    Returns a BARE JSON array of agent objects (a {"data"|"agents": [...]} wrapper is
    tolerated defensively). Each row is run through the allow-list _project_a2a_agent
    — public agent-card fields only, NEVER headers/litellm_params/object_permission.
    Sorted by name.

    When ``user_id`` is set, sends ``x-user-id: <user_id>`` alongside the master-key
    Authorization. The /v1/agents endpoint itself does not read x-user-id, but the
    deployment's gateway custom auth (sso_key_swapper) resolves master+x-user-id to
    the user's default key BEFORE the endpoint runs, so /v1/agents then filters by
    that key's agent access groups — the same per-user scoping path as MCP. The
    value MUST come from the authenticated session, never client input.

    Raises httpx.HTTPStatusError on a non-2xx (the caller maps a 404 — a LiteLLM with
    no A2A gateway, A2A is beta since v1.80.8 — to an "unavailable" empty state) and
    httpx.RequestError when unreachable. Used by GET /api/session/a2a.
    """
    # Bare JSON array, with a {"data"|"agents": [...]} wrapper tolerated defensively.
    return await _list_catalog(
        "/v1/agents",
        _project_a2a_agent,
        lambda d: (d.get("data") or d.get("agents") or []) if isinstance(d, dict) else d,
        settings,
        user_id,
    )


# ---------------------------------------------------------------------------
# User-scoping contract probe (sso_key_swapper custom auth)
# ---------------------------------------------------------------------------

# A deliberately non-existent user id used ONLY to probe the LiteLLM custom-auth
# contract. It must never match a real LiteLLM user (the `@invalid.local` host and
# the sentinel affixes make a collision practically impossible).
CONTRACT_PROBE_USER_ID = "__alitellm-auth-contract-probe__@invalid.local"


async def verify_user_scoping_contract(settings: Settings) -> str:
    """Probe whether LiteLLM enforces the master-key + x-user-id impersonation contract.

    alitellm-auth scopes the per-user Models/MCP catalogs by sending the master key
    in Authorization PLUS an `x-user-id` header; the deployment's `sso_key_swapper`
    custom auth (see deploy/litellm/) resolves that to the user's default key. This
    function verifies that contract is actually installed by hitting `/v1/models`
    (a master key alone lists the models, or an empty list if none are configured)
    while impersonating a deliberately NON-EXISTENT user via `x-user-id`:

      * custom auth installed  -> the impersonation is rejected (401/403)  => "enforced"
      * custom auth absent     -> the master key authenticates as full admin and the
                                  model list comes back (2xx), x-user-id ignored
                                                                             => "not_enforced"
      * backend unreachable / 5xx -> cannot tell                            => "unknown"

    A "not_enforced" result means the per-user catalog silently degrades to the
    global admin view — the caller logs a prominent warning (we do NOT fail
    readiness over it). "unknown" is transient (boot ordering / outage).
    """
    headers = _admin_headers(settings)
    headers["x-user-id"] = CONTRACT_PROBE_USER_ID
    try:
        async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=10.0) as client:
            resp = await client.get("/v1/models", headers=headers)
    except httpx.RequestError:
        return "unknown"
    if resp.status_code in (401, 403):
        return "enforced"
    if resp.is_success:
        return "not_enforced"
    return "unknown"
