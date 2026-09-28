# SPDX-License-Identifier: Apache-2.0
"""Tests for the public, unauthenticated GET /api/config endpoint.

This endpoint returns ONLY non-secret presentation config (brand/tagline/links/
providers/public_host) sourced from pydantic Settings at request time. It NEVER
returns a key, user data, or any secret-bearing field (threat T-09-18).
"""

import io
import json
import tarfile

import pytest
from fastapi.testclient import TestClient
from tests.as_defaults import AS_TEST_DEFAULTS

from app import public


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


def test_public_has_no_static_mount(tmp_path, monkeypatch):
    """/public/* is 404 except the opencode-auth alias route. 0.20.0 still had a
    check_dir=False StaticFiles mount over an absent directory: every path 500."""
    monkeypatch.chdir(tmp_path)
    assert _client().get("/public/opencode/api.json").status_code == 404


def test_opencode_plugin_is_served_from_the_image_not_the_mount(tmp_path, monkeypatch):
    """/public/opencode-auth is a permanent alias route for the baked tarball.

    api_public_url="" here: this test is about route precedence, not the
    platform.json repack (covered separately), so raw non-tarball bytes must
    pass through unmodified.
    """
    monkeypatch.chdir(tmp_path)
    client = _client(api_public_url="")
    assert client.get("/public/opencode-auth").status_code == 404

    (tmp_path / "clients").mkdir()
    (tmp_path / "clients" / "opencode-auth.tgz").write_bytes(b"\x1f\x8b")
    r = client.get("/public/opencode-auth")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/gzip"
    assert r.content == b"\x1f\x8b"


def _bake(tmp_path):
    src = io.BytesIO()
    with tarfile.open(fileobj=src, mode="w:gz") as tar:
        data = b"export const x = 1\n"
        info = tarfile.TarInfo("package/index.mjs")
        info.size = len(data)
        tar.addfile(info, io.BytesIO(data))
    (tmp_path / "clients").mkdir()
    (tmp_path / "clients" / "opencode-auth.tgz").write_bytes(src.getvalue())
    public._plugin_tgz.cache_clear()


def _members(raw):
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tar:
        return {m.name: tar.extractfile(m).read() for m in tar.getmembers() if m.isfile()}


@pytest.mark.parametrize("path", ["/clients/opencode/plugin", "/public/opencode-auth"])
def test_plugin_tgz_carries_platform_json(tmp_path, monkeypatch, path):
    from app.main import create_app

    monkeypatch.chdir(tmp_path)
    _bake(tmp_path)
    client = TestClient(
        create_app(settings=make_test_settings(api_public_url="https://api.example.com/"))
    )
    resp = client.get(path)
    assert resp.status_code == 200
    files = _members(resp.content)
    assert files["package/index.mjs"] == b"export const x = 1\n"
    assert json.loads(files["package/platform.json"]) == {
        "api": "https://api.example.com/v1",
        "platform": "https://api.example.com",
        "provider": "ai-platform",
    }


def test_plugin_tgz_carries_the_configured_provider_name(tmp_path, monkeypatch):
    from app.main import create_app

    monkeypatch.chdir(tmp_path)
    _bake(tmp_path)
    client = TestClient(
        create_app(
            settings=make_test_settings(
                api_public_url="https://api.example.com/", provider_name="acme"
            )
        )
    )
    resp = client.get("/clients/opencode/plugin")
    assert json.loads(_members(resp.content)["package/platform.json"])["provider"] == "acme"


def test_plugin_tgz_bytes_are_deterministic(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _bake(tmp_path)
    first = public._plugin_tgz("https://api.example.com", "ai-platform")
    public._plugin_tgz.cache_clear()
    assert public._plugin_tgz("https://api.example.com", "ai-platform") == first


def test_plugin_tgz_without_api_public_url_is_the_baked_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _bake(tmp_path)
    assert (
        public._plugin_tgz("", "ai-platform")
        == (tmp_path / "clients" / "opencode-auth.tgz").read_bytes()
    )
