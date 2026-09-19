# SPDX-License-Identifier: Apache-2.0
"""OpenWork organization server ("Den") contract.

The OpenWork desktop app, pointed at this deployment, signs in with the Dex
session the user already holds and then receives enforced desktop policy and
the deployment's branding. See docs/plans/2026-09-18-openwork-den.md for the full
contract and the verified protocol traps.

The Den API is served at BOTH /api/den and /openwork/api/den. OpenWork's
Settings input keeps only the origin of the organization server URL
(organization-server-input.ts: `return url.origin`), so a desktop configured
by hand calls <origin>/api/den; a bootstrap file or deep link may still carry
the /openwork path. The handoff page and brand marks live under /openwork only;
the middleware rescues the origin-only sign-in URL (/?desktopAuth=1, which the
gateway 301s to /ui/) by redirecting it there. Only registered when OPENWORK_ENABLED.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timedelta, timezone
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

# Handoff page + brand marks: /openwork only.
router = APIRouter(prefix="/openwork", tags=["openwork"])
# The Den API: included at "" and again at "/openwork" (main.py).
den_router = APIRouter(tags=["openwork"])

# Store partitions. Grants are single-use and short-lived; tokens are the
# desktop's long-lived session credential.
GRANT_KIND = "openwork_grant"
TOKEN_KIND = "openwork_token"

_templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
# src/api/brand/ in the tree, /app/brand in the image (Dockerfile COPY). Not
# under /public: that is a projected volume at runtime and would hide files.
_BRAND_DIR = Path(__file__).parent.parent / "brand"
_BRAND_ASSETS = {"logo.svg": "openwork-logo.svg", "icon.svg": "openwork-icon.svg"}

_DEN_PREFIXES = ("/api/den", "/openwork/api/den")
# Where an origin-only sign-in URL lands: the desktop opens /?desktopAuth=1 and
# the gateway 301s / to /ui/, query intact.
_HANDOFF_RESCUE_PATHS = ("/", "/ui", "/ui/")
_ALLOWED_HEADERS = (
    "authorization,content-type,accept,"
    "x-organization-id,x-openwork-org-id,x-openwork-legacy-org-id"
)


class DenCorsMiddleware(BaseHTTPMiddleware):
    """Reflect the caller's origin for Den routes only; rescue the sign-in URL.

    The desktop is not a browser page on our origin, and it sends
    credentials: "include", so "*" is not usable. Scoped to the Den prefix so
    the cookie-authenticated SPA API keeps its same-origin-only posture.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in _HANDOFF_RESCUE_PATHS and request.query_params.get("desktopAuth") == "1":
            return RedirectResponse(f"/openwork?{request.url.query}", status_code=302)
        if not path.startswith(_DEN_PREFIXES):
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


@den_router.get("/api/den/v1/me", response_model=None)
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


@den_router.post("/api/den/v1/auth/desktop-handoff/exchange", response_model=None)
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
            "connectEnabled": True,
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
            "logo_url": settings.openwork_brand_logo_url,
            "email": email,
            "deep_link": deep_link,
            "ttl_minutes": settings.openwork_grant_ttl_seconds // 60,
        },
    )


@den_router.get("/api/den/v1/me/orgs", response_model=None)
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


@den_router.post("/api/den/v1/me/active-organization", response_model=None)
async def den_set_active_org(request: Request) -> JSONResponse:
    """Single-org deployment: acknowledge the choice, there is nothing to switch."""
    session = await require_den_token(request)
    if isinstance(session, JSONResponse):
        return session
    org = _organization(request.app.state.settings)
    return JSONResponse({"activeOrgId": org["id"], "activeOrgSlug": org["slug"]})


@den_router.get("/api/den/v1/resources", response_model=None)
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


@den_router.get("/api/den/v1/me/desktop-config", response_model=None)
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
        # provider OpenCode loads from its own config, and
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
        # Served below (Cloud MCP); false only relabels Settings → Connect and
        # tells the agent not to suggest signing in — it never stops the mint.
        "connectEnabled": True,
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


