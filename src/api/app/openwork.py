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
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.oauth_as.store import Store

router = APIRouter(prefix="/openwork", tags=["openwork"])

# Store partitions. Grants are single-use and short-lived; tokens are the
# desktop's long-lived session credential.
GRANT_KIND = "openwork_grant"
TOKEN_KIND = "openwork_token"


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
