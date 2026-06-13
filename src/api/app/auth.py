# SPDX-License-Identifier: Apache-2.0
"""OIDC authentication routes."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

import httpx
from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings
from app.litellm_client import (
    delete_litellm_key,
    ensure_team_and_user,
    generate_litellm_key,
    get_key_info,
    get_litellm_user,
    LiteLLMUserNotFound,
    list_litellm_keys,
)

logger = logging.getLogger(__name__)

router = APIRouter()
oauth = OAuth()  # module-level so tests can patch it

TEMPLATES_DIR = Path(__file__).parent / "templates"


def configure_auth(settings: Settings) -> None:
    """Register the OIDC provider (Dex, Keycloak, etc.). Call once at app startup."""
    oauth.register(
        name="oidc",
        server_metadata_url=f"{settings.oauth_issuer_url}/.well-known/openid-configuration",
        client_id=settings.oauth_client_id,
        client_secret=settings.oauth_client_secret,
        client_kwargs={"scope": "openid email profile"},
    )


def _templates() -> Jinja2Templates:
    return Jinja2Templates(directory=str(TEMPLATES_DIR))


@router.get("/api/oauth/whoami")
async def whoami(
    request: Request,
    x_alitellm_auth_api_key: str | None = Header(default=None),
) -> JSONResponse:
    """Return metadata for the authenticated LiteLLM key, enriched with user info.

    Reads the ``x-alitellm-auth-api-key`` header, validates it against LiteLLM,
    enriches the response with user-level data from LiteLLM, and returns JSON.

    Error semantics (D-03):
    - Missing header → 401
    - Invalid/unknown key (get_key_info 4xx) → 401 (don't reveal key existence)
    - Valid key but LiteLLM User absent → 404
    - Enrichment call fails with 5xx → 502
    """
    if not x_alitellm_auth_api_key:
        raise HTTPException(status_code=401, detail="Missing x-alitellm-auth-api-key header")

    # Accept both "sk-..." and "Bearer sk-..."
    api_key = x_alitellm_auth_api_key.removeprefix("Bearer ").strip()

    settings: Settings = request.app.state.settings
    try:
        info = await get_key_info(api_key, settings)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        # 404 maps to 401 intentionally — don't reveal whether the key exists
        if status in (401, 403, 404):
            raise HTTPException(status_code=401, detail="Invalid or unknown API key")
        raise HTTPException(status_code=502, detail="LiteLLM key lookup failed")
    except httpx.RequestError:
        # ConnectError/TimeoutException are RequestError subclasses, NOT
        # HTTPStatusError. A backend-unreachable condition must surface as the
        # documented 502, not an uncaught 500 (WR-01).
        raise HTTPException(status_code=502, detail="LiteLLM backend unreachable")

    # Build response from get_key_info(); user_id is included via the comprehension
    # because get_key_info now returns it (API-02). The raw "key" field is excluded
    # (not safe to expose here). The legacy "user" alias is dropped (D-02).
    payload = {k: v for k, v in info.items() if k != "key"}

    # Enrich with LiteLLM user data (D-01). A valid key may lack an email in its
    # metadata (keys created outside the token factory, or older keys). In that
    # case we cannot perform a meaningful user lookup, so we return the key info
    # unenriched rather than emit a deceptive 404 (WR-01).
    email = info.get("email")
    if not email:
        return JSONResponse(payload)

    try:
        user = await get_litellm_user(email, settings)
        payload["litellm_user"] = user
    except LiteLLMUserNotFound:
        raise HTTPException(status_code=404, detail="LiteLLM user not found")
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=502, detail="LiteLLM enrichment failed")
    except httpx.RequestError:
        # Backend unreachable during enrichment → 502, not uncaught 500 (WR-01).
        raise HTTPException(status_code=502, detail="LiteLLM enrichment failed")

    return JSONResponse(payload)


@router.get("/api/oauth/login")
async def login(request: Request, action: str = "login") -> HTMLResponse:
    """Redirect user to Dex for authentication.

    ``?action`` selects the post-callback behavior (D-02/D-13):
    - ``"login"`` (default) → the callback mints a new LiteLLM key.
    - ``"ui"``              → the callback eager-creates the LiteLLM user WITHOUT
                              minting a key (the SPA sign-in CTA navigates here).

    T-09-04: the param is whitelisted before being written to the session — an
    arbitrary value can never enter ``oauth_action`` (falls back to ``"login"``).
    """
    settings: Settings = request.app.state.settings
    request.session["oauth_action"] = action if action in {"login", "ui"} else "login"
    callback_url = f"{settings.app_base_url}/api/oauth/callback"
    return await oauth.oidc.authorize_redirect(request, callback_url)


@router.get("/api/oauth/logout")
async def logout(request: Request) -> RedirectResponse:
    """Clear the local session and return to the /ui sign-in landing.

    The SPA "sign out" link (app.js) navigates here. This is an app-LOCAL logout:
    ``session.clear()`` empties the signed session, so Starlette's SessionMiddleware
    emits a cookie-clearing ``Set-Cookie`` on this response and the SPA cold-loads
    straight into the sign-in card (a /me 401 on a fresh page = "signin", not the
    silent "expired" re-login).

    The OIDC provider's SSO session is intentionally left intact — RP-initiated
    end-session (Dex ``end_session_endpoint``) is out of scope, so a fresh sign-in
    may silently re-authenticate via the IdP. Trailing slash on /ui/ avoids the
    StaticFiles slash-redirect hop (which emits a cleartext http:// Location behind
    the TLS-terminating gateway).
    """
    settings: Settings = request.app.state.settings
    request.session.clear()
    return RedirectResponse(f"{settings.app_base_url}/ui/", status_code=302)


@router.get("/api/oauth/callback", name="auth_callback", response_model=None)
async def auth_callback(request: Request) -> HTMLResponse | JSONResponse:
    """Handle Dex callback for all OIDC flows.

    Reads ``session["oauth_action"]`` to decide what to do after authentication:
    - ``"login"``  (default) → generate a new LiteLLM key → success HTML
    - ``"reveal"``            → list existing keys     → success HTML (latest)
    - ``"tokens"``            → list existing keys     → JSON
    """
    templates = _templates()
    action = request.session.pop("oauth_action", "login")

    # 1. Exchange authorization code for OIDC token
    try:
        token = await oauth.oidc.authorize_access_token(request)
    except Exception as exc:
        # Never render the raw exception (may carry issuer URLs / error_description)
        # into the page (#4). Log server-side, show a generic message.
        logger.error("callback: OIDC token exchange failed: %s", exc)
        return templates.TemplateResponse(
            request,
            "error.html",
            {"error": "Authentication failed. Please try signing in again."},
            status_code=400,
        )

    # 2. Extract user identity
    user_info = token.get("userinfo") or {}
    email = user_info.get("email")
    name = user_info.get("name") or email

    if not email:
        return templates.TemplateResponse(
            request,
            "error.html",
            {"error": "No email claim returned by identity provider."},
            status_code=400,
        )

    settings: Settings = request.app.state.settings

    # D-02: stamp the session for ALL actions (login, reveal, tokens, ui).
    # The session cookie is signed but NOT encrypted — store only non-sensitive identity.
    # D-01: NEVER store the access_token / id_token / any sk- here (signed, not encrypted).
    request.session["sub"] = user_info.get("sub")
    request.session["email"] = email
    request.session["name"] = name
    request.session["authenticated_at"] = datetime.now(timezone.utc).isoformat()

    # 3. Dispatch based on action
    if action == "ui":
        # D-13: eager-create the LiteLLM user on first /ui login (no key minted).
        # Dashboard entry makes the user exist immediately so /me is coherent.
        try:
            await ensure_team_and_user(email, settings, name=name)
        except Exception as exc:
            # D-09 graceful degrade — still redirect; /me handles the transient no-user case.
            logger.error("ui: ensure_team_and_user failed for %s: %s", email, exc)
        return RedirectResponse(f"{settings.app_base_url}/ui", status_code=302)

    if action == "reveal":
        try:
            keys = await list_litellm_keys(email, settings)
        except Exception as exc:
            # Never interpolate the raw backend exception (which can carry
            # resp.text via _extract_litellm_error) into the HTML page returned
            # to the browser. Log server-side, render a generic message (WR-A,
            # same non-leak treatment as the WR-05 delete_token fix).
            logger.error("reveal: list_litellm_keys failed for %s: %s", email, exc)
            return templates.TemplateResponse(
                request,
                "error.html",
                {"error": "Could not retrieve your tokens. Please try again later."},
                status_code=500,
            )
        if not keys:
            return templates.TemplateResponse(
                request,
                "error.html",
                {"error": "No tokens found for this user. Please use /login to create one."},
                status_code=404,
            )
        latest = keys[0]
        return templates.TemplateResponse(
            request,
            "success.html",
            {
                "name": name,
                "email": email,
                "key": None,
                "key_id": latest["id"],
                "team_id": f"team-{settings.oauth_client_id}",
                "api_url": f"{settings.api_public_url}/v1",
            },
        )

    if action == "tokens":
        try:
            keys = await list_litellm_keys(email, settings)
        except Exception as exc:
            # Same non-leak treatment as the reveal branch above (WR-A): log the
            # raw exception server-side, return a generic message to the client.
            logger.error("tokens: list_litellm_keys failed for %s: %s", email, exc)
            return templates.TemplateResponse(
                request,
                "error.html",
                {"error": "Could not retrieve your tokens. Please try again later."},
                status_code=500,
            )
        safe_keys = [{k: v for k, v in t.items() if k != "key"} for t in keys]
        return JSONResponse({"email": email, "tokens": safe_keys})

    # Default: action == "login" — generate a new key
    try:
        key_data = await generate_litellm_key(email, settings, name=name)
    except Exception as exc:
        # Never interpolate the raw backend error body (resp.text via
        # _extract_litellm_error) into the page (#4) — same non-leak treatment as
        # the reveal/tokens branches (WR-A). Log server-side, show generic copy.
        logger.error("login: key generation failed for %s: %s", email, exc)
        return templates.TemplateResponse(
            request,
            "error.html",
            {"error": "Could not create your API key. Please try again later."},
            status_code=500,
        )

    return templates.TemplateResponse(
        request,
        "success.html",
        {
            "name": name,
            "email": email,
            "key": key_data["key"],
            "key_id": key_data["id"],
            "team_id": key_data["team_id"],
            "api_url": f"{settings.api_public_url}/v1",
        },
    )


@router.get("/api/oauth/reveal")
async def reveal(request: Request) -> HTMLResponse:
    """Redirect user to Dex for authentication (shows latest existing key on return)."""
    settings: Settings = request.app.state.settings
    request.session["oauth_action"] = "reveal"
    callback_url = f"{settings.app_base_url}/api/oauth/callback"
    return await oauth.oidc.authorize_redirect(request, callback_url)


@router.get("/api/oauth/tokens")
async def list_tokens(request: Request) -> HTMLResponse:
    """Redirect user to Dex for authentication (returns JSON token list on return)."""
    settings: Settings = request.app.state.settings
    request.session["oauth_action"] = "tokens"
    callback_url = f"{settings.app_base_url}/api/oauth/callback"
    return await oauth.oidc.authorize_redirect(request, callback_url)


@router.delete("/api/oauth/tokens/{key_id}")
async def delete_token(
    request: Request,
    key_id: str,
    x_alitellm_auth_api_key: str | None = Header(default=None),
) -> JSONResponse:
    """Delete a specific token by its key_id/alias.

    Requires a valid API key in the header to authenticate the user.
    """
    if not x_alitellm_auth_api_key:
        raise HTTPException(status_code=401, detail="Missing x-alitellm-auth-api-key header")

    api_key = x_alitellm_auth_api_key.removeprefix("Bearer ").strip()
    settings: Settings = request.app.state.settings

    # 1. Authenticate the caller to get their email.
    # Distinguish a genuine credential problem (4xx → 401) from a backend
    # outage (5xx → 502); a valid key must not be reported as "invalid" just
    # because LiteLLM is unhealthy (WR-02).
    try:
        caller_info = await get_key_info(api_key, settings)
        email = caller_info.get("email")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code in (401, 403, 404):
            raise HTTPException(status_code=401, detail="Invalid or unknown API key")
        raise HTTPException(status_code=502, detail="LiteLLM key lookup failed")
    except httpx.RequestError:
        # Backend unreachable on auth → 502, not an uncaught 500 (WR-02/#3).
        raise HTTPException(status_code=502, detail="LiteLLM backend unreachable")

    # An email-less caller cannot own a token-factory key. Mirror the WR-01
    # whoami guard here on the destructive path: without this, email is None and
    # the ownership filter (metadata.get("email") == None) would match every
    # other email-less key in the shared team, letting the caller enumerate and
    # delete keys that are not theirs (WR-B).
    if not email:
        raise HTTPException(status_code=403, detail="Key has no associated user")

    # 2. Find the token associated with this ID for this user
    try:
        user_keys = await list_litellm_keys(email, settings)
        target_token = None

        for k in user_keys:
            if k["id"] == key_id:
                target_token = k["key"]
                break

        if not target_token:
            raise HTTPException(status_code=404, detail="Token not found or does not belong to you")

        # 3. Delete the token
        await delete_litellm_key(target_token, settings)
        logger.info("User %s deleted key %s", email, key_id)
    except HTTPException:
        raise
    except httpx.HTTPStatusError as exc:
        # Narrow the mapping and never echo raw backend text (which may include
        # resp.text) into the client response body (WR-05): a 404 from the
        # backend stays a 404, everything else is a 502.
        logger.error("Delete failed for key %s: %s", key_id, exc)
        code = 404 if exc.response.status_code == 404 else 502
        raise HTTPException(status_code=code, detail="Failed to delete token")
    except httpx.RequestError:
        # Backend unreachable on list/delete → 502, not an uncaught 500 (#3).
        logger.error("Delete unreachable for key %s", key_id)
        raise HTTPException(status_code=502, detail="LiteLLM backend unreachable")

    return JSONResponse({"status": "deleted", "id": key_id})
