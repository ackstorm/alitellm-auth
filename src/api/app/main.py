# SPDX-License-Identifier: Apache-2.0
"""Token Factory FastAPI application factory."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from starlette.middleware.sessions import SessionMiddleware

from app.admin import router as admin_router
from app.auth import configure_auth, router as auth_router
from app.config import Settings, get_settings
from app.public import router as public_router
from app.session import router as session_router

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if settings is None:
        settings = get_settings()

    app = FastAPI(title="alitellm-auth", version="0.4.1")

    # SessionMiddleware is REQUIRED by authlib to persist OAuth state/nonce
    # between /auth/login and /auth/callback. Without it: MismatchingStateError.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret_key,
        same_site="lax",  # D-03: Strict breaks the OIDC callback's cross-site top-level GET
        https_only=settings.session_https_only,  # env-gated (D-18/D-06): True in prod, False for local dev
        max_age=28800,  # D-05: 8h sliding idle timeout (Starlette re-sets per response)
    )

    # Store settings on app.state for access in route handlers
    app.state.settings = settings

    # Register Dex as OIDC provider
    configure_auth(settings)

    # Mount auth routes
    app.include_router(auth_router)
    app.include_router(admin_router)
    # Mount session API router (/api/session/*)
    app.include_router(session_router)
    # Public presentation-config router (GET /api/config) — registered BEFORE the
    # /ui StaticFiles mount below so /api/config is never shadowed by the static mount.
    app.include_router(public_router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    # Serve the SPA shell at /ui same-origin (D-03). Mounted AFTER all API routers so
    # it never shadows /api/* (T-09-06). check_dir=False so create_app() (and the whole
    # test suite + the module-level import guard) does not crash when src/ui/dist is
    # absent — the Dockerfile builder stage (Plan 04) populates /app/ui/dist at image
    # build time. /ui returns 200 text/html even unauthenticated; auth is gated
    # client-side by the SPA (Plan 02).
    app.mount("/ui", StaticFiles(directory="ui/dist", html=True, check_dir=False), name="ui")

    return app


def _log_missing_env_vars(exc: ValidationError) -> None:
    """Print a friendly one-line-per-var message for missing required env vars.

    Pydantic's default traceback is noisy and hides which vars are missing.
    This reformats it into something readable at a glance in pod logs.
    """
    missing = [
        ".".join(str(p) for p in err["loc"]).upper()
        for err in exc.errors()
        if err["type"] == "missing"
    ]
    other = [err for err in exc.errors() if err["type"] != "missing"]

    if missing:
        logger.error("=" * 70)
        logger.error("Startup failed: required environment variables are not set")
        logger.error("=" * 70)
        for var in missing:
            logger.error("  - %s", var)
        logger.error("")
        logger.error("These are typically provided by the k8s secret 'alitellm-auth-secret'.")
        logger.error("Check: kubectl get secret alitellm-auth-secret -n <namespace> -o yaml")
        logger.error("=" * 70)

    if other:
        logger.error("Additional config validation errors: %s", other)


# Module-level app instance for uvicorn — guarded so tests don't fail without env vars.
# Exceptions are logged so real startup failures surface in pod logs (otherwise uvicorn
# only reports "NoneType object is not callable" with no hint of the underlying cause).
try:
    app = create_app()
except ValidationError as exc:
    _log_missing_env_vars(exc)
    app = None  # type: ignore[assignment]
except Exception:
    logger.exception("create_app() failed at import time")
    app = None  # type: ignore[assignment]
