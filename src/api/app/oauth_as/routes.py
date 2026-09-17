# SPDX-License-Identifier: Apache-2.0
"""OAuth authorization server discovery and public key routes."""

from __future__ import annotations

import logging
import secrets
import time
from urllib.parse import urlparse

from fastapi import APIRouter, Request
from starlette.responses import JSONResponse

from app.config import Settings
from app.oauth_as.store import Store, create_store
from app.oauth_as.tokens import Signer

router = APIRouter()
logger = logging.getLogger(__name__)

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


def _parsed_redirect(redirect_uri: str):
    try:
        return urlparse(redirect_uri)
    except ValueError:
        return None


def _is_loopback(redirect_uri: str) -> bool:
    parsed = _parsed_redirect(redirect_uri)
    if parsed is None or parsed.scheme != "http":
        return False
    try:
        return parsed.hostname in ("127.0.0.1", "localhost", "::1")
    except ValueError:
        return False


def _redirect_allowed(redirect_uri: str) -> bool:
    parsed = _parsed_redirect(redirect_uri)
    if parsed is None:
        return False
    try:
        return (parsed.scheme == "https" and bool(parsed.hostname)) or _is_loopback(redirect_uri)
    except ValueError:
        return False


def _redirect_matches(registered: str, presented: str) -> bool:
    """Exact match, except a loopback redirect may change port (RFC 8252 §7.3)."""
    if registered == presented:
        return True
    if not (_is_loopback(registered) and _is_loopback(presented)):
        return False
    a, b = _parsed_redirect(registered), _parsed_redirect(presented)
    if a is None or b is None:
        return False
    try:
        return (a.hostname, a.path, a.query, a.fragment, a.username, a.password) == (
            b.hostname,
            b.path,
            b.query,
            b.fragment,
            b.username,
            b.password,
        )
    except ValueError:
        return False


def _error(status: int, error: str, description: str = "") -> JSONResponse:
    body = {"error": error}
    if description:
        body["error_description"] = description
    return JSONResponse(body, status_code=status, headers={"Cache-Control": "no-store"})


@router.post("/oauth/register")
async def register(request: Request) -> JSONResponse:
    assert _store is not None
    try:
        body = await request.json()
    except (ValueError, TypeError):
        return _error(400, "invalid_client_metadata", "body must be a JSON object")
    if not isinstance(body, dict):
        return _error(400, "invalid_client_metadata", "body must be a JSON object")
    uris = body.get("redirect_uris")
    if (
        not isinstance(uris, list)
        or not uris
        or not all(isinstance(uri, str) and _redirect_allowed(uri) for uri in uris)
    ):
        return _error(400, "invalid_redirect_uri", "redirect_uris must be https or loopback http")
    if body.get("token_endpoint_auth_method", "none") != "none":
        return _error(400, "invalid_client_metadata", "only public clients are registered here")
    client_id = secrets.token_urlsafe(16)
    record = {
        "client_id": client_id,
        "client_id_issued_at": int(time.time()),
        "client_name": str(body.get("client_name", ""))[:200],
        "redirect_uris": uris,
        "token_endpoint_auth_method": "none",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }
    await _store.put("client", client_id, record)
    logger.info("Registered OAuth client %s (%s)", client_id, record["client_name"])
    return JSONResponse(record, status_code=201, headers={"Cache-Control": "no-store"})
