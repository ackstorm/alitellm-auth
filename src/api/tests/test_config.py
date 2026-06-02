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
