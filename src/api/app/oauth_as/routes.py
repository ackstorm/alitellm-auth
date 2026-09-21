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

import httpx
from fastapi import APIRouter, Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse

from app.config import Settings
from app.auth import oauth
from app.litellm_client import LiteLLMUserNotFound, ensure_team_and_user, get_litellm_user
from app.oauth_as.grants import Grants, create_grants
from app.oauth_as.store import Store, create_store
from app.oauth_as.tokens import Signer

router = APIRouter()
logger = logging.getLogger(__name__)

_settings: Settings | None = None
_store: Store | None = None
_signer: Signer | None = None
_grants: Grants | None = None
CLIENT_TTL = 90 * 86400  # an unused client re-registers after 90 days
PENDING_TTL = 600
CODE_TTL = 120
CHAIN_TTL = 600
HINT_TTL = 600  # the login_hint handed to a broker; one chain step, not a session
# offline_access: Dex hands back a refresh token that every refresh of OURS
# replays at Dex first, so a user disabled at the identity provider is out at
# the next refresh, not after AS_REFRESH_TTL_SECONDS. Requested only here, not
# by the console login: Dex keeps ONE refresh token per (user, client) and
# replaces it whenever a login asks for offline_access.
DEX_SCOPE = "openid email profile offline_access"
DEXRT = "dexrt"  # store kind: the user's Dex refresh token, keyed by email


def configure_as(
    settings: Settings,
    *,
    store: Store | None = None,
    signer: Signer | None = None,
    grants: Grants | None = None,
) -> None:
    global _settings, _store, _signer, _grants
    _settings = settings
    _store = store or create_store(settings)
    _signer = signer or Signer(settings.as_signing_key_pem)
    _grants = grants or create_grants(settings)


def authorization_server_metadata(issuer: str, audience: str, services: list[str] = ()) -> dict:
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/oauth/authorize",
        "token_endpoint": f"{issuer}/oauth/token",
        "registration_endpoint": f"{issuer}/oauth/register",
        "jwks_uri": f"{issuer}/oauth/jwks.json",
        "scopes_supported": [audience, *services],
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code", "refresh_token"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["none"],
        # RFC 9207: every authorization response carries iss (Claude Code checks).
        "authorization_response_iss_parameter_supported": True,
    }


@router.get("/.well-known/oauth-authorization-server")
async def as_metadata() -> JSONResponse:
    assert _settings is not None
    return JSONResponse(
        authorization_server_metadata(
            _settings.as_issuer, _settings.as_audience, list(_settings.services)
        )
    )


