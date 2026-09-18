# SPDX-License-Identifier: Apache-2.0
"""Tests for the OpenWork organization server (Den) contract.

See docs/plans/2026-09-18-openwork-den.md. The desktop client is strict about
error shape and CORS; those are pinned here, not left to convention.
"""

import asyncio

import pytest
from fastapi.testclient import TestClient

from app.openwork import TOKEN_KIND


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
        openwork_enabled=True,
        as_redis_url="memory://",
    )
    base.update(overrides)
    return Settings(**base)


def _client(**overrides):
    from app.main import create_app

    return TestClient(create_app(make_test_settings(**overrides)))


def _put_token(client: TestClient, token: str = "test-den-token") -> str:
    asyncio.run(
        client.app.state.openwork_store.put(
            TOKEN_KIND, token, {"email": "dev@ackstorm.com", "name": "Dev"}, ttl=3600
        )
    )
    return token


@pytest.fixture
def den_token_client():
    """A TestClient plus a valid Den session token for dev@ackstorm.com."""
    client = _client()
    return client, _put_token(client)


def test_den_routes_absent_when_disabled():
    response = _client(openwork_enabled=False).get("/openwork/api/den/v1/me")
    assert response.status_code == 404


def test_unauthenticated_v1_call_uses_the_den_error_shape():
    # The desktop reads payload.error / payload.message; FastAPI's default
    # {"detail": ...} would surface as a generic "Request failed with 401".
    response = _client().get("/openwork/api/den/v1/me")
    assert response.status_code == 401
    body = response.json()
    assert body["error"] == "unauthorized"
    assert isinstance(body["message"], str) and body["message"]
    assert "detail" not in body


def test_unknown_token_is_rejected_with_the_den_error_shape(den_token_client):
    client, _ = den_token_client
    response = client.get("/openwork/api/den/v1/me", headers={"authorization": "Bearer nope"})
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_me_returns_the_token_owner(den_token_client):
    client, token = den_token_client
    response = client.get("/openwork/api/den/v1/me", headers={"authorization": f"Bearer {token}"})
    assert response.status_code == 200
    user = response.json()["user"]
    assert user["email"] == "dev@ackstorm.com"
    assert user["name"] == "Dev"
    assert user["id"].startswith("user_")


def test_den_cors_reflects_the_requesting_origin():
    # credentials: "include" on the client (den.ts:2916) means the wildcard
    # origin is rejected; the exact origin must come back.
    response = _client().options(
        "/openwork/api/den/v1/me",
        headers={
            "origin": "app://openwork",
            "access-control-request-method": "GET",
            "access-control-request-headers": "authorization",
        },
    )
    assert response.status_code in (200, 204)
    assert response.headers["access-control-allow-origin"] == "app://openwork"
    assert response.headers["access-control-allow-credentials"] == "true"


