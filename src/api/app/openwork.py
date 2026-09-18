# SPDX-License-Identifier: Apache-2.0
"""OpenWork organization server ("Den") contract.

The OpenWork desktop app, pointed at this deployment, signs in with the Dex
session the user already holds and then receives enforced desktop policy and
ACKstorm branding. See docs/plans/2026-09-18-openwork-den.md for the full
contract and the verified protocol traps.

Mounted at /openwork; the desktop derives its API base by appending /api/den.
Only registered when OPENWORK_ENABLED.
"""

from __future__ import annotations

import hashlib
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.config import Settings
from app.oauth_as.store import Store

router = APIRouter(prefix="/openwork", tags=["openwork"])

# Store partitions. Grants are single-use and short-lived; tokens are the
# desktop's long-lived session credential.
GRANT_KIND = "openwork_grant"
TOKEN_KIND = "openwork_token"

_templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
# src/api/brand/ in the tree, /app/brand in the image (Dockerfile COPY). Not
# under /public: that is a projected volume at runtime and would hide files.
_BRAND_DIR = Path(__file__).parent.parent / "brand"
_BRAND_ASSETS = {"logo.svg": "openwork-logo.svg", "icon.svg": "openwork-icon.svg"}

_DEN_PREFIX = "/openwork/api/den"
_ALLOWED_HEADERS = (
    "authorization,content-type,accept,"
    "x-organization-id,x-openwork-org-id,x-openwork-legacy-org-id"
)


class DenCorsMiddleware(BaseHTTPMiddleware):
    """Reflect the caller's origin for Den routes only.

    The desktop is not a browser page on our origin, and it sends
    credentials: "include", so "*" is not usable. Scoped to the Den prefix so
    the cookie-authenticated SPA API keeps its same-origin-only posture.
    """

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith(_DEN_PREFIX):
            return await call_next(request)

        origin = request.headers.get("origin")
        if request.method == "OPTIONS":
            response = Response(status_code=204)
        else:
            response = await call_next(request)

        if origin:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Credentials"] = "true"
            response.headers["Vary"] = "Origin"
            response.headers["Access-Control-Allow-Methods"] = "GET,POST,DELETE,OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = _ALLOWED_HEADERS
        return response


def den_error(status: int, error: str, message: str) -> JSONResponse:
    """The error envelope the desktop understands.

    OpenWork's client reads payload.error and payload.message (den.ts:2941).
    FastAPI's default {"detail": ...} collapses into a generic failure string
    with no actionable code, so every error path here returns this instead.
    """
    return JSONResponse(status_code=status, content={"error": error, "message": message})


def _store(request: Request) -> Store:
    # One store per app, created in create_app(): create_store() builds a fresh
    # MemoryStore each call, so a per-request store would forget every grant.
    return request.app.state.openwork_store


def user_id_for(email: str) -> str:
    """Stable, opaque per-user id. The desktop only needs it to be a string."""
    return "user_" + hashlib.sha256(email.encode("utf-8")).hexdigest()[:24]


async def require_den_token(request: Request) -> dict[str, Any] | JSONResponse:
    """Resolve the desktop's bearer token, or return the Den 401 envelope.

    Returns a JSONResponse on failure rather than raising, so handlers keep the
    error shape; every caller must check with isinstance().
    """
    header = request.headers.get("authorization") or ""
    token = header[7:].strip() if header[:7].lower() == "bearer " else ""
    if not token:
        return den_error(401, "unauthorized", "This request needs a session token.")
    row = await _store(request).get(TOKEN_KIND, token)
    if not row:
        return den_error(401, "unauthorized", "This session token is unknown or expired.")
    return row


@router.get("/api/den/v1/me", response_model=None)
async def den_me(request: Request) -> JSONResponse:
    """The signed-in user, as the desktop's session check expects."""
    session = await require_den_token(request)
    if isinstance(session, JSONResponse):
        return session
    return JSONResponse(
        {
            "user": {
                "id": user_id_for(session["email"]),
                "email": session["email"],
                "name": session.get("name") or session["email"],
            }
        }
    )


def _organization(settings: Settings) -> dict[str, str]:
    return {
        "id": "organization_"
        + hashlib.sha256(settings.openwork_org_slug.encode()).hexdigest()[:16],
        "slug": settings.openwork_org_slug,
        "name": settings.openwork_org_name,
    }