@den_router.post("/api/den/api/auth/sign-out", response_model=None)
async def den_sign_out(request: Request) -> JSONResponse:
    """Revoke the desktop's session token. Idempotent: an unknown token is fine."""
    header = request.headers.get("authorization") or ""
    token = header[7:].strip() if header[:7].lower() == "bearer " else ""
    if token:
        await _store(request).pop(TOKEN_KIND, token)
    return JSONResponse({})


@den_router.post("/api/den/v1/telemetry/ingest", response_model=None)
async def den_telemetry(request: Request) -> JSONResponse:
    """Accept and discard. We do not forward desktop telemetry anywhere."""
    session = await require_den_token(request)
    if isinstance(session, JSONResponse):
        return session
    return JSONResponse({})


# --- Cloud MCP (OpenWork Connect) ---------------------------------------------
# The desktop mints a token here whenever it is signed in (connectEnabled does
# NOT gate that), registers <resource>/agent as the `openwork-cloud` remote MCP
# in every workspace and probes it. Health turns green only when tools/list
# carries search_capabilities + execute_capability. We ship an EMPTY catalog:
# enough for a green badge and the substrate for pushing skills later.
# Contract + verified traps: docs/references/openwork-connect.md §2.
MCP_TOKEN_KIND = "openwork_mcp_token"
MCP_TOKEN_TTL_SECONDS = 7 * 86400  # the hosted Den's lifetime; the desktop re-mints 24h early
_MCP_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26")
_MCP_TOOLS = [
    {
        "name": "search_capabilities",
        "description": "Search this organization's Connect catalog. It is currently empty.",
        "annotations": {"readOnlyHint": True},
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
                "type": {"type": "string"},
                "intent": {"type": "string"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "execute_capability",
        "description": "Run a capability by the exact name search_capabilities returned.",
        "annotations": {"destructiveHint": True},
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "body": {"type": "object", "additionalProperties": True},
                "path": {"type": "object", "additionalProperties": True},
                "query": {"type": "object", "additionalProperties": True},
            },
            "required": ["name"],
        },
    },
]
# Read by the local server on every prompt; strict v1 shape (connect-skill-catalog.ts).
_MCP_RESOURCES: dict[str, str] = {
    "skill://index.json": json.dumps(
        {"$schema": "https://schemas.agentskills.io/discovery/0.2.0/schema.json", "skills": []}
    ),
    "automation://index.json": json.dumps(
        {"fetchedAt": 0, "total": 0, "omitted": 0, "automations": []}
    ),
}


def mcp_resource(settings: Settings) -> str:
    """Token `resource`; the desktop appends /agent and requires the /mcp suffix."""
    return f"{den_api_base(settings)}/mcp"


@den_router.post("/api/den/v1/mcp/token", response_model=None)
async def den_mcp_token(request: Request) -> JSONResponse:
    session = await require_den_token(request)
    if isinstance(session, JSONResponse):
        return session
    settings: Settings = request.app.state.settings
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(seconds=MCP_TOKEN_TTL_SECONDS)
    await _store(request).put(
        MCP_TOKEN_KIND, token, {"email": session["email"]}, ttl=MCP_TOKEN_TTL_SECONDS
    )
    return JSONResponse(
        {
            "token": token,
            "expiresAt": expires.isoformat().replace("+00:00", "Z"),
            # Must equal the active org id or health fails cloud_token_org_mismatch.
            "organizationId": _organization(settings)["id"],
            "scopes": ["mcp:read", "mcp:write"],
            "resource": mcp_resource(settings),
        }
    )


