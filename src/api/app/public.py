# SPDX-License-Identifier: Apache-2.0
"""Public, unauthenticated presentation-config endpoint.

`GET /api/config` returns ONLY non-secret presentation config (brand/tagline/
links/providers/public_host) sourced from pydantic Settings at request time so a
deployment can re-brand without a rebuild (D-01). The SPA fetches this once at
boot and threads it into both the cold login and the authed shell.

Security (threat T-09-18): this handler NEVER reads or returns a key, user data,
or any secret-bearing field (litellm_master_key/session_secret_key/
oauth_client_secret). It deliberately OMITS Depends(require_session_user) (it is
public) and any same-origin guard (read-only GET, same exemption as
session_stats).
"""

from __future__ import annotations

from urllib.parse import urlparse, urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from app.config import Settings

router = APIRouter(tags=["public"])

# Static BACKED-BY provider chip labels (D-14) — not derived from any secret.
_PROVIDERS = [{"label": "Google"}, {"label": "Dex"}, {"label": "OIDC"}]


@router.get("/api/config", response_model=None)
async def public_config(request: Request) -> JSONResponse:
    """Return non-secret presentation config (public, unauthenticated)."""
    settings: Settings = request.app.state.settings

    # Derive the host label from api_public_url; fall back to the raw value when
    # urlparse cannot extract a hostname (e.g. a bare host with no scheme).
    public_host = urlparse(settings.api_public_url).hostname or settings.api_public_url

    # Real-links-only rule (D-02/D-03): a link key is present ONLY when its target
    # is non-null and non-empty; absent targets are omitted entirely (no dead anchor).
    link_sources = {
        "docs": settings.link_docs,
        "status": settings.link_status,
        "support": settings.link_support,
        "privacy": settings.link_privacy,
        "terms": settings.link_terms,
    }
    links = {key: value for key, value in link_sources.items() if value}

    payload = {
        "brand": settings.brand,
        "brand_short": settings.brand_short,
        "provider_name": settings.provider_name,
        "tagline": settings.tagline,
        "accent_segment": settings.accent_segment,
        "public_host": public_host,
        # Explicit hosted-chat URL; "" lets the SPA derive chat.<domain> from the
        # api host (deriveSubdomainUrl). Set CHAT_PUBLIC_URL to override.
        "chat_public_url": settings.chat_public_url,
        "providers": _PROVIDERS,
        "links": links,
    }
    return JSONResponse(payload)


def _backend_options(api_public_url: str, provider_name: str) -> dict[str, str]:
    """Where the OpenCode plugin's backend is: `api` for OAuth discovery, `platform`
    (the origin serving /clients/*) for its config, `provider` = PROVIDER_NAME."""
    base = api_public_url.rstrip("/")
    parts = urlsplit(base)
    return {
        "api": f"{base}/v1",
        "platform": f"{parts.scheme}://{parts.netloc}",
        "provider": provider_name,
    }


@router.get("/.well-known/opencode", response_model=None)
async def opencode_wellknown(request: Request) -> Response:
    """OpenCode well-known manifest: `opencode auth login <this origin>` installs
    the SSO plugin with this deployment's options (engines v1 and v2).

    Public data only. `auth` is mandatory for OpenCode; the plugin does not use
    the credential its command yields, so any portable command will do.
    """
    settings: Settings = request.app.state.settings
    if not settings.api_public_url:
        raise HTTPException(status_code=404)
    options = _backend_options(settings.api_public_url, settings.provider_name)
    return JSONResponse(
        {
            "auth": {"command": ["opencode", "--version"], "env": ""},
            "config": {"plugin": [[settings.opencode_plugin_spec, options]]},
        }
    )
