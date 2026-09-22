# SPDX-License-Identifier: Apache-2.0
"""Tests for the public, unauthenticated GET /api/config endpoint.

This endpoint returns ONLY non-secret presentation config (brand/tagline/links/
providers/public_host) sourced from pydantic Settings at request time. It NEVER
returns a key, user data, or any secret-bearing field (threat T-09-18).
"""

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


def test_public_mount_serves_artifact_unauthenticated(tmp_path, monkeypatch):
    """/public is a StaticFiles mount: 200 with no session, same as /ui.

    StaticFiles resolves "public" against the process cwd, so chdir into a
    tmp dir holding the file (same approach as test_session.py's /ui test).
    """
    d = tmp_path / "public" / "opencode"
    d.mkdir(parents=True)
    (d / "api.json").write_text('{"ackstorm": {"models": {}}}')
    monkeypatch.chdir(tmp_path)

    client = _client()
    r = client.get("/public/opencode/api.json")
    assert r.status_code == 200
    assert r.json()["ackstorm"]["models"] == {}


def test_public_mount_does_not_shadow_api_routes():
    """The mount is registered AFTER every /api/* router (T-09-06)."""
    client = _client()
    assert client.get("/api/config").status_code == 200


def test_opencode_plugin_is_served_from_the_image_not_the_mount(tmp_path, monkeypatch):
    """The tarball lives outside /public (a projected volume at runtime) and is
    served by a route registered before the mount, so a /public/opencode-auth
    file in the mount could not shadow it either."""
    monkeypatch.chdir(tmp_path)
    client = _client()
    assert client.get("/public/opencode-auth").status_code == 404

    (tmp_path / "clients").mkdir()
    (tmp_path / "clients" / "opencode-auth.tgz").write_bytes(b"\x1f\x8b")
    r = client.get("/public/opencode-auth")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/gzip"
    assert r.content == b"\x1f\x8b"
