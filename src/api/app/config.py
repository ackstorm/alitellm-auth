# SPDX-License-Identifier: Apache-2.0
"""Application settings loaded from environment variables."""

from __future__ import annotations
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


def get_settings() -> Settings:
    return Settings()
