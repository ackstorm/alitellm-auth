# SPDX-License-Identifier: Apache-2.0
import pytest
from unittest.mock import patch


def test_settings_load_from_env():
    env = {
        "APP_BASE_URL": "http://localhost:8080",
        "SESSION_SECRET_KEY": "test-secret-32-chars-padding-xxx",
        "OAUTH_ISSUER_URL": "http://dex.test/dex",
        "OAUTH_CLIENT_ID": "test-client",
        "OAUTH_CLIENT_SECRET": "test-secret",
        "LITELLM_URL": "http://litellm.test",
        "LITELLM_MASTER_KEY": "sk-test",
        "API_PUBLIC_URL": "https://api.test",
    }
    with patch.dict("os.environ", env, clear=True):
        from app.config import get_settings

        settings = get_settings()

    assert settings.app_base_url == "http://localhost:8080"
    assert settings.oauth_issuer_url == "http://dex.test/dex"
    assert settings.oauth_client_id == "test-client"
    assert settings.litellm_url == "http://litellm.test"
    assert settings.litellm_master_key == "sk-test"
    assert settings.api_public_url == "https://api.test"


def test_settings_missing_required_raises():
    with patch.dict("os.environ", {}, clear=True):
        from app.config import get_settings

        with pytest.raises(Exception):  # pydantic ValidationError
            get_settings()


def test_brand_link_fields_default_neutral():
    """Brand/link fields default to alitellm-auth-neutral values when unset (D-01)."""
    env = {
        "APP_BASE_URL": "http://localhost:8080",
        "SESSION_SECRET_KEY": "test-secret-32-chars-padding-xxx",
        "OAUTH_ISSUER_URL": "http://dex.test/dex",
        "OAUTH_CLIENT_ID": "test-client",
        "OAUTH_CLIENT_SECRET": "test-secret",
        "LITELLM_URL": "http://litellm.test",
        "LITELLM_MASTER_KEY": "sk-test",
    }
    with patch.dict("os.environ", env, clear=True):
        from app.config import get_settings

        settings = get_settings()

    assert settings.brand == "alitellm-auth"
    assert settings.brand_short == "LiteLLM"
    assert settings.tagline == ""
    assert settings.accent_segment == "-auth"
    assert settings.provider_label == "dex"
    assert settings.link_docs is None
    assert settings.link_status is None
    assert settings.link_support is None
    assert settings.link_privacy is None
    assert settings.link_terms is None


def test_brand_link_fields_load_from_env():
    """Brand/link fields load from environment variables."""
    env = {
        "APP_BASE_URL": "http://localhost:8080",
        "SESSION_SECRET_KEY": "test-secret-32-chars-padding-xxx",
        "OAUTH_ISSUER_URL": "http://dex.test/dex",
        "OAUTH_CLIENT_ID": "test-client",
        "OAUTH_CLIENT_SECRET": "test-secret",
        "LITELLM_URL": "http://litellm.test",
        "LITELLM_MASTER_KEY": "sk-test",
        "BRAND": "ACKStorm AI Gateway",
        "ACCENT_SEGMENT": "",
        "TAGLINE": "Self-service portal for LiteLLM API keys",
        "LINK_DOCS": "https://docs.example",
        "LINK_PRIVACY": "https://privacy.example",
        "LINK_TERMS": "https://terms.example",
    }
    with patch.dict("os.environ", env, clear=True):
        from app.config import get_settings

        settings = get_settings()

    assert settings.brand == "ACKStorm AI Gateway"
    assert settings.accent_segment == ""
    assert settings.tagline == "Self-service portal for LiteLLM API keys"
    assert settings.link_docs == "https://docs.example"
    assert settings.link_privacy == "https://privacy.example"
    assert settings.link_terms == "https://terms.example"
