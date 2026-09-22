# SPDX-License-Identifier: Apache-2.0
"""Tests for the startup user-scoping contract check (app.contract)."""

import logging
from unittest.mock import AsyncMock

import pytest

from app.config import Settings
from app import contract
from tests.as_defaults import AS_TEST_DEFAULTS


def make_settings(**kwargs) -> Settings:
    defaults = dict(
        session_secret_key="x" * 32,
        oauth_issuer_url="http://oidc.test/dex",
        oauth_client_id="platform",
        oauth_client_secret="s",
        litellm_url="http://litellm.test",
        litellm_master_key="sk-admin",
        api_public_url="https://api.test",
        **AS_TEST_DEFAULTS,
    )
    return Settings(**{**defaults, **kwargs})


@pytest.mark.asyncio
async def test_not_enforced_logs_critical(monkeypatch, caplog):
    monkeypatch.setattr(
        contract, "verify_user_scoping_contract", AsyncMock(return_value="not_enforced")
    )
    sleep = AsyncMock()
    with caplog.at_level(logging.CRITICAL, logger="app.contract"):
        status = await contract.warn_if_contract_unenforced(make_settings(), sleep=sleep)
    assert status == "not_enforced"
    blob = "\n".join(r.getMessage() for r in caplog.records)
    assert "NOT ENFORCED" in blob
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)
    sleep.assert_not_called()  # definitive result on attempt 1 → no retry


@pytest.mark.asyncio
async def test_enforced_no_critical(monkeypatch, caplog):
    monkeypatch.setattr(
        contract, "verify_user_scoping_contract", AsyncMock(return_value="enforced")
    )
    with caplog.at_level(logging.INFO, logger="app.contract"):
        status = await contract.warn_if_contract_unenforced(make_settings(), sleep=AsyncMock())
    assert status == "enforced"
    assert not any(r.levelno == logging.CRITICAL for r in caplog.records)


@pytest.mark.asyncio
async def test_disabled_skips_probe(monkeypatch):
    probe = AsyncMock(return_value="not_enforced")
    monkeypatch.setattr(contract, "verify_user_scoping_contract", probe)
    status = await contract.warn_if_contract_unenforced(
        make_settings(litellm_user_scoping_check=False), sleep=AsyncMock()
    )
    assert status == "disabled"
    probe.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_retries_then_warns(monkeypatch, caplog):
    probe = AsyncMock(return_value="unknown")
    monkeypatch.setattr(contract, "verify_user_scoping_contract", probe)
    sleep = AsyncMock()
    with caplog.at_level(logging.WARNING, logger="app.contract"):
        status = await contract.warn_if_contract_unenforced(
            make_settings(), attempts=3, delay_seconds=0.0, sleep=sleep
        )
    assert status == "unknown"
    assert probe.await_count == 3  # all attempts exhausted
    assert sleep.await_count == 2  # slept between attempts (attempts - 1)
    assert any(r.levelno == logging.WARNING for r in caplog.records)


@pytest.mark.asyncio
async def test_unknown_then_enforced_breaks_early(monkeypatch):
    probe = AsyncMock(side_effect=["unknown", "enforced"])
    monkeypatch.setattr(contract, "verify_user_scoping_contract", probe)
    sleep = AsyncMock()
    status = await contract.warn_if_contract_unenforced(make_settings(), attempts=5, sleep=sleep)
    assert status == "enforced"
    assert probe.await_count == 2  # stopped once definitive
    assert sleep.await_count == 1