@router.post("/api/den/v1/auth/desktop-handoff/exchange", response_model=None)
async def desktop_handoff_exchange(request: Request) -> JSONResponse:
    """Trade a one-time grant for the desktop's session token.

    Public by design: the grant IS the credential, which is why it is minted
    only for an already-signed-in browser session, expires in minutes, and is
    consumed atomically here (store.pop) so a captured value cannot be replayed.
    """
    settings: Settings = request.app.state.settings
    try:
        body = await request.json()
    except Exception:
        body = {}
    grant = (body.get("grant") or "").strip() if isinstance(body, dict) else ""
    if not grant:
        return den_error(400, "invalid_request", "A grant is required.")

    # pop is the single-use guarantee: a second exchange finds nothing.
    claimed = await _store(request).pop(GRANT_KIND, grant)
    if not claimed:
        return den_error(
            404,
            "grant_not_found",
            "This desktop sign-in link is missing, expired, or already used.",
        )

    token = secrets.token_urlsafe(32)
    await _store(request).put(
        TOKEN_KIND,
        token,
        {"email": claimed["email"], "name": claimed.get("name") or claimed["email"]},
        ttl=settings.openwork_token_ttl_seconds,
    )
    return JSONResponse(
        {
            "token": token,
            "user": {
                "id": user_id_for(claimed["email"]),
                "email": claimed["email"],
                "name": claimed.get("name") or claimed["email"],
            },
            "organization": _organization(settings),
            # Connect (cloud MCP) is not served; the plan's Phase 6 was skipped.
            "connectEnabled": False,
        }
    )


def den_api_base(settings: Settings) -> str:
    """The API base the desktop must use — what we hand it in the deep link."""
    return f"{settings.app_base_url.rstrip('/')}/openwork/api/den"


@router.get("", response_model=None)
@router.get("/", response_model=None)
async def handoff_page(request: Request):
    """Mint a one-time grant for the signed-in user and show the handoff link.

    The desktop opens this URL with ?desktopAuth=1. It never reads our response
    body: it waits for the openwork:// deep link, or for the user to paste the
    grant. So this page only has to put the value in front of the human.
    """
    settings: Settings = request.app.state.settings
    email = request.session.get("email")
    if not email:
        # Remember why we are going to Dex, so the callback returns here
        # instead of the SPA (auth.py::_auth_callback_ui).
        request.session["openwork_handoff"] = True
        return RedirectResponse(
            f"{settings.app_base_url.rstrip('/')}/api/oauth/login", status_code=302
        )

    request.session.pop("openwork_handoff", None)
    grant = secrets.token_urlsafe(24)
    await _store(request).put(
        GRANT_KIND,
        grant,
        {"email": email, "name": request.session.get("name") or email},
        ttl=settings.openwork_grant_ttl_seconds,
    )
    deep_link = "openwork://den-auth?" + urlencode(
        {"grant": grant, "denBaseUrl": den_api_base(settings)}
    )
    return _templates.TemplateResponse(
        request,
        "openwork_handoff.html",
        {
            "brand": settings.openwork_brand_app_name,
            "email": email,
            "deep_link": deep_link,
            "ttl_minutes": settings.openwork_grant_ttl_seconds // 60,
        },
    )


@router.get("/api/den/v1/me/orgs", response_model=None)
async def den_orgs(request: Request) -> JSONResponse:
    session = await require_den_token(request)
    if isinstance(session, JSONResponse):
        return session
    settings: Settings = request.app.state.settings
    org = _organization(settings)
    return JSONResponse(
        {
            "orgs": [{**org, "role": "member"}],
            "activeOrgId": org["id"],
            "activeOrgSlug": org["slug"],
        }
    )


@router.post("/api/den/v1/me/active-organization", response_model=None)
async def den_set_active_org(request: Request) -> JSONResponse:
    """Single-org deployment: acknowledge the choice, there is nothing to switch."""
    session = await require_den_token(request)
    if isinstance(session, JSONResponse):
        return session
    org = _organization(request.app.state.settings)
    return JSONResponse({"activeOrgId": org["id"], "activeOrgSlug": org["slug"]})


@router.get("/api/den/v1/resources", response_model=None)
async def den_resources(request: Request) -> JSONResponse:
    """Change-detection snapshot.

    The desktop diffs these timestamps against what it has installed, so the
    values must be byte-identical while nothing has changed. We ship no
    resources, so both maps stay empty and the question never arises — but keep
    that property if anything is ever added here.
    """
    session = await require_den_token(request)
    if isinstance(session, JSONResponse):
        return session
    settings: Settings = request.app.state.settings
    return JSONResponse(
        {
            "organizationId": _organization(settings)["id"],
            "orgMemberId": "orgmember_" + user_id_for(session["email"])[5:],
            "teamIds": [],
            "resources": {"llmProviders": {}, "marketplaces": []},
        }
    )


