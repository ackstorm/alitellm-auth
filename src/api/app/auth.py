# SPDX-License-Identifier: Apache-2.0
"""OIDC authentication routes.

Sign-in is UI-only. The OIDC flow authenticates the user, eager-creates their
LiteLLM user (idempotent), and redirects to /ui — it NEVER mints a virtual key.
Keys are created explicitly from inside the console (POST /api/session/keys).
``whoami`` (header-authed key -> identity resolver) is the only non-UI endpoint.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from authlib.integrations.starlette_client import OAuth
from authlib.integrations.starlette_client import StarletteIntegration
from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings
from app.litellm_client import (
    ensure_team_and_user,
    get_key_info,
    get_litellm_user,
    LiteLLMUserNotFound,
    strip_bearer_prefix,
)

logger = logging.getLogger(__name__)

router = APIRouter()
oauth = OAuth()  # module-level so tests can patch it


class ConcurrentStateStarletteIntegration(StarletteIntegration):
    """Preserve valid OAuth states when a browser starts overlapping flows.

    Authlib's default Starlette integration clears every state for this client
    whenever it saves a new one. Keep its session binding and expiry markers,
    but prune only expired entries; Authlib still validates and clears each
    callback state through the normal get/clear methods.
    """

    async def set_state_data(self, session, state, data):
        key = f"_state_{self.name}_{state}"
        now = time.time()
        if self.cache:
            await self.cache.set(key, json.dumps({"data": data}), self.expires_in)
            if session is not None:
                session[key] = {"exp": now + self.expires_in}
        elif session is not None:
            session[key] = {"data": data, "exp": now + self.expires_in}
        if session is not None:
            self._clear_session_state(session)


# BaseOAuth reads this when it constructs the registered OIDC client.
oauth.framework_integration_cls = ConcurrentStateStarletteIntegration

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
    api_key = strip_bearer_prefix(x_alitellm_auth_api_key)

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
async def login(request: Request) -> HTMLResponse:
    """Redirect the user to the OIDC provider to sign in.

    Sign-in is UI-only. The callback always eager-creates the LiteLLM user
    (idempotent) and redirects to /ui — it NEVER mints a virtual key. The SPA
    uses this route both for the fresh sign-in CTA and the silent mid-session
    expiry redirect; neither can mint a key (keys are created explicitly via
    POST /api/session/keys inside the console).

    ``callback_url`` is built from ``settings.app_base_url`` (always https), never
    ``request.url_for`` — which would yield http:// behind the TLS gateway and be
    rejected as an unregistered redirect_uri.
    """
    settings: Settings = request.app.state.settings
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


async def _auth_callback_ui(
    email: str, name: str | None, settings: Settings, openwork_handoff: bool = False
) -> RedirectResponse:
    # Eager-create the LiteLLM user on sign-in (no key minted). Dashboard entry
    # makes the user exist immediately so /me is coherent.
    try:
        await ensure_team_and_user(email, settings, name=name)
    except Exception as exc:
        # D-09 graceful degrade — still redirect; /me handles the transient no-user case.
        logger.error("ui: ensure_team_and_user failed for %s: %s", email, exc)
    # A desktop sign-in detoured through Dex: return to the handoff page that
    # started it, not the SPA, or the desktop never receives its grant.
    if openwork_handoff:
        return RedirectResponse(f"{settings.app_base_url.rstrip('/')}/openwork", status_code=302)
    return RedirectResponse(f"{settings.app_base_url}/ui", status_code=302)


@router.get("/api/oauth/callback", name="auth_callback", response_model=None)
async def auth_callback(request: Request) -> HTMLResponse | RedirectResponse:
    """Handle the OIDC provider callback.

    Sign-in is UI-only: after authentication we eager-create the LiteLLM user
    (idempotent) and redirect to /ui. No virtual key is ever minted here — keys
    are created explicitly from inside the console (POST /api/session/keys).
    """
    templates = _templates()

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

    # Stamp the session with non-sensitive identity only. The session cookie is
    # signed but NOT encrypted — NEVER store the access_token / id_token / any sk-.
    request.session["sub"] = user_info.get("sub")
    request.session["email"] = email
    request.session["name"] = name
    request.session["authenticated_at"] = datetime.now(timezone.utc).isoformat()

    # 3. Sign-in is UI-only — eager-create the user and redirect to /ui.
    openwork_handoff = bool(request.session.pop("openwork_handoff", False))
    return await _auth_callback_ui(email, name, settings, openwork_handoff=openwork_handoff)
