# SPDX-License-Identifier: Apache-2.0
"""Startup verification of the LiteLLM user-scoping contract (sso_key_swapper).

This is NON-FATAL: alitellm-auth never refuses to serve or fails readiness over it.
At startup it probes LiteLLM and, if the master-key + ``x-user-id`` impersonation
contract is NOT enforced (the custom auth is missing/misconfigured), logs a prominent
CRITICAL banner — per-user Models/MCPs would silently degrade to the GLOBAL admin
catalog until the deployment installs the ``sso_key_swapper`` custom auth.

See deploy/litellm/ for the canonical custom-auth file and install instructions.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable

from app.config import Settings
from app.litellm_client import verify_user_scoping_contract

logger = logging.getLogger(__name__)

_BANNER = "=" * 70


def _log_not_enforced() -> None:
    """Loud, unmissable CRITICAL banner for the privilege-escalation hazard."""
    logger.critical(_BANNER)
    logger.critical("LiteLLM user-scoping contract NOT ENFORCED")
    logger.critical(_BANNER)
    logger.critical("A master-key request carrying x-user-id was accepted as FULL ADMIN.")
    logger.critical("The sso_key_swapper custom auth is missing or misconfigured, so the")
    logger.critical("per-user Models/MCPs catalog silently falls back to the GLOBAL admin")
    logger.critical("view (every user would see every model / MCP server).")
    logger.critical("")
    logger.critical("Fix: install the custom auth on the LiteLLM deployment —")
    logger.critical("  deploy/litellm/README.md (configMap + volumeMount + custom_auth).")
    logger.critical(_BANNER)


async def warn_if_contract_unenforced(
    settings: Settings,
    *,
    attempts: int = 5,
    delay_seconds: float = 3.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> str:
    """Probe the user-scoping contract and log the result. Never raises.

    Retries ONLY while the result is ``"unknown"`` (LiteLLM not reachable yet at
    boot); stops on the first definitive ``"enforced"``/``"not_enforced"``. Returns
    the final status. Designed to run as a background task so a slow LiteLLM boot
    never delays serving.
    """
    if not settings.litellm_user_scoping_check:
        logger.info(
            "LiteLLM user-scoping contract check disabled (LITELLM_USER_SCOPING_CHECK=false)"
        )
        return "disabled"

    status = "unknown"
    for attempt in range(1, attempts + 1):
        try:
            status = await verify_user_scoping_contract(settings)
        except Exception:  # defensive: the probe shouldn't raise, but never crash startup
            logger.exception("user-scoping contract probe errored")
            status = "unknown"
        if status != "unknown":
            break
        if attempt < attempts:
            await sleep(delay_seconds)

    if status == "enforced":
        logger.info("LiteLLM user-scoping contract enforced (sso_key_swapper active).")
    elif status == "not_enforced":
        _log_not_enforced()
    else:
        logger.warning(
            "Could not verify the LiteLLM user-scoping contract after %d attempt(s) "
            "(backend unreachable / 5xx). Per-user scoping is unverified.",
            attempts,
        )
    return status