@router.get("/api/den/v1/me/desktop-config", response_model=None)
async def den_desktop_config(request: Request) -> JSONResponse:
    """Branding and enforced policy for this member's desktop.

    OpenWork's local server persists this and then denies engine and HTTP
    actions with 403 organization_policy_denied, so these are real limits, not
    UI preferences. Schema: packages/types/src/den/desktop-policies.ts:330.
    """
    session = await require_den_token(request)
    if isinstance(session, JSONResponse):
        return session
    settings: Settings = request.app.state.settings

    payload: dict[str, Any] = {
        "brandAppName": settings.openwork_brand_app_name,
        "brandAccentColor": settings.openwork_accent_color,
        # Deliberately permissive: allowCustomProviders=False would hide the
        # ackstorm provider OpenCode loads from its own config, and
        # allowManageExtensions=False would block installing the auth plugin.
        "allowCustomProviders": True,
        "allowManageExtensions": True,
        "allowControlSettings": True,
        "allowBuiltInExtensions": True,
        "allowMultipleWorkspaces": True,
        "allowZenModel": True,
        "allowAlphaUpdates": False,
        "showWelcomePage": False,
        "execution": {
            "commands": "allow",
            # NOTE: a non-empty list disables interactive terminals and saved
            # commands outright (managed-policy-rules.ts:77-78).
            "blockedCommands": list(settings.openwork_blocked_commands),
            "blockBrowserUploads": settings.openwork_block_browser_uploads,
        },
        "automationsEnabled": False,
        "dashboardEnabled": False,
        "connectEnabled": False,
    }
    # A non-URL value is dropped by the client normalizer, so omit rather than
    # send an empty string.
    if settings.openwork_brand_logo_url:
        payload["brandLogoUrl"] = settings.openwork_brand_logo_url
    if settings.openwork_brand_icon_url:
        payload["brandIconUrl"] = settings.openwork_brand_icon_url
    return JSONResponse(payload)


@router.get("/brand/{name}", response_model=None)
async def brand_asset(name: str):
    """Serve the two published brand marks. Public: they are not secrets.

    An explicit allow-list, not a path join, so this can never read outside
    the brand directory.
    """
    filename = _BRAND_ASSETS.get(name)
    if not filename:
        return den_error(404, "not_found", f"No brand asset {name}")
    return FileResponse(_BRAND_DIR / filename, media_type="image/svg+xml")


@router.post("/api/den/api/auth/sign-out", response_model=None)
async def den_sign_out(request: Request) -> JSONResponse:
    """Revoke the desktop's session token. Idempotent: an unknown token is fine."""
    header = request.headers.get("authorization") or ""
    token = header[7:].strip() if header[:7].lower() == "bearer " else ""
    if token:
        await _store(request).pop(TOKEN_KIND, token)
    return JSONResponse({})


@router.post("/api/den/v1/telemetry/ingest", response_model=None)
async def den_telemetry(request: Request) -> JSONResponse:
    """Accept and discard. We do not forward desktop telemetry anywhere."""
    session = await require_den_token(request)
    if isinstance(session, JSONResponse):
        return session
    return JSONResponse({})


# Empty-but-valid payloads for an organization that ships no resources. The key
# names are what each client parser looks for (den.ts getDenOrgLlmProviders,
# getOrgMarketplaces, getMeLibraryPlugins, getDenExternalMcpConnections, ...);
# a wrong name parses as "no data" and hides real breakage.
_EMPTY_GET: dict[str, dict[str, Any]] = {
    "llm-providers": {"llmProviders": []},
    "inference-providers": {"inferenceProviders": []},
    "marketplaces": {"items": []},
    "resources/marketplace-capabilities": {"items": []},
    "me/library": {"items": []},
    "me/dashboards": {"items": []},
    "mcp-connections": {"connections": []},
    "mcp-connections/presets": {"presets": []},
    "apps": {"enabled": False, "sharingEnabled": False, "items": []},
    "automations": {"items": [], "nextCursor": None},
    "cloud-automations": {"items": [], "nextCursor": None},
    "plugins": {"items": []},
    "inference/analytics/settings": {
        "available": False,
        "subscribed": False,
        "modelsEnabled": False,
        "enabled": False,
        "consentedAt": None,
        "consentVersion": None,
        "exportEnabled": False,
        "langfuseHost": None,
        "langfuseConfigured": False,
    },
}


# Declared LAST: FastAPI matches in registration order, so every explicit
# /api/den/v1/... route above wins over this catch-all.
@router.get("/api/den/v1/{resource:path}", response_model=None)
async def den_empty_catalog(resource: str, request: Request) -> JSONResponse:
    """Catch-all for catalogs this deployment does not populate.

    An unknown path returns the Den 404 envelope rather than FastAPI's, which
    keeps the desktop's error banner readable while we find out what it wanted.
    """
    session = await require_den_token(request)
    if isinstance(session, JSONResponse):
        return session
    payload = _EMPTY_GET.get(resource.rstrip("/"))
    if payload is None:
        return den_error(404, "not_implemented", f"No handler for /v1/{resource}")
    return JSONResponse(payload)
