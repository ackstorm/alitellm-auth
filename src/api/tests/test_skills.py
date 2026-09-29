# SPDX-License-Identifier: Apache-2.0
"""Tests for the SKILL.md templates served to OpenCode clients."""

from app.skills import GENAI_API, genai_api_body
from tests.as_defaults import AS_TEST_DEFAULTS

SERVICES = (
    '{"mcp-google-drive": {"store": "google-drive", "broker": "https://b.test/g"},'
    ' "mcp-aws-eks-ro": {"store": "aws-eks-ro", "broker": "https://b.test/a"}}'
)


def _settings(**overrides):
    from app.config import Settings

    base = dict(
        app_base_url="https://console.example.com/",
        session_secret_key="test-secret-32-chars-padding-xxxx",
        oauth_issuer_url="http://dex.test/dex",
        oauth_client_id="test-client",
        oauth_client_secret="test-secret",
        litellm_url="http://litellm.test",
        litellm_master_key="sk-test",
        api_public_url="https://api.example.com/",
        as_services=SERVICES,
        session_https_only=True,
        **AS_TEST_DEFAULTS,
    )
    base.update(overrides)
    return Settings(**base)


def test_genai_api_is_filled_from_settings():
    text = genai_api_body(_settings(provider_name="acme"))
    assert GENAI_API == "genai-api"
    assert text.startswith("---\nname: genai-api\n")
    assert "{{" not in text and "}}" not in text
    assert "https://console.example.com/ui/" in text
    assert "https://api.example.com/v1" in text
    assert "opencode auth login -p acme" in text
    assert "opencode auth login https://console.example.com\n" in text
    assert (
        "- `mcp-aws-eks-ro`: `https://api.example.com/mcp/mcp-aws-eks-ro`\n"
        "- `mcp-google-drive`: `https://api.example.com/mcp/mcp-google-drive`"
    ) in text


def test_genai_api_is_brand_neutral_by_default():
    assert "ackstorm" not in genai_api_body(_settings()).lower()


def test_genai_api_without_services():
    text = genai_api_body(_settings(as_services=""))
    assert "No per-server OAuth endpoints are configured on this platform." in text
