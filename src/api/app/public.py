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

import functools
import gzip
import io
import json
import tarfile
from pathlib import Path
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


# Baked by the Dockerfile from clients/opencode. A route rather than a file under
# /public: that directory is a projected volume at runtime and hides image files.
_OPENCODE_PLUGIN = Path("clients/opencode-auth.tgz")


@functools.cache
def _plugin_tgz(api_public_url: str, provider_name: str) -> bytes:
    """The baked plugin tarball plus package/platform.json for this deployment.

    platform.json tells the product-neutral plugin where its backend is:
    `api` for OAuth discovery and the fallback provider, `platform` (the origin
    serving /clients/*) for its config, `provider`: the OpenCode provider id
    (PROVIDER_NAME). Deterministic: baked members keep their metadata,
    platform.json gets mtime 0 and gzip mtime 0, so every replica and restart
    serves the same bytes. No API_PUBLIC_URL → the baked file as is.
    """
    baked = _OPENCODE_PLUGIN.read_bytes()
    base = api_public_url.rstrip("/")
    if not base:
        return baked
    parts = urlsplit(base)
    doc = json.dumps(
        {
            "api": f"{base}/v1",
            "platform": f"{parts.scheme}://{parts.netloc}",
            "provider": provider_name,
        },
        sort_keys=True,
    ).encode()
    out = io.BytesIO()
    with (
        tarfile.open(fileobj=io.BytesIO(baked), mode="r:gz") as src,
        gzip.GzipFile(fileobj=out, mode="wb", mtime=0) as gz,
        tarfile.open(fileobj=gz, mode="w") as dst,
    ):
        for member in src.getmembers():
            if member.name != "package/platform.json":
                dst.addfile(member, src.extractfile(member) if member.isfile() else None)
        info = tarfile.TarInfo("package/platform.json")
        info.size, info.mode, info.mtime = len(doc), 0o644, 0
        dst.addfile(info, io.BytesIO(doc))
    return out.getvalue()


# /public/opencode-auth is the original install URL, saved in users' opencode.json
# by `opencode plugin <url> -g`: a PERMANENT alias, never remove it.
@router.get("/clients/opencode/plugin", response_model=None)
@router.get("/public/opencode-auth", response_model=None)
async def opencode_plugin(request: Request) -> Response:
    """The OpenCode auth plugin as an npm tarball: `opencode plugin <this URL> -g`."""
    if not _OPENCODE_PLUGIN.is_file():
        raise HTTPException(status_code=404)
    settings: Settings = request.app.state.settings
    body = _plugin_tgz(settings.api_public_url, settings.provider_name)
    return Response(
        body,
        media_type="application/gzip",
        headers={"Content-Disposition": 'attachment; filename="opencode-auth.tgz"'},
    )
