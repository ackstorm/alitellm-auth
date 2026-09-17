# SPDX-License-Identifier: Apache-2.0
"""OAuth authorization server discovery and public key routes."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
import time
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.config import Settings
from app.auth import oauth
from app.litellm_client import ensure_team_and_user
from app.oauth_as.store import Store, create_store
from app.oauth_as.tokens import Signer

router = APIRouter()
logger = logging.getLogger(__name__)

_settings: Settings | None = None
_store: Store | None = None
_signer: Signer | None = None
PENDING_TTL = 600
CODE_TTL = 120


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
        parsed.port  # Accessing the property validates the port syntax and range.
        return parsed.hostname in ("127.0.0.1", "localhost", "::1")
    except ValueError:
        return False


def _redirect_allowed(redirect_uri: str) -> bool:
    parsed = _parsed_redirect(redirect_uri)
    if parsed is None:
        return False
    try:
        _ = parsed.port  # Raises ValueError for malformed or out-of-range ports.
        if (
            parsed.fragment
            or "#" in redirect_uri
            or parsed.username is not None
            or parsed.password is not None
        ):
            return False
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
        return (a.hostname, a.path, a.params, a.query, a.fragment, a.username, a.password) == (
            b.hostname,
            b.path,
            b.params,
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


def _client_redirect(redirect_uri: str, params: dict) -> RedirectResponse:
    sep = "&" if "?" in redirect_uri else "?"
    return RedirectResponse(f"{redirect_uri}{sep}{urlencode(params)}", status_code=302)


def _html_error(status: int, message: str) -> HTMLResponse:
    return HTMLResponse(f"<h1>Authorization failed</h1><p>{message}</p>", status_code=status)


@router.get("/oauth/authorize")
async def authorize(request: Request):
    assert _store is not None and _settings is not None
    q = request.query_params
    client = await _store.get("client", q.get("client_id", ""))
    if client is None:
        return _html_error(400, "unknown client_id")
    redirect_uri = q.get("redirect_uri", "")
    if not any(_redirect_matches(uri, redirect_uri) for uri in client["redirect_uris"]):
        return _html_error(400, "redirect_uri is not registered for this client")

    state = q.get("state")
    scope = q.get("scope", _settings.as_audience)
    if scope != _settings.as_audience:
        params = {"error": "invalid_scope", "error_description": "requested scope is not supported"}
        if state:
            params["state"] = state
        return _client_redirect(redirect_uri, params)
    challenge = q.get("code_challenge", "")
    if (
        q.get("response_type") != "code"
        or q.get("code_challenge_method") != "S256"
        or re.fullmatch(r"[A-Za-z0-9_-]{43}", challenge) is None
    ):
        params = {"error": "invalid_request", "error_description": "response_type=code with PKCE S256 is required"}
        if state:
            params["state"] = state
        return _client_redirect(redirect_uri, params)

    pending_id = secrets.token_urlsafe(24)
    await _store.put("pending", pending_id, {
        "client_id": client["client_id"],
        "redirect_uri": redirect_uri,
        "state": state,
        "code_challenge": q["code_challenge"],
        "scope": scope,
    }, ttl=PENDING_TTL)
    request.session["as_pending"] = pending_id
    # The ingress terminates TLS, so request.url_for may incorrectly report http.
    callback = _settings.app_base_url.rstrip("/") + "/oauth/as-callback"
    return await oauth.oidc.authorize_redirect(request, callback)


@router.get("/oauth/as-callback", name="as_callback")
async def as_callback(request: Request):
    assert _store is not None and _settings is not None
    pending_id = request.session.pop("as_pending", None)
    pending = await _store.pop("pending", pending_id) if pending_id else None
    if pending is None:
        return _html_error(400, "no authorization request is pending — start again from your client")
    try:
        token = await oauth.oidc.authorize_access_token(request)
    except Exception as exc:  # Authlib raises several OAuthError subclasses.
        logger.warning("Dex callback failed: %s", exc)
        return _html_error(400, "the identity provider did not complete the login")
    userinfo = token.get("userinfo") or {}
    email = userinfo.get("email")
    if not email:
        return _html_error(400, "the identity provider returned no email")
    await ensure_team_and_user(email, _settings, name=userinfo.get("name"))
    code = secrets.token_urlsafe(32)
    await _store.put("code", code, {**pending, "sub": email}, ttl=CODE_TTL)
    params = {"code": code}
    if pending.get("state"):
        params["state"] = pending["state"]
    logger.info("Authorization code issued to client %s", pending["client_id"])
    return _client_redirect(pending["redirect_uri"], params)


def _pkce_ok(challenge: str, verifier: str) -> bool:
    if re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier) is None:
        return False
    digest = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return hmac.compare_digest(challenge, digest)


async def _issue(sub: str, client_id: str, scope: str) -> JSONResponse:
    assert _settings is not None and _store is not None and _signer is not None
    ttl = _settings.as_access_ttl_seconds
    access = _signer.issue(
        issuer=_settings.as_issuer,
        audience=_settings.as_audience,
        sub=sub,
        scope=scope,
        client_id=client_id,
        ttl=ttl,
    )
    refresh = secrets.token_urlsafe(32)
    await _store.put(
        "refresh",
        refresh,
        {"sub": sub, "client_id": client_id, "scope": scope},
        ttl=_settings.as_refresh_ttl_seconds,
    )
    return JSONResponse(
        {
            "access_token": access,
            "token_type": "Bearer",
            "expires_in": ttl,
            "refresh_token": refresh,
            "scope": scope,
        },
        headers={"Cache-Control": "no-store", "Pragma": "no-cache"},
    )


@router.post("/oauth/token")
async def token(request: Request) -> JSONResponse:
    assert _store is not None
    form = await request.form()
    grant = form.get("grant_type")
    client_id = str(form.get("client_id", ""))
    if grant == "authorization_code":
        rec = await _store.pop("code", str(form.get("code", "")))
        if (
            rec is None
            or rec["client_id"] != client_id
            or not _redirect_matches(rec["redirect_uri"], str(form.get("redirect_uri", "")))
            or not _pkce_ok(rec["code_challenge"], str(form.get("code_verifier", "")))
        ):
            return _error(400, "invalid_grant")
        return await _issue(rec["sub"], client_id, rec["scope"])
    if grant == "refresh_token":
        presented = str(form.get("refresh_token", ""))
        rec = await _store.pop("refresh", presented)
        if rec is None or rec["client_id"] != client_id:
            return _error(400, "invalid_grant")
        return await _issue(rec["sub"], client_id, rec["scope"])
    return _error(400, "unsupported_grant_type")
