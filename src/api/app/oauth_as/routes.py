# SPDX-License-Identifier: Apache-2.0
"""OAuth authorization server discovery and public key routes."""

from __future__ import annotations

from fastapi import APIRouter
from starlette.responses import JSONResponse

from app.config import Settings
from app.oauth_as.store import Store, create_store
from app.oauth_as.tokens import Signer

router = APIRouter()

_settings: Settings | None = None
_store: Store | None = None
_signer: Signer | None = None


def configure_as(
    settings: Settings, *, store: Store | None = None, signer: Signer | None = None
) -> None:
    global _settings, _store, _signer
    _settings = settings
    _store = store or create_store(settings)
    _signer = signer or Signer(settings.as_signing_key_pem)


def authorization_server_metadata(issuer: str, audience: str) -> dict:
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "registration_endpoint": f"{issuer}/oauth/register",
        "jwks_uri": f"{issuer}/oauth/jwks.json",
        "scopes_supported": [audience],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
    }


@router.get("/.well-known/oauth-authorization-server")
async def as_metadata() -> JSONResponse:
    assert _settings is not None
    return JSONResponse(authorization_server_metadata(_settings.as_issuer, _settings.as_audience))


@router.get("/.well-known/oauth-protected-resource")
async def protected_resource() -> JSONResponse:
    """RFC 9728 document for the API resource."""
    assert _settings is not None
    return JSONResponse(
        {
            "resource": _settings.api_public_url.rstrip("/"),
            "authorization_servers": [_settings.as_issuer],
            "scopes_supported": [_settings.as_audience],
            "bearer_methods_supported": ["header"],
        }
    )


@router.get("/oauth/jwks.json")
async def jwks() -> JSONResponse:
    assert _signer is not None
    return JSONResponse(_signer.jwks(), headers={"Cache-Control": "public, max-age=300"})
