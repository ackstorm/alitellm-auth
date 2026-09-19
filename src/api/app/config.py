# SPDX-License-Identifier: Apache-2.0
"""Application settings loaded from environment variables."""

from __future__ import annotations

from typing import Literal

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
    # Shared team id + display alias for the single per-deployment team. Defaults
    # to "default"; override per deployment. Decoupled from OAUTH_CLIENT_ID so the
    # team can be renamed without touching the OIDC client. Env var:
    # LITELLM_DEFAULT_TEAM.
    litellm_default_team: str = "default"
    # Startup verification of the master-key + x-user-id user-scoping contract
    # (the sso_key_swapper custom auth — see deploy/litellm/). Non-fatal: when the
    # contract is not enforced we log a CRITICAL banner; we never refuse to serve.
    # Set false for OSS forks / deployments not using per-user catalog scoping.
    # Env var: LITELLM_USER_SCOPING_CHECK
    litellm_user_scoping_check: bool = True
    # Redis for the OpenWork Den's grants and tokens. Required whenever
    # OPENWORK_ENABLED=true; memory:// is for tests and one-replica development only.
    as_redis_url: str = ""

    # --- OpenWork organization server (docs/plans/2026-09-18-openwork-den.md) ---
    # Off by default; nothing below is read unless OPENWORK_ENABLED=true.
    # Grants and tokens live in the store behind AS_REDIS_URL (memory:// for local dev).
    openwork_enabled: bool = False
    # Session token lifetime. The desktop holds this until sign-out.
    openwork_token_ttl_seconds: int = 30 * 24 * 3600
    # One-time sign-in grant lifetime. Keep short: it is a bearer to a session.
    openwork_grant_ttl_seconds: int = 300

    # Branding pushed to the desktop. accent must be one of the 22 Radix
    # families OpenWork accepts (packages/types/src/den/desktop-policies.ts:302);
    # anything else is silently dropped by the client.
    openwork_brand_app_name: str = "AliteLLM Auth"
    openwork_brand_logo_url: str = ""
    openwork_brand_icon_url: str = ""
    openwork_accent_color: Literal[
        "blue",
        "crimson",
        "cyan",
        "gold",
        "grass",
        "green",
        "indigo",
        "iris",
        "jade",
        "lime",
        "mint",
        "orange",
        "pink",
        "plum",
        "purple",
        "red",
        "ruby",
        "sky",
        "teal",
        "tomato",
        "violet",
        "yellow",
    ] = "mint"

    # Execution policy. NOTE: a non-empty blocked-command list disables
    # interactive terminals and saved commands outright in OpenWork
    # (apps/server/src/managed-policy-rules.ts:77-78). Empty = terminals work.
    # Patterns are case-insensitive globs (* and ?) over the whole command.
    openwork_blocked_commands: list[str] = []
    openwork_block_browser_uploads: bool = False
    # Organization identity shown in the desktop.
    openwork_org_name: str = "AliteLLM Auth"
    openwork_org_slug: str = "alitellm-auth"

    @model_validator(mode="after")
    def _openwork_requires_a_store(self) -> "Settings":
        # Grants and tokens live in the Redis store; without a URL create_store()
        # would dial redis.from_url("") and die at boot with an opaque error.
        if self.openwork_enabled and not self.as_redis_url:
            raise ValueError("OPENWORK_ENABLED=true requires AS_REDIS_URL (memory:// for dev)")
        return self

    # Neutral default (D-01): keep OSS forks brand-neutral. Deployments set the
    # branded public URL via API_PUBLIC_URL. When unset, public_config falls back
    # gracefully (urlparse("").hostname or "" → "").
    api_public_url: str = ""  # public URL shown to users
    # Public URL of the hosted chat UI (CHAT nav button + How-to card). When unset,
    # the SPA falls back to deriving chat.<domain> from api_public_url's host. Set
    # this when the chat UI does NOT live at chat.<same-domain-as-api>.
    # Env var: CHAT_PUBLIC_URL
    chat_public_url: str = ""

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

    @property
    def team_id(self) -> str:
        """Shared team id for the single per-deployment team (LITELLM_DEFAULT_TEAM)."""
        return self.litellm_default_team


def get_settings() -> Settings:
    return Settings()