def test_den_cors_applies_to_real_responses_too(den_token_client):
    client, token = den_token_client
    response = client.get(
        "/openwork/api/den/v1/me",
        headers={"authorization": f"Bearer {token}", "origin": "app://openwork"},
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "app://openwork"


def test_den_cors_does_not_apply_to_the_spa_api():
    response = _client().options(
        "/api/config",
        headers={"origin": "https://evil.test", "access-control-request-method": "GET"},
    )
    assert "access-control-allow-origin" not in response.headers


def test_grant_exchange_returns_a_session_and_is_single_use():
    from app.openwork import GRANT_KIND

    client = _client()
    asyncio.run(
        client.app.state.openwork_store.put(
            GRANT_KIND, "test-grant-value", {"email": "dev@ackstorm.com", "name": "Dev"}, ttl=300
        )
    )

    first = client.post(
        "/openwork/api/den/v1/auth/desktop-handoff/exchange", json={"grant": "test-grant-value"}
    )
    assert first.status_code == 200
    body = first.json()
    assert body["token"]
    assert body["user"]["email"] == "dev@ackstorm.com"
    assert body["organization"]["slug"] == "ackstorm"
    assert body["connectEnabled"] is False

    # The token works.
    me = client.get("/openwork/api/den/v1/me", headers={"authorization": f"Bearer {body['token']}"})
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "dev@ackstorm.com"

    # Replaying the grant does not.
    replay = client.post(
        "/openwork/api/den/v1/auth/desktop-handoff/exchange", json={"grant": "test-grant-value"}
    )
    assert replay.status_code == 404
    assert replay.json()["error"] == "grant_not_found"


def test_exchange_rejects_an_unknown_grant():
    response = _client().post(
        "/openwork/api/den/v1/auth/desktop-handoff/exchange", json={"grant": "nope-nope-nope"}
    )
    assert response.status_code == 404
    assert response.json()["error"] == "grant_not_found"


def test_exchange_rejects_a_missing_or_malformed_grant():
    client = _client()
    assert (
        client.post("/openwork/api/den/v1/auth/desktop-handoff/exchange", json={}).json()["error"]
        == "invalid_request"
    )
    response = client.post(
        "/openwork/api/den/v1/auth/desktop-handoff/exchange", content=b"not json"
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


def _make_session_cookie(secret: str, data: dict) -> str:
    """Create a signed Starlette session cookie for test use (as test_auth does)."""
    import base64
    import json

    from itsdangerous import TimestampSigner

    payload = base64.b64encode(json.dumps(data).encode()).decode()
    return TimestampSigner(secret).sign(payload).decode()


HANDOFF_URL = "/openwork?mode=sign-in&desktopAuth=1&desktopScheme=openwork"


def test_handoff_page_redirects_to_login_when_signed_out():
    client = _client()
    response = client.get(HANDOFF_URL, follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "http://localhost:8080/api/oauth/login"
    # The intent is remembered so the callback returns here rather than /ui.
    assert client.cookies.get("session") is not None


def test_handoff_page_mints_a_deep_link_for_a_signed_in_user():
    from app.openwork import GRANT_KIND

    client = _client()
    client.cookies.set(
        "session",
        _make_session_cookie(
            client.app.state.settings.session_secret_key,
            {"email": "dev@ackstorm.com", "name": "Dev", "openwork_handoff": True},
        ),
    )
    response = client.get(HANDOFF_URL, follow_redirects=False)
    assert response.status_code == 200
    assert "dev@ackstorm.com" in response.text
    assert "openwork://den-auth?grant=" in response.text
    assert "denBaseUrl=http%3A%2F%2Flocalhost%3A8080%2Fopenwork%2Fapi%2Fden" in response.text

    # The grant on the page is real: it exchanges for the signed-in user.
    import re

    grant = re.search(r"grant=([A-Za-z0-9_-]+)", response.text).group(1)
    exchanged = client.post(
        "/openwork/api/den/v1/auth/desktop-handoff/exchange", json={"grant": grant}
    )
    assert exchanged.status_code == 200
    assert exchanged.json()["user"]["email"] == "dev@ackstorm.com"
    assert asyncio.run(client.app.state.openwork_store.get(GRANT_KIND, grant)) is None


def test_orgs_lists_the_single_organization(den_token_client):
    client, token = den_token_client
    response = client.get(
        "/openwork/api/den/v1/me/orgs", headers={"authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["orgs"]) == 1
    assert body["orgs"][0]["slug"] == "ackstorm"
    assert body["orgs"][0]["name"] == "ACKstorm"
    assert body["orgs"][0]["role"] == "member"
    assert body["activeOrgId"] == body["orgs"][0]["id"]
    assert body["activeOrgSlug"] == "ackstorm"


def test_active_organization_is_acknowledged(den_token_client):
    client, token = den_token_client
    response = client.post(
        "/openwork/api/den/v1/me/active-organization",
        json={"organizationId": "whatever"},
        headers={"authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["activeOrgSlug"] == "ackstorm"


def test_resource_snapshot_timestamps_are_byte_stable(den_token_client):
    """Any reformat reads as 'modified' to the desktop and re-triggers sync."""
    client, token = den_token_client
    headers = {"authorization": f"Bearer {token}"}
    first = client.get("/openwork/api/den/v1/resources", headers=headers).json()
    second = client.get("/openwork/api/den/v1/resources", headers=headers).json()
    assert first == second
    assert first["organizationId"]
    assert first["orgMemberId"].startswith("orgmember_")
    assert first["teamIds"] == []
    assert first["resources"] == {"llmProviders": {}, "marketplaces": []}


DESKTOP_CONFIG = "/openwork/api/den/v1/me/desktop-config"


def test_desktop_config_carries_branding_and_policy(den_token_client):
    client, token = den_token_client
    response = client.get(DESKTOP_CONFIG, headers={"authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["brandAppName"] == "ACKstorm Work"
    assert body["brandAccentColor"] == "mint"
    # Must stay permissive: false here would hide the ackstorm provider that
    # comes from OpenCode's own config, and block adding the auth plugin.
    assert body["allowCustomProviders"] is True
    assert body["allowManageExtensions"] is True
    assert body["execution"]["commands"] == "allow"
    assert body["execution"]["blockedCommands"] == []
    assert body["execution"]["blockBrowserUploads"] is False
    assert body["showWelcomePage"] is False
    assert body["connectEnabled"] is False


def test_desktop_config_passes_through_blocked_commands():
    client = _client(
        openwork_blocked_commands=["* | sh", "mkfs*"], openwork_block_browser_uploads=True
    )
    token = _put_token(client)
    body = client.get(DESKTOP_CONFIG, headers={"authorization": f"Bearer {token}"}).json()
    assert body["execution"]["blockedCommands"] == ["* | sh", "mkfs*"]
    assert body["execution"]["blockBrowserUploads"] is True


def test_desktop_config_omits_empty_brand_urls():
    # The client validates brandLogoUrl as a URL and drops the whole field if
    # it is not one; sending "" would be silently discarded, so omit it.
    client = _client(openwork_brand_logo_url="", openwork_brand_icon_url="")
    token = _put_token(client)
    body = client.get(DESKTOP_CONFIG, headers={"authorization": f"Bearer {token}"}).json()
    assert "brandLogoUrl" not in body
    assert "brandIconUrl" not in body


def test_desktop_config_sends_brand_urls_when_set():
    client = _client(
        openwork_brand_logo_url="https://x.test/logo.svg",
        openwork_brand_icon_url="https://x.test/icon.svg",
    )
    token = _put_token(client)
    body = client.get(DESKTOP_CONFIG, headers={"authorization": f"Bearer {token}"}).json()
    assert body["brandLogoUrl"] == "https://x.test/logo.svg"
    assert body["brandIconUrl"] == "https://x.test/icon.svg"


@pytest.mark.parametrize("name", ["logo.svg", "icon.svg"])
def test_brand_marks_are_served_as_svg_without_auth(name):
    response = _client().get(f"/openwork/brand/{name}")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("image/svg+xml")
    assert response.text.lstrip().startswith("<svg")


def test_brand_route_rejects_an_unknown_asset():
    response = _client().get("/openwork/brand/config.py")
    assert response.status_code == 404
    assert response.json()["error"] == "not_found"


EMPTY_ENDPOINTS = {
    "/openwork/api/den/v1/llm-providers": {"llmProviders": []},
    "/openwork/api/den/v1/inference-providers": {"inferenceProviders": []},
    "/openwork/api/den/v1/marketplaces": {"items": []},
    "/openwork/api/den/v1/resources/marketplace-capabilities": {"items": []},
    "/openwork/api/den/v1/me/library": {"items": []},
    "/openwork/api/den/v1/me/dashboards": {"items": []},
    "/openwork/api/den/v1/mcp-connections": {"connections": []},
    "/openwork/api/den/v1/mcp-connections/presets": {"presets": []},
    "/openwork/api/den/v1/apps": {"enabled": False, "sharingEnabled": False, "items": []},
    "/openwork/api/den/v1/automations": {"items": [], "nextCursor": None},
    "/openwork/api/den/v1/cloud-automations": {"items": [], "nextCursor": None},
    "/openwork/api/den/v1/plugins": {"items": []},
}


@pytest.mark.parametrize("path,expected", sorted(EMPTY_ENDPOINTS.items()))
def test_catalog_stubs_are_empty_but_well_formed(den_token_client, path, expected):
    client, token = den_token_client
    response = client.get(path, headers={"authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json() == expected


def test_catalog_stubs_require_a_token(den_token_client):
    client, _ = den_token_client
    response = client.get("/openwork/api/den/v1/llm-providers")
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_unknown_catalog_uses_the_den_404_envelope(den_token_client):
    client, token = den_token_client
    response = client.get(
        "/openwork/api/den/v1/some/new/thing", headers={"authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404
    assert response.json()["error"] == "not_implemented"


def test_telemetry_ingest_accepts_and_discards(den_token_client):
    client, token = den_token_client
    response = client.post(
        "/openwork/api/den/v1/telemetry/ingest",
        json={"events": [{"name": "whatever"}]},
        headers={"authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200


def test_sign_out_revokes_the_token(den_token_client):
    client, token = den_token_client
    headers = {"authorization": f"Bearer {token}"}
    assert client.post("/openwork/api/den/api/auth/sign-out", headers=headers).status_code == 200
    assert client.get("/openwork/api/den/v1/me", headers=headers).status_code == 401
    # Idempotent: signing out twice is not an error the desktop should see.
    assert client.post("/openwork/api/den/api/auth/sign-out", headers=headers).status_code == 200
