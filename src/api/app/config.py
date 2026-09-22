# SPDX-License-Identifier: Apache-2.0
"""Application settings loaded from environment variables."""

from __future__ import annotations

import json
from typing import Literal

from cryptography.fernet import Fernet
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
    # Scopes requested from the OIDC provider, for BOTH the console login and
    # the authorization-server leg.
    #
    # Adding "groups" makes Dex's Google connector perform a Directory API
    # lookup (serviceAccountFilePath + domainToAdminEmail in the connector
    # config) and return the user's Workspace groups. That lookup needs
    # domain-wide delegation for admin.directory.group.readonly; without it Dex
    # FAILS the login rather than omitting the claim — and this is the only
    # sign-in path there is, for the console and for every OAuth client.
    #
    # So it is OFF by default: opt in per deployment with
    # OAUTH_SCOPES="openid email profile groups" (Helm: config.oauthScopes),
    # and roll back by restoring this value and restarting — no image rebuild.
    oauth_scopes: str = "openid email profile"

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
    # OAuth 2.1 authorization server — the front door (docs/plans/2026-09-17-oauth-front-door.md).
    # Off by default; nothing below is read unless AS_ENABLED=true.
    as_enabled: bool = False
    as_issuer_url: str = ""  # empty → app_base_url. Must be the public URL clients dial.
    as_audience: str = "alitellm"  # `aud` of every access token; the authz checks it
    as_signing_key_pem: str = ""  # RSA private key, PEM. Same on every replica → same JWKS
    as_access_ttl_seconds: int = 3600
    # A refresh re-validates the user in LiteLLM (Task 7), bounding browser-free access.
    as_refresh_ttl_seconds: int = 7 * 86400
    # Required except for memory://, which is for tests and one-replica development only.
    as_redis_url: str = ""
    # Fernet key for the per-user LiteLLM key at rest. LiteLLM hands out the plaintext
    # once, at /key/generate, so we hold the only copy — encrypted.
    as_key_encryption_key: str = ""
    # Shared secret between the Go authz and /api/internal/* (Task 9). Both containers
    # read it from the same Secret via envFrom.
    internal_token: str = ""
    # MCP services a user token may carry as scopes. JSON: scope name (the path
    # segment under /mcp/) → {"store": the pods' service name in Redis,
    # "broker": that service's authorization server}. Empty → no MCP scopes.
    #   {"mcp-aws-eks-ro": {"store": "aws-eks-ro", "broker": "https://api.ackstorm.ai/aws-eks-ro-callback"}}
    as_services: str = ""
    # Where the MCP pods keep their cleartext grant projection
    # (oauth:{store}:state:{email}). Empty → same Redis as AS_REDIS_URL.
    as_mcp_redis_url: str = ""

    # --- OpenWork organization server (docs/plans/2026-09-18-openwork-den.md) ---
    # Off by default; nothing below is read unless OPENWORK_ENABLED=true.
    # Reuses AS_REDIS_URL for grant/token storage (set it to memory:// for local dev).
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

    @property
    def services(self) -> dict[str, dict]:
        return json.loads(self.as_services) if self.as_services else {}

    @property
    def as_issuer(self) -> str:
        return (self.as_issuer_url or self.app_base_url).rstrip("/")

    @model_validator(mode="after")
    def _scopes_keep_openid(self) -> "Settings":
        # OAUTH_SCOPES is free-form and feeds both the console login and the AS
        # leg. Drop "openid" (or blank the value) and the provider returns no
        # id_token, so every callback dies on "No email claim returned by
        # identity provider" — a total sign-in outage found only by a user
        # trying to log in. Fail at boot instead.
        if "openid" not in self.oauth_scopes.split():
            raise ValueError('OAUTH_SCOPES must include "openid" (got: %r)' % self.oauth_scopes)
        return self

    @model_validator(mode="after")
    def _openwork_requires_a_store(self) -> "Settings":
        # Grants and tokens live in the AS store; without a URL create_store()
        # would dial redis.from_url("") and die at boot with an opaque error.
        if self.openwork_enabled and not self.as_redis_url:
            raise ValueError("OPENWORK_ENABLED=true requires AS_REDIS_URL (memory:// for dev)")
        return self

    @model_validator(mode="after")
    def _as_requires_its_secrets(self) -> "Settings":
        if not self.as_enabled:
            return self
        missing = [
            env
            for env, value in (
                ("AS_SIGNING_KEY_PEM", self.as_signing_key_pem),
                ("AS_KEY_ENCRYPTION_KEY", self.as_key_encryption_key),
                ("AS_REDIS_URL", self.as_redis_url),
                ("INTERNAL_TOKEN", self.internal_token),
            )
            if not value
        ]
        if missing:
            raise ValueError(f"{', '.join(missing)} required when AS_ENABLED=true")
        try:
            Fernet(self.as_key_encryption_key.encode())
        except (ValueError, TypeError) as exc:
            raise ValueError("AS_KEY_ENCRYPTION_KEY is not a valid Fernet key") from exc
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
