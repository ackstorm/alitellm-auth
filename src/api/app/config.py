# SPDX-License-Identifier: Apache-2.0
"""Application settings loaded from environment variables."""

from __future__ import annotations
from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    model_config = {"env_prefix": "", "case_sensitive": False}

    # Application
    app_base_url: str = "http://localhost:8080"
    session_secret_key: str  # required — shared across all replicas for cookie signing

    # OIDC provider (Dex, Keycloak, etc.) — single external URL reachable from browser and server
    oauth_issuer_url: str
    oauth_client_id: str
    oauth_client_secret: str

    # API (LiteLLM backend)
    litellm_url: str  # internal URL used server-side to call admin endpoints
    litellm_master_key: str
    api_public_url: str = "https://api.ackstorm.ai"  # public URL shown to users

    # Factory config — path to mounted ConfigMap JSON with team/user LiteLLM params
    factory_config_path: str | None = None

    # Security baseline (D-18) — Secure cookie flag; True in prod, False for local HTTP dev.
    # Env var: SESSION_HTTPS_ONLY
    session_https_only: bool = False

    # Presentation config (D-01) — served by the public GET /api/config endpoint so a
    # deployment can re-brand without a rebuild. ONLY non-secret presentation values.
    # Defaults stay alitellm-auth-neutral so OSS forks render unchanged.
    brand: str = "alitellm-auth"
    brand_short: str = "LiteLLM"
    tagline: str = ""
    accent_segment: str = "-auth"  # wordmark segment rendered in --accent2; empty → no accent span
    provider_label: str = "dex"

    # Real-links-only targets (D-02/D-03) — None/empty means the link is OMITTED from
    # the SPA (no dead anchor). NEVER add a secret-bearing field to this set.
    link_docs: str | None = None
    link_status: str | None = None
    link_support: str | None = None
    link_privacy: str | None = None
    link_terms: str | None = None

    @model_validator(mode="after")
    def _require_secure_cookie_on_https(self) -> "Settings":
        """D-06 startup guard: refuse a https-served deploy that ships a non-Secure cookie.

        If app_base_url is https:// but session_https_only is False, raise so a
        misconfigured prod crashloops loudly instead of silently shipping a
        non-Secure session cookie. Local http://localhost dev is unaffected (the
        https:// gate is False there). The env var is named explicitly so pod logs
        point straight at the fix.
        """
        if self.app_base_url.startswith("https://") and not self.session_https_only:
            raise ValueError(
                "https APP_BASE_URL requires SESSION_HTTPS_ONLY=true "
                "(refusing to ship a non-Secure session cookie in prod)"
            )
        return self


def get_settings() -> Settings:
    return Settings()
