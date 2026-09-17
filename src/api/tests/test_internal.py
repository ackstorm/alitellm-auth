# SPDX-License-Identifier: Apache-2.0
import asyncio
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

from app.main import create_app
from app.oauth_as import routes
from tests.test_oauth_as_routes import make_settings

HDR = {"x-internal-token": "shh"}
MINTED = {"key": "sk-front-1", "id": "k1", "team_id": "default"}


def _client() -> TestClient:
    return TestClient(create_app(settings=make_settings()), raise_server_exceptions=False)


def _404() -> httpx.HTTPStatusError:
    response = httpx.Response(404, request=httpx.Request("GET", "http://litellm.test/key/info"))
    return httpx.HTTPStatusError("gone", request=response.request, response=response)


def test_rejects_without_the_internal_token():
    client = _client()
    assert client.post("/api/internal/front-key", json={"sub": "u@x.com"}).status_code == 403
    response = client.post(
        "/api/internal/front-key", json={"sub": "u@x.com"}, headers={"x-internal-token": "nope"}
    )
    assert response.status_code == 403


def test_mints_once_then_serves_from_the_store_and_lowercases_the_subject():
    client = _client()
    with (
        patch("app.internal.generate_litellm_key", AsyncMock(return_value=MINTED)) as generate,
        patch("app.internal.get_key_info", AsyncMock(return_value={})),
    ):
        first = client.post("/api/internal/front-key", json={"sub": "U@X.com"}, headers=HDR)
        second = client.post("/api/internal/front-key", json={"sub": "u@x.com"}, headers=HDR)
    assert first.status_code == 200 and first.json() == {"key": "sk-front-1"}
    assert second.json() == {"key": "sk-front-1"}
    generate.assert_awaited_once()
    assert generate.await_args.args[0] == "u@x.com"
    assert generate.await_args.kwargs["alias"] == "front"


def test_stored_key_is_not_plaintext():
    client = _client()
    with patch("app.internal.generate_litellm_key", AsyncMock(return_value=MINTED)):
        client.post("/api/internal/front-key", json={"sub": "u@x.com"}, headers=HDR)
    record = asyncio.run(routes._store.get("frontkey", "u@x.com"))
    assert record is not None and "sk-front-1" not in record["enc"]


def test_a_key_litellm_no_longer_recognises_is_reminted():
    client = _client()
    with (
        patch(
            "app.internal.generate_litellm_key",
            AsyncMock(side_effect=[MINTED, {**MINTED, "key": "sk-front-2"}]),
        ) as generate,
        patch("app.internal.get_key_info", AsyncMock(side_effect=_404())),
    ):
        client.post("/api/internal/front-key", json={"sub": "u@x.com"}, headers=HDR)
        response = client.post("/api/internal/front-key", json={"sub": "u@x.com"}, headers=HDR)
    assert response.json() == {"key": "sk-front-2"}
    assert generate.await_count == 2


def test_litellm_down_on_the_liveness_check_still_serves_the_stored_key():
    client = _client()
    with (
        patch("app.internal.generate_litellm_key", AsyncMock(return_value=MINTED)),
        patch("app.internal.get_key_info", AsyncMock(side_effect=httpx.ConnectError("down"))),
    ):
        client.post("/api/internal/front-key", json={"sub": "u@x.com"}, headers=HDR)
        response = client.post("/api/internal/front-key", json={"sub": "u@x.com"}, headers=HDR)
    assert response.status_code == 200 and response.json() == {"key": "sk-front-1"}


def test_a_concurrent_mint_waits_instead_of_minting_twice():
    client = _client()
    asyncio.run(routes._store.acquire("mint:u@x.com", ttl=10))
    with (
        patch("app.internal.generate_litellm_key", AsyncMock(return_value=MINTED)) as generate,
        patch("app.internal.MINT_WAIT_SECONDS", 0),
    ):
        response = client.post("/api/internal/front-key", json={"sub": "u@x.com"}, headers=HDR)
    assert response.status_code == 503 and response.json()["error"] == "mint_in_progress"
    generate.assert_not_awaited()


def test_litellm_failure_on_mint_is_a_502():
    client = _client()
    with patch("app.internal.generate_litellm_key", AsyncMock(side_effect=_404())):
        response = client.post("/api/internal/front-key", json={"sub": "u@x.com"}, headers=HDR)
    assert response.status_code == 502