@router.get("/.well-known/oauth-protected-resource")
@router.get("/.well-known/oauth-protected-resource/{suffix:path}")
async def protected_resource(suffix: str = "") -> JSONResponse:
    """RFC 9728 for the API and for every MCP path under it. Served on the
    platform host and, through a gitops route prefix, at the same path on the
    API host — where a compliant client checks `resource` against the URL it
    dialled. We compose every one of these; LiteLLM composes none."""
    assert _settings is not None
    resource = _settings.api_public_url.rstrip("/")
    scopes = [_settings.as_audience]
    suffix = suffix.strip("/")
    if suffix:
        resource += "/" + suffix
        head, _, svc = suffix.partition("/")
        svc = svc.split("/", 1)[0]
        if head == "mcp" and svc in _settings.services:
            scopes.append(svc)
    return JSONResponse(
        {
            "resource": resource,
            "authorization_servers": [_settings.as_issuer],
            "scopes_supported": scopes,
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
    await _store.put("client", client_id, record, ttl=CLIENT_TTL)
    logger.info("Registered OAuth client %s (%s)", client_id, record["client_name"])
    return JSONResponse(record, status_code=201, headers={"Cache-Control": "no-store"})


def _client_redirect(redirect_uri: str, params: dict) -> RedirectResponse:
    """Back to the client. Every response, code or error, names the issuer (RFC 9207)."""
    assert _settings is not None
    sep = "&" if "?" in redirect_uri else "?"
    query = urlencode({**params, "iss": _settings.as_issuer})
    return RedirectResponse(f"{redirect_uri}{sep}{query}", status_code=302)


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
    requested = (q.get("scope") or _settings.as_audience).split()
    unknown = [s for s in requested if s != _settings.as_audience and s not in _settings.services]
    if unknown:
        params = {
            "error": "invalid_scope",
            "error_description": f"unknown scope: {' '.join(unknown)}",
        }
        if state:
            params["state"] = state
        return _client_redirect(redirect_uri, params)
    challenge = q.get("code_challenge", "")
    if (
        q.get("response_type") != "code"
        or q.get("code_challenge_method") != "S256"
        or re.fullmatch(r"[A-Za-z0-9_-]{43}", challenge) is None
    ):
        params = {
            "error": "invalid_request",
            "error_description": "response_type=code with PKCE S256 is required",
        }
        if state:
            params["state"] = state
        return _client_redirect(redirect_uri, params)

    await _store.put("client", client["client_id"], client, ttl=CLIENT_TTL)
    pending_id = secrets.token_urlsafe(24)
    await _store.put(
        "pending",
        pending_id,
        {
            "client_id": client["client_id"],
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": q["code_challenge"],
            "scopes": requested,
        },
        ttl=PENDING_TTL,
    )
    # The ingress terminates TLS, so request.url_for may incorrectly report http.
    callback = _settings.app_base_url.rstrip("/") + "/oauth/as-callback"
    # Each in-flight request has its own state; Authlib tracks OAuth state per ID.
    return await oauth.oidc.authorize_redirect(request, callback, state=pending_id, scope=DEX_SCOPE)


@router.get("/oauth/as-callback", name="as_callback")
async def as_callback(request: Request):
    assert _store is not None and _settings is not None and _grants is not None
    pending_id = request.query_params.get("state", "")
    pending = await _store.pop("pending", pending_id) if pending_id else None
    if pending is None:
        return _html_error(
            400, "no authorization request is pending — start again from your client"
        )
    try:
        token = await oauth.oidc.authorize_access_token(request)
    except Exception as exc:  # Authlib raises several OAuthError subclasses.
        logger.warning("Dex callback failed: %s", exc)
        return _html_error(400, "the identity provider did not complete the login")
    userinfo = token.get("userinfo") or {}
    email = (userinfo.get("email") or "").strip().lower()
    if not email:
        return _html_error(400, "the identity provider returned no email")
    dex_refresh = token.get("refresh_token")
    if not dex_refresh:
        # Loud, at login: the alternative is a session that dies at its first refresh.
        logger.error("Dex issued no refresh token: offline_access not granted for this connector")
        return _html_error(400, "the identity provider issued no refresh token (offline_access)")
    # One Dex refresh token per user, newest login wins — Dex itself keeps one
    # per (user, client) and replaces it on a new login, so a second tool
    # signing in must not strand the first tool's session. Stored before
    # provisioning: Dex has already replaced the previous token, so a LiteLLM
    # outage here must not leave the old one on file.
    await _store.put(DEXRT, email, {"rt": dex_refresh}, ttl=_settings.as_refresh_ttl_seconds)
    try:
        await ensure_team_and_user(email, _settings, name=userinfo.get("name"))
    except httpx.HTTPError as exc:
        logger.warning("User provisioning failed at as-callback: %s", exc)
        return _html_error(503, "user provisioning failed: LiteLLM is unreachable, try again")
    pending["sub"] = email
    todo = [
        s
        for s in pending["scopes"]
        if s in _settings.services and not await _grants.granted(email, s)
    ]
    if todo:
        return await _chain_next(request, {**pending, "todo": todo})
    return await _finish(pending)


async def _broker_client_id(broker: str) -> str:
    """Register once as a public client of this broker (RFC 7591), remember it."""
    assert _store is not None and _settings is not None
    cached = await _store.get("brokerclient", broker)
    if cached:
        return cached["client_id"]
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{broker}/register",
            json={
                "client_name": "alitellm-auth front door",
                "redirect_uris": [f"{_settings.as_issuer}/oauth/broker-callback"],
                "token_endpoint_auth_method": "none",
            },
        )
    resp.raise_for_status()
    client_id = resp.json()["client_id"]
    await _store.put("brokerclient", broker, {"client_id": client_id}, ttl=CLIENT_TTL)
    return client_id


async def _chain_next(request: Request, pending: dict) -> RedirectResponse:
    """Send the user to the broker of the next service that has no grant."""
    assert _store is not None and _settings is not None and _signer is not None
    scope = pending["todo"][0]
    svc = _settings.services[scope]
    try:
        client_id = await _broker_client_id(svc["broker"])
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        logger.warning("Broker %s unreachable, skipping scope %s: %s", svc["broker"], scope, exc)
        return await _skip_and_continue(request, pending)
    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    chain_id = secrets.token_urlsafe(24)
    # verifier is unused today: the broker's code is never redeemed (the
    # projection is the truth). Kept so a revision that redeems it can.
    await _store.put("chain", chain_id, {**pending, "verifier": verifier}, ttl=CHAIN_TTL)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": f"{_settings.as_issuer}/oauth/broker-callback",
        "scope": svc["store"],
        "state": chain_id,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        # Who this ceremony is for. The browser reaches the broker with no header
        # of ours, and the account it then picks at the provider need not carry
        # the platform's email (Zoho names none at all), so the broker keys the
        # grant by this instead: signed by us, audience the broker's own store
        # name so it verifies nowhere else, and short-lived.
        "login_hint": _signer.issue(
            issuer=_settings.as_issuer,
            audience=svc["store"],
            sub=pending["sub"],
            scope="",
            client_id=client_id,
            ttl=HINT_TTL,
        ),
    }
    return RedirectResponse(f"{svc['broker']}/authorize?{urlencode(params)}", status_code=302)


