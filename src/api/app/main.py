# SPDX-License-Identifier: Apache-2.0
"""Token Factory FastAPI application factory."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from pydantic import ValidationError
from starlette.middleware.sessions import SessionMiddleware

from app.admin import router as admin_router
from app.auth import configure_auth, router as auth_router
from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    if settings is None:
        settings = get_settings()

    app = FastAPI(title="alitellm-auth", version="0.2.0")

    # SessionMiddleware is REQUIRED by authlib to persist OAuth state/nonce
    # between /auth/login and /auth/callback. Without it: MismatchingStateError.
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret_key,
        same_site="lax",
        https_only=False,  # Set True in production (HTTPS)
    )

    # Store settings on app.state for access in route handlers
    app.state.settings = settings

    # Register Dex as OIDC provider
    configure_auth(settings)

    # Mount auth routes
    app.include_router(auth_router)
    app.include_router(admin_router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

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
