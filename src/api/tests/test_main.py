# SPDX-License-Identifier: Apache-2.0
from fastapi.testclient import TestClient
from tests.as_defaults import AS_TEST_DEFAULTS


def make_test_settings():
    from app.config import Settings

    return Settings(
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


def test_health_endpoint_returns_ok():
    from app.main import create_app

    app = create_app(settings=make_test_settings())
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_app_has_session_middleware():
    from app.main import create_app

    app = create_app(settings=make_test_settings())
    middleware_types = [m.cls if hasattr(m, "cls") else type(m) for m in app.user_middleware]
    # SessionMiddleware must be present
    assert any("SessionMiddleware" in str(t) for t in middleware_types)


def test_as_routes_are_always_mounted():
    """The front door has no off switch -- the console reads its store."""
    from app.main import create_app
    from tests.test_auth import make_test_settings

    client = TestClient(create_app(settings=make_test_settings()), raise_server_exceptions=False)
    assert client.get("/.well-known/oauth-authorization-server").status_code == 200


def test_as_routes_present_when_enabled():
    from app.main import create_app
    from tests.test_oauth_as_routes import make_settings

    client = TestClient(create_app(settings=make_settings()), raise_server_exceptions=False)
    assert client.get("/.well-known/oauth-authorization-server").status_code == 200
    assert client.get("/oauth/jwks.json").status_code == 200
