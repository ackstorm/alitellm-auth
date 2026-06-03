# SPDX-License-Identifier: Apache-2.0
"""One-time idempotent budget backfill CLI.

Finds all existing LiteLLM users whose factory budget fields (max_budget,
budget_duration, tpm_limit, rpm_limit, max_parallel_requests) are None/missing
and patches ONLY those absent fields via /user/update.  Users with any of these
fields already set are left untouched — manual values are never overwritten.

This is the complement to the D-16 lazy backfill (which fires on login).  Run
this once to backfill Phase-2/3-era users who have never logged in since the
factory config was applied.

Usage (dry-run, no writes — the default):
    cd src/api && .venv/bin/python ../../scripts/backfill_user_budgets.py

Inspect + apply:
    cd src/api && .venv/bin/python ../../scripts/backfill_user_budgets.py --apply

Required environment variables (same as the running service):
    LITELLM_URL, LITELLM_MASTER_KEY, SESSION_SECRET_KEY,
    OAUTH_ISSUER_URL, OAUTH_CLIENT_ID, OAUTH_CLIENT_SECRET
    FACTORY_CONFIG_PATH (optional — path to factory-config.json)

The script is GATED: it never runs automatically and performs no writes without
the explicit --apply flag.
"""

from __future__ import annotations

import argparse
import asyncio
import sys


# ---------------------------------------------------------------------------
# argparse MUST be resolved before any Settings() instantiation so that
# `--help` exits 0 even when env vars are not set (M-3 requirement).
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill missing factory budget fields (max_budget, budget_duration, "
            "tpm_limit, rpm_limit, max_parallel_requests) on existing LiteLLM users. "
            "Dry-run by default — add --apply to write changes."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        default=False,
        help=(
            "Write changes via /user/update.  Without this flag the script only "
            "PRINTS which users and fields would be updated (dry-run, no writes)."
        ),
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="Print all users, not just those needing a backfill.",
    )
    return parser


# Parse args early — before any import that could trigger Settings() validation.
_PARSER = _build_arg_parser()
_ARGS = _PARSER.parse_args()

# ---------------------------------------------------------------------------
# Now it is safe to import app.* (Settings will be instantiated inside main).
# sys.path is already correct when the script is run as:
#   cd src/api && .venv/bin/python ../../scripts/backfill_user_budgets.py
# because Python prepends the invocation directory (src/api) to sys.path.
# ---------------------------------------------------------------------------

import httpx  # noqa: E402 — after arg parse to keep --help clean
import logging  # noqa: E402

from app.config import Settings  # noqa: E402
from app.litellm_client import (  # noqa: E402
    _admin_headers,
    _load_factory_config,
    list_litellm_users,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)

# The five factory budget fields that the D-16 lazy backfill monitors.
# This MUST match the field set used in ensure_team_and_user's backfill block
# (src/api/app/litellm_client.py) so that this script and the on-login backfill
# are consistent.
FACTORY_BUDGET_FIELDS = (
    "max_budget",
    "budget_duration",
    "tpm_limit",
    "rpm_limit",
    "max_parallel_requests",
)


async def _update_user(
    user_id: str,
    missing: dict,
    settings: Settings,
) -> None:
    """POST /user/update with only the missing fields.

    Mirrors the POST-and-raise error convention used by delete_litellm_user
    (litellm_client.py lines 611-622).  H3: never send null values — caller
    must guarantee missing contains only non-None values.
    """
    headers = _admin_headers(settings)
    async with httpx.AsyncClient(base_url=settings.litellm_url, timeout=30.0) as client:
        resp = await client.post(
            "/user/update",
            headers=headers,
            json={"user_id": user_id, **missing},
        )
    if not resp.is_success:
        try:
            err = resp.json()
            msg = (
                err.get("detail")
                or err.get("message")
                or (err.get("error", {}) or {}).get("message")
                or resp.text
            )
        except Exception:
            msg = resp.text
        raise httpx.HTTPStatusError(
            f"LiteLLM /user/update failed ({resp.status_code}): {msg}",
            request=resp.request,
            response=resp,
        )


async def main(args: argparse.Namespace) -> int:
    """Run the backfill.

    Returns exit code (0 = success, 1 = partial failure).
    """
    settings = Settings()

    factory = _load_factory_config(settings.factory_config_path)
    factory_user = factory.get("user", {})

    # Build the target budget dict: only non-None factory values for the five
    # monitored fields (H3: never send null; never include other factory keys).
    target: dict = {
        field: factory_user[field]
        for field in FACTORY_BUDGET_FIELDS
        if field in factory_user and factory_user[field] is not None
    }

    if not target:
        logger.warning(
            "Factory config provides no budget fields for the 'user' block "
            "(FACTORY_CONFIG_PATH=%s).  Nothing to backfill.",
            settings.factory_config_path,
        )
        return 0

    logger.info(
        "Factory target fields: %s",
        {k: target[k] for k in target},
    )

    users = await list_litellm_users(settings)
    logger.info("Fetched %d users from LiteLLM.", len(users))

    needs_update: list[tuple[str, dict]] = []

    for user in users:
        user_id = user.get("user_id") or user.get("email") or ""
        if not user_id:
            logger.warning("Skipping user with no user_id: %r", user)
            continue

        # Find fields that are None/missing on this user AND present in factory target.
        # H3: we never include a field if the user already has it set (even to 0 — a
        # zero budget is a deliberately-set value, not "missing").
        missing = {
            field: value
            for field, value in target.items()
            if user.get(field) is None
        }

        if missing:
            needs_update.append((user_id, missing))
            if args.verbose or True:  # always print affected users
                print(
                    f"  [NEEDS BACKFILL] user_id={user_id!r}  "
                    f"missing fields: {list(missing.keys())}"
                )
        elif args.verbose:
            print(f"  [OK] user_id={user_id!r}  all factory fields already set")

    if not needs_update:
        print("No users need a budget backfill.  Nothing to do.")
        return 0

    mode = "--apply" if args.apply else "DRY-RUN"
    print(
        f"\n{mode}: {len(needs_update)} user(s) out of {len(users)} need a budget backfill."
    )

    if not args.apply:
        print(
            "\nDry-run complete.  Re-run with --apply to write changes.\n"
            "No LiteLLM /user/update calls were made."
        )
        return 0

    # --apply: patch only the missing fields for each user.
    errors = 0
    updated = 0
    for user_id, missing in needs_update:
        try:
            await _update_user(user_id, missing, settings)
            logger.info("Backfilled user %r with fields %s", user_id, list(missing.keys()))
            updated += 1
        except httpx.HTTPStatusError as exc:
            logger.error("Failed to backfill user %r: %s", user_id, exc)
            errors += 1

    print(f"\nBackfill complete: {updated} updated, {errors} failed.")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(_ARGS)))
