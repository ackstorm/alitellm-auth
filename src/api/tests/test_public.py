# SPDX-License-Identifier: Apache-2.0
"""Tests for the public, unauthenticated GET /api/config endpoint.

This endpoint returns ONLY non-secret presentation config (brand/tagline/links/
providers/public_host) sourced from pydantic Settings at request time. It NEVER
returns a key, user data, or any secret-bearing field (threat T-09-18).
"""

import pytest
from fastapi.testclient import TestClient
from tests.as_defaults import AS_TEST_DEFAULTS


def make_test_settings(**overrides):
    from app.config import Settings

    base = dict(
        app_base_url="http://localhost:8080",
        session_secret_key="test-secret-32-chars-padding-xxxx",
        oauth_issuer_url="http://dex.test/dex",
        oauth_client_id="test-client",
        oauth_client_secret="test-secret",
        litellm_url="http://litellm.test",
        litellm_master_key="sk-test",
        api_public_url="https://api.test",
        **AS_TEST_DEFAULTS,
    )
    base.update(overrides)
    return Settings(**base)


def _client(**overrides):
    from app.main import create_app

    return TestClient(create_app(settings=make_test_settings(**overrides)))


def test_config_returns_200_without_auth_header():
    """(a) GET /api/config returns 200 with no auth header and brand/providers/links."""
    client = _client()
    resp = client.get("/api/config")  # no auth header at all
    assert resp.status_code == 200
    body = resp.json()
    assert "brand" in body
    assert "providers" in body
    assert isinstance(body["providers"], list) and len(body["providers"]) > 0
    assert "links" in body
    assert isinstance(body["links"], dict)


def test_config_links_empty_with_default_settings():
    """(b) With default settings all link_* are None, so links has zero keys."""
    client = _client()
    body = client.get("/api/config").json()
    assert body["links"] == {}


def test_config_links_present_only_when_set():
    """(c) With link_docs/link_privacy set, only those keys are present."""
    client = _client(
        link_docs="https://docs.test",
        link_privacy="https://privacy.test",
    )
    links = client.get("/api/config").json()["links"]
    assert links["docs"] == "https://docs.test"
    assert links["privacy"] == "https://privacy.test"
    # unset link keys must be absent entirely (no dead anchors downstream)
    assert "status" not in links
    assert "support" not in links
    assert "terms" not in links


def test_config_public_host_is_host_of_api_public_url():
    """(d) public_host equals the host of api_public_url."""
    client = _client(api_public_url="https://api.test:8443/path")
    body = client.get("/api/config").json()
    assert body["public_host"] == "api.test"


def test_config_chat_public_url_defaults_empty():
    """(d2) chat_public_url is "" by default → the SPA derives chat.<domain>."""
    body = _client().get("/api/config").json()
    assert body["chat_public_url"] == ""


def test_config_chat_public_url_passthrough_when_set():
    """(d3) An explicit CHAT_PUBLIC_URL is returned verbatim (overrides derivation)."""
    client = _client(chat_public_url="https://chat.example.com")
    body = client.get("/api/config").json()
    assert body["chat_public_url"] == "https://chat.example.com"


def test_config_contains_no_secret_values():
    """(e) The payload contains NONE of the secret setting values."""
    secrets = {
        "litellm_master_key": "sk-super-secret-master",
        "session_secret_key": "session-secret-32-chars-padding-x",
        "oauth_client_secret": "oauth-super-secret",
    }
    client = _client(**secrets)
    text = client.get("/api/config").text
    for value in secrets.values():
        assert value not in text


def test_config_defaults_are_neutral():
    """Defaults stay alitellm-auth-neutral (D-01 OSS forks)."""
    body = _client().get("/api/config").json()
    assert body["brand"] == "alitellm-auth"
    assert body["accent_segment"] == "-auth"
    assert body["providers"] == [
        {"label": "Google"},
        {"label": "Dex"},
        {"label": "OIDC"},
    ]


def test_config_exposes_provider_name():
    """provider_name lets the SPA print `opencode auth login -p <provider>`."""
    body = _client().get("/api/config").json()
    assert body["provider_name"] == "ai-platform"


def test_config_provider_name_passthrough_when_set():
    client = _client(provider_name="acme")
    body = client.get("/api/config").json()
    assert body["provider_name"] == "acme"


@pytest.mark.parametrize(
    "path", ["/public/opencode/api.json", "/public/opencode-auth", "/clients/opencode/plugin"]
)
def test_no_static_mount_and_no_plugin_tarball(tmp_path, monkeypatch, path):
    """/public/* is 404 (0.20.0 had a check_dir=False StaticFiles mount over an
    absent directory: every path 500). The plugin installs from
    /.well-known/opencode now; the tarball routes are gone."""
    monkeypatch.chdir(tmp_path)
    assert _client().get(path).status_code == 404


SPEC = "git+https://github.com/ackstorm/opencode-oidc-provider.git#v0.4.4"


def test_wellknown_opencode_manifest_points_at_the_plugin_with_options():
    body = _client(api_public_url="https://api.example.com/").get("/.well-known/opencode").json()
    assert body == {
        "auth": {"command": ["echo", "ok"], "env": ""},
        "config": {
            "plugin": [
                [
                    SPEC,
                    {
                        "api": "https://api.example.com/v1",
                        "platform": "https://api.example.com",
                        "provider": "ai-platform",
                    },
                ]
            ],
            "enabled_providers": ["ai-platform"],
        },
    }


def test_wellknown_opencode_uses_configured_spec_and_provider():
    client = _client(
        api_public_url="https://api.example.com",
        provider_name="acme",
        opencode_plugin_spec="git+https://example.com/p.git#v9.9.9",
    )
    spec, opts = client.get("/.well-known/opencode").json()["config"]["plugin"][0]
    assert spec == "git+https://example.com/p.git#v9.9.9"
    assert opts["provider"] == "acme"
    assert client.get("/.well-known/opencode").json()["config"]["enabled_providers"] == ["acme"]


def test_wellknown_opencode_is_404_without_api_public_url():
    assert _client(api_public_url="").get("/.well-known/opencode").status_code == 404


def test_wellknown_opencode_carries_no_secrets():
    secrets = {
        "litellm_master_key": "sk-master-SECRET",
        "session_secret_key": "SESSION-SECRET",
        "oauth_client_secret": "OAUTH-SECRET",
    }
    raw = (
        _client(api_public_url="https://api.example.com", **secrets)
        .get("/.well-known/opencode")
        .text
    )
    for value in secrets.values():
        assert value not in raw
