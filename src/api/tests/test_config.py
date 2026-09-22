# SPDX-License-Identifier: Apache-2.0
from cryptography.fernet import Fernet
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


def test_settings_team_id_property():
    from app.config import Settings

    base = dict(
        app_base_url="http://localhost:8080",
        session_secret_key="test-secret-32-chars-padding-xxxx",
        oauth_issuer_url="http://dex.test/dex",
        oauth_client_id="platform",
        oauth_client_secret="test-secret",
        litellm_url="http://litellm.test",
        litellm_master_key="sk-test",
        api_public_url="https://api.test",
    )
    # Defaults to "default", decoupled from oauth_client_id.
    assert Settings(**base).team_id == "default"
    # Overridable via LITELLM_DEFAULT_TEAM.
    assert Settings(**base, litellm_default_team="platform").team_id == "platform"


def _base(**over):
    kw = dict(
        app_base_url="http://localhost:8080",
        session_secret_key="test-secret-32-chars-padding-xxxx",
        oauth_issuer_url="http://dex.test/dex",
        oauth_client_id="test-client",
        oauth_client_secret="test-secret",
        litellm_url="http://litellm.test",
        litellm_master_key="sk-test",
    )
    kw.update(over)
    return kw


def test_as_is_off_by_default():
    from app.config import Settings

    s = Settings(**_base())
    assert s.as_enabled is False
    assert s.as_issuer == "http://localhost:8080"
    assert s.as_refresh_ttl_seconds == 7 * 86400


def test_as_issuer_url_overrides_app_base_url_and_strips_slash():
    from app.config import Settings

    assert (
        Settings(**_base(as_issuer_url="https://platform.test/")).as_issuer
        == "https://platform.test"
    )


def _as_on(**over):
    kw = dict(
        as_enabled=True,
        as_signing_key_pem="-----BEGIN",
        as_key_encryption_key=Fernet.generate_key().decode(),
        as_redis_url="memory://",
        internal_token="shh",
    )
    kw.update(over)
    return _base(**kw)


def test_as_enabled_requires_every_secret():
    from pydantic import ValidationError

    from app.config import Settings

    Settings(**_as_on())  # complete configuration → fine
    for field, env in (
        ("as_signing_key_pem", "AS_SIGNING_KEY_PEM"),
        ("as_key_encryption_key", "AS_KEY_ENCRYPTION_KEY"),
        ("as_redis_url", "AS_REDIS_URL"),
        ("internal_token", "INTERNAL_TOKEN"),
    ):
        with pytest.raises(ValidationError, match=env):
            Settings(**_as_on(**{field: ""}))


def test_as_enabled_rejects_an_invalid_fernet_key_at_startup():
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError, match="Fernet"):
        Settings(**_as_on(as_key_encryption_key="x" * 44))


def test_as_services_is_a_json_registry_keyed_by_scope():
    from app.config import Settings

    assert Settings(**_as_on()).services == {}
    assert Settings(
        **_as_on(as_services='{"mcp-x": {"store": "x", "broker": "https://b"}}')
    ).services == {"mcp-x": {"store": "x", "broker": "https://b"}}


def _openwork_base(**overrides):
    base = dict(
        session_secret_key="test-secret-32-chars-padding-xxxx",
        oauth_issuer_url="http://dex.test/dex",
        oauth_client_id="test-client",
        oauth_client_secret="test-secret",
        litellm_url="http://litellm.test",
        litellm_master_key="sk-test",
    )
    base.update(overrides)
    return base


def test_openwork_disabled_by_default():
    from app.config import Settings

    settings = Settings(**_openwork_base())
    assert settings.openwork_enabled is False
    assert settings.openwork_brand_app_name == "AliteLLM Auth"
    assert settings.openwork_accent_color == "mint"


def test_openwork_accent_color_must_be_a_radix_family():
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError):
        Settings(**_openwork_base(openwork_accent_color="#ff00ff"))


def test_openwork_enabled_requires_a_store_url():
    from pydantic import ValidationError

    from app.config import Settings

    with pytest.raises(ValidationError, match="AS_REDIS_URL"):
        Settings(**_openwork_base(openwork_enabled=True))
    assert Settings(**_openwork_base(openwork_enabled=True, as_redis_url="memory://"))


def test_personal_team_settings_default_off():
    """The new model ships disabled: rollout is a per-deployment decision."""
    from app.config import Settings

    s = Settings(**_base())
    assert s.personal_teams_enabled is False
    assert s.personal_team_prefix == "user-"
    assert s.default_access_groups == []
    assert s.user_access_groups == {}
    assert s.personal_team_id("Alice@Example.com ") == "user-alice@example.com"