def _mcp_reply(message: Any) -> dict[str, Any] | None:
    """One JSON-RPC message in, one reply out; None for a notification."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return {
            "jsonrpc": "2.0",
            "id": None,
            "error": {"code": -32600, "message": "Invalid request"},
        }
    method, params, mid = message.get("method"), message.get("params") or {}, message.get("id")
    if "id" not in message:
        return None  # notification (e.g. notifications/initialized)

    def ok(result: Any) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def err(code: int, text: str) -> dict[str, Any]:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": text}}

    if method == "initialize":
        requested = params.get("protocolVersion")
        return ok(
            {
                "protocolVersion": requested
                if requested in _MCP_PROTOCOL_VERSIONS
                else _MCP_PROTOCOL_VERSIONS[0],
                "capabilities": {
                    "tools": {"listChanged": False},
                    "resources": {"listChanged": False},
                },
                "serverInfo": {"name": "alitellm-auth-den", "version": "1"},
                "instructions": (
                    "This organization's Connect catalog is empty: search_capabilities "
                    "returns no matches and there are no connected services, remote "
                    "skills, workflows or automations. Do not suggest connecting services."
                ),
            }
        )
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": _MCP_TOOLS})
    if method == "tools/call":
        name = params.get("name")
        if name == "search_capabilities":
            payload = {"matches": [], "hint": "The Connect catalog is empty."}
            return ok(
                {
                    "content": [{"type": "text", "text": json.dumps(payload)}],
                    "structuredContent": payload,
                    "isError": False,
                }
            )
        if name == "execute_capability":
            return ok(
                {
                    "content": [
                        {
                            "type": "text",
                            "text": json.dumps(
                                {
                                    "error": "unknown_capability",
                                    "name": (params.get("arguments") or {}).get("name"),
                                }
                            ),
                        }
                    ],
                    "isError": True,
                }
            )
        return err(-32602, f"Unknown tool: {name}")
    if method == "resources/list":
        return ok(
            {
                "resources": [
                    {"uri": uri, "name": uri, "mimeType": "application/json"}
                    for uri in _MCP_RESOURCES
                ]
            }
        )
    if method == "resources/read":
        uri = params.get("uri") or ""
        text = _MCP_RESOURCES.get(uri)
        if text is None:
            return err(-32002, f"Resource not found: {uri}")
        # The reader matches on uri, so it must come back verbatim.
        return ok({"contents": [{"uri": uri, "mimeType": "application/json", "text": text}]})
    if method == "prompts/list":
        return ok({"prompts": []})
    return err(-32601, f"Method not found: {method}")


@den_router.api_route("/api/den/mcp/agent", methods=["GET", "POST", "DELETE"], response_model=None)
async def den_mcp_agent(request: Request) -> Response:
    """Streamable-HTTP MCP endpoint the engine registers as `openwork-cloud`.

    Traps (connect-mcp-transport.ts): a notification batch gets 202 with an
    EMPTY body; GET is answered 405 like the hosted Den (a 204 confuses the
    SDK); a 401 makes the desktop re-mint silently.
    """
    header = request.headers.get("authorization") or ""
    token = header[7:].strip() if header[:7].lower() == "bearer " else ""
    if not token or not await _store(request).get(MCP_TOKEN_KIND, token):
        return den_error(401, "invalid_mcp_token", "Missing or unknown MCP token.")
    if request.method == "GET":
        return Response(status_code=405, headers={"Allow": "POST, DELETE"})
    if request.method == "DELETE":
        return Response(status_code=204)  # nothing is kept per session
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        )
    messages = body if isinstance(body, list) else [body]
    replies = [r for r in (_mcp_reply(m) for m in messages) if r is not None]
    if not replies:
        return Response(status_code=202)
    return JSONResponse(replies if isinstance(body, list) else replies[0])


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
@den_router.api_route(
    "/api/den/v1/{resource:path}", methods=["GET", "POST", "PUT", "DELETE"], response_model=None
)
async def den_empty_catalog(resource: str, request: Request) -> JSONResponse:
    """Catch-all for catalogs this deployment does not populate.

    An unknown path (any method) returns the Den 404 envelope rather than
    FastAPI's 404/405 {"detail"}, which keeps the desktop's error banner
    readable while we find out what it wanted.
    """
    session = await require_den_token(request)
    if isinstance(session, JSONResponse):
        return session
    payload = _EMPTY_GET.get(resource.rstrip("/")) if request.method == "GET" else None
    if payload is None:
        return den_error(404, "not_implemented", f"No handler for {request.method} /v1/{resource}")
    return JSONResponse(payload)