async def _skip_and_continue(request: Request, pending: dict) -> RedirectResponse:
    rest = pending["todo"][1:]
    if rest:
        return await _chain_next(request, {**pending, "todo": rest})
    return await _finish(pending)


@router.get("/oauth/broker-callback")
async def broker_callback(request: Request):
    """Back from a service broker. A `code` means the broker ran the provider
    consent and stored the grant before minting it; the projection is what we
    trust, so the code is not redeemed. An `error` means the user declined:
    the token is issued without that scope."""
    assert _store is not None
    chain = await _store.pop("chain", request.query_params.get("state", ""))
    if chain is None:
        return _html_error(400, "no authorization is in progress — start again from your client")
    if request.query_params.get("error"):
        logger.info(
            "Service broker returned %s for scope %s",
            request.query_params["error"],
            chain["todo"][0],
        )
    return await _skip_and_continue(request, chain)


async def _finish(pending: dict) -> RedirectResponse:
    assert _store is not None and _grants is not None and _settings is not None
    scopes = await _grants.scopes_for(pending["sub"], pending["scopes"], _settings.as_audience)
    code = secrets.token_urlsafe(32)
    await _store.put("code", code, {**pending, "scope": " ".join(scopes)}, ttl=CODE_TTL)
    params = {"code": code}
    if pending.get("state"):
        params["state"] = pending["state"]
    logger.info(
        "Authorization code issued to client %s (scopes %s)", pending["client_id"], " ".join(scopes)
    )
    return _client_redirect(pending["redirect_uri"], params)


def _pkce_ok(challenge: str, verifier: str) -> bool:
    if re.fullmatch(r"[A-Za-z0-9._~-]{43,128}", verifier) is None:
        return False
    digest = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
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


async def _user_exists(sub: str) -> bool:
    assert _settings is not None
    try:
        await get_litellm_user(sub, _settings)
    except LiteLLMUserNotFound:
        return False
    return True


class DexRefused(Exception):
    """Dex answered the refresh with an OAuth error (invalid_grant): the identity
    provider no longer honours the user, the token expired or was rotated away."""


