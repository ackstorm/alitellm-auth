# SPDX-License-Identifier: Apache-2.0
"""Tests for the SKILL.md templates served to OpenCode clients."""

from app.skills import mcp_setup_body
from tests.as_defaults import AS_TEST_DEFAULTS


def _settings(**overrides):
    from app.config import Settings

    base = dict(
        app_base_url="http://localhost:8080",
        session_secret_key="test-secret-32-chars-padding-xxxx",
        oauth_issuer_url="http://dex.test/dex",
        oauth_client_id="test-client",
        oauth_client_secret="test-secret",
        litellm_url="http://litellm.test",
        litellm_master_key="sk-test",
        **AS_TEST_DEFAULTS,
    )
    base.update(overrides)
    return Settings(**base)


def test_mcp_setup_lists_the_oauth_services_sorted():
    services = (
        '{"mcp-google-drive": {"store": "google-drive", "broker": "https://b.test/g"},'
        ' "mcp-aws-eks-ro": {"store": "aws-eks-ro", "broker": "https://b.test/a"}}'
    )
    text = mcp_setup_body(
        _settings(as_services=services, api_public_url="https://api.example.com/")
    )
    assert text.startswith("---\nname: mcp-setup\n")
    assert "{{servers}}" not in text
    assert (
        "- `mcp-aws-eks-ro`: `https://api.example.com/mcp/mcp-aws-eks-ro`\n"
        "- `mcp-google-drive`: `https://api.example.com/mcp/mcp-google-drive`"
    ) in text


def test_mcp_setup_without_services():
    text = mcp_setup_body(_settings(as_services="", api_public_url="https://api.example.com"))
    assert "None are configured on this gateway yet." in text
