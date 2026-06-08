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

from urllib.parse import urlparse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

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
        "tagline": settings.tagline,
        "accent_segment": settings.accent_segment,
        "public_host": public_host,
        # Explicit hosted-chat URL; "" lets the SPA derive chat.<domain> from the
        # api host (deriveSubdomainUrl). Set CHAT_PUBLIC_URL to override.
        "chat_public_url": settings.chat_public_url,
        "provider_label": settings.provider_label,
        "providers": _PROVIDERS,
        "links": links,
    }
    return JSONResponse(payload)