async def _dex_refresh(refresh_token: str) -> str:
    """Replay a Dex refresh token; return the rotated one (the same one when Dex
    did not rotate). DexRefused on a 4xx; httpx.HTTPError when Dex is unreachable
    or answers 5xx."""
    assert _settings is not None
    metadata = await oauth.oidc.load_server_metadata()
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            metadata["token_endpoint"],
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            auth=(_settings.oauth_client_id, _settings.oauth_client_secret),
        )
    if 400 <= resp.status_code < 500:
        raise DexRefused(resp.text[:200])
    resp.raise_for_status()
    return resp.json().get("refresh_token") or refresh_token


async def _revalidate_at_dex(sub: str) -> str | None:
    """Ask the identity provider whether the user still stands: replay the user's
    shared Dex refresh token and store the rotated one. None (record deleted)
    when the IdP refuses. A sibling session may rotate the shared token while
    we are at Dex, so a refusal is retried once with the token stored now."""
    assert _store is not None and _settings is not None
    rec = await _store.get(DEXRT, sub)
    for _ in range(2):
        if rec is None:
            return None
        try:
            rotated = await _dex_refresh(rec["rt"])
        except DexRefused as exc:
            current = await _store.get(DEXRT, sub)
            if current is not None and current["rt"] != rec["rt"]:
                rec = current
                continue
            logger.info("Identity provider refused the refresh for a user; sessions ended: %s", exc)
            await _store.pop(DEXRT, sub)
            return None
        await _store.put(DEXRT, sub, {"rt": rotated}, ttl=_settings.as_refresh_ttl_seconds)
        return rotated
    await _store.pop(DEXRT, sub)
    return None


@router.post("/oauth/token")
async def token(request: Request) -> JSONResponse:
    assert _store is not None and _settings is not None and _grants is not None
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
        rec = await _store.get("refresh", presented)
        if rec is None or rec["client_id"] != client_id:
            return _error(400, "invalid_grant")
        # The identity provider first: only a user Dex still honours gets a new
        # pair. A refusal ends every session of the user (the Dex token is gone,
        # so siblings fail their next refresh without asking Dex) and the client
        # goes back to login, where the IdP says no. Dex unreachable is a 503
        # and the presented token stays valid.
        try:
            honoured = await _revalidate_at_dex(rec["sub"])
        except httpx.HTTPError as exc:
            logger.warning("Refresh deferred, identity provider unreachable: %s", exc)
            return _error(503, "temporarily_unavailable", "identity provider unreachable")
        # Why the front key is NOT revoked on refusal (ach revokes its oauth pk_):
        # here the authz resolves sub → front key through /api/internal/front-key,
        # which self-heals — a revoked key would simply be re-minted on the next
        # request carrying a still-valid JWT. Exposure after an IdP refusal is
        # bounded by AS_ACCESS_TTL_SECONDS (default 3600) either way, which is
        # the same bound ach ends up with.
        if honoured is None:
            await _store.pop("refresh", presented)
            return _error(
                400, "invalid_grant", "the identity provider no longer honours this session"
            )
        try:
            alive = await _user_exists(rec["sub"])
        except httpx.HTTPError as exc:
            logger.warning("Refresh deferred, LiteLLM unreachable: %s", exc)
            return _error(503, "temporarily_unavailable")
        consumed = await _store.pop("refresh", presented)
        if consumed is None or consumed["client_id"] != client_id:
            return _error(400, "invalid_grant")
        if not alive:
            logger.info("Refused a refresh for a user no longer in LiteLLM")
            return _error(400, "invalid_grant")
        # Re-derived on every refresh: a revoked grant drops off within one access-token TTL.
        scopes = await _grants.scopes_for(
            consumed["sub"], consumed["scope"].split(), _settings.as_audience
        )
        return await _issue(consumed["sub"], client_id, " ".join(scopes))
    return _error(400, "unsupported_grant_type")
