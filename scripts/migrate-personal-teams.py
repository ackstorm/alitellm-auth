#!/usr/bin/env python3
"""Move existing token-factory keys into their owner's personal team.

Dry run is the default. Nothing is written without --apply.

Run `./scripts/migrate-personal-teams.py --help` for the ownership rules and
the one consequence you must understand before running it with --apply.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import httpx

DENY_ALL_MODEL = "__deny_all__"
DENY_ALL_AGENT = "00000000-0000-0000-0000-000000000000"
TEAM_METADATA = {"source": "token-factory", "alt_managed": "user-team"}
ACH_KEY_PREFIXES = ("pkid_", "ekid_")
ACH_TEAM_PREFIX = "ach-"

EPILOG = """
WHAT IT DOES
  For every virtual key this service minted, ensures the owner's personal team
  exists (created CLOSED: models=[__deny_all__], deny-all object_permission)
  and then POST /key/update to move the key into it.

  It does NOT attach access groups. The service attaches them on the user's
  next login. A migrated key therefore REACHES NOTHING UNTIL ITS OWNER LOGS IN
  AGAIN. That is the safe direction (fail closed), but it is a user-visible
  outage for anyone using a key without logging in. Plan the announcement.

  A team change reaches a live key in roughly 15-60 seconds, not instantly.

OWNERSHIP RULES (this LiteLLM proxy is shared with the sibling system `ach`)
  MIGRATE      keys with metadata.source == "token-factory"
  NEVER touch  keys whose token or alias starts with pkid_ or ekid_ (ach's)
  NEVER touch  keys currently in a team whose id starts with "ach-" (ach's)
  SKIP         anything ambiguous -- it is reported, not migrated

CONFIG
  LITELLM_URL / --litellm-url            LiteLLM proxy base URL
  LITELLM_MASTER_KEY / --master-key      LiteLLM admin key (never printed)

EXAMPLES
  ./scripts/migrate-personal-teams.py                      # dry run, everyone
  ./scripts/migrate-personal-teams.py --email a@b.com      # dry run, one user
  ./scripts/migrate-personal-teams.py --email a@b.com --apply
  ./scripts/migrate-personal-teams.py --apply --max-budget 100 --budget-duration 30d
"""


# ── helpers ──────────────────────────────────────────────────────────────────


def short(token: str | None) -> str:
    """Never print a full token. Truncate to something greppable but useless."""
    if not token:
        return "<none>"
    return token[:10] + "..." if len(token) > 13 else "<redacted>"


def parse_metadata(raw) -> dict:
    """LiteLLM sometimes hands metadata back as stringified JSON."""
    if isinstance(raw, str):
        try:
            return json.loads(raw) or {}
        except Exception:
            return {}
    return raw if isinstance(raw, dict) else {}


def already_exists(resp: httpx.Response) -> bool:
    """Older LiteLLM answers 409; newer answers 400 + 'already exists' (any casing)."""
    return resp.status_code == 409 or (
        resp.status_code == 400 and "already exists" in resp.text.lower()
    )


# ── LiteLLM calls ────────────────────────────────────────────────────────────


def fetch_keys(client: httpx.Client, email: str | None) -> list:
    """All keys, paginated. return_full_object=true is required for metadata/user_id."""
    # size=100 is a CEILING, not a preference. Measured on v1.99.1: size=50 and
    # size=100 both return all 27 keys, but size=200 returns {"keys": [],
    # "total_count": null} with HTTP 200 and no error at all. Raising this would
    # make the script report "nothing to migrate" and look like a clean no-op.
    rows, page = [], 1
    while page <= 200:  # hard stop; 200 pages x 100 = 20k keys
        params = {"page": page, "size": 100, "return_full_object": "true"}
        if email:
            params["user_id"] = email
        resp = client.get("/key/list", params=params)
        resp.raise_for_status()
        body = resp.json()
        batch = body.get("keys") if isinstance(body, dict) else body
        if not isinstance(batch, list) or not batch:
            break
        rows.extend(batch)
        total_pages = (body or {}).get("total_pages") if isinstance(body, dict) else None
        if total_pages and page >= total_pages:
            break
        if len(batch) < 100:
            break
        page += 1
    return rows


def team_exists(client: httpx.Client, team_id: str) -> bool:
    """/team/info is the ONLY truth. /team/new reports object_permission: null
    even when it applied, and LiteLLM silently accepts a nonexistent team_id on
    /key/update -- the key then fails OPEN. So: confirm, never assume."""
    resp = client.get("/team/info", params={"team_id": team_id})
    return resp.status_code == 200


def create_team(
    client: httpx.Client, team_id: str, max_budget: float | None, budget_duration: str | None
) -> None:
    """Create the personal team CLOSED. Mirrors app.litellm_client.ensure_personal_team
    phase 1 -- deliberately WITHOUT phase 2 (access-group attachment)."""
    payload: dict = {
        "team_id": team_id,
        "team_alias": team_id,
        "models": [DENY_ALL_MODEL],
        "object_permission": {
            "mcp_servers": [],
            "mcp_access_groups": [],
            "agents": [DENY_ALL_AGENT],
            "agent_access_groups": [],
        },
        "metadata": dict(TEAM_METADATA),
    }
    # Budget must land at CREATE time: budget edits do not propagate to live
    # keys on this LiteLLM version. An existing team's budget is never touched.
    if max_budget is not None:
        payload["max_budget"] = max_budget
    if budget_duration:
        payload["budget_duration"] = budget_duration

    resp = client.post("/team/new", json=payload)
    if resp.status_code != 200 and not already_exists(resp):
        raise RuntimeError(f"/team/new {team_id} failed ({resp.status_code}): {resp.text[:300]}")


def model_count(client: httpx.Client, token: str | None) -> int | None:
    """How many models this key can currently see. None = could not read."""
    if not token:
        return None
    try:
        resp = client.get("/v1/models", headers={"Authorization": f"Bearer {token}"})
    except httpx.HTTPError:
        return None
    if resp.status_code != 200:
        return None
    data = resp.json().get("data")
    return len(data) if isinstance(data, list) else None


# ── ownership ────────────────────────────────────────────────────────────────


def classify(row, prefix: str) -> tuple[str | None, str | None]:
    """(destination_team_id, None) to migrate, or (None, skip_reason).

    Conservative by construction: every unrecognised shape falls through to a
    skip. The ach exclusions are checked FIRST so they can never be overridden.
    """
    if not isinstance(row, dict):
        return None, "list did not return a full object (return_full_object ignored?)"

    md = parse_metadata(row.get("metadata"))
    token = row.get("token") or row.get("key") or ""
    aliases = [row.get("key_alias") or "", md.get("key_alias") or "", token]
    if any(a.startswith(ACH_KEY_PREFIXES) for a in aliases if isinstance(a, str)):
        return None, "ach-owned key (pkid_/ekid_ prefix)"

    current = row.get("team_id") or ""
    if isinstance(current, str) and current.startswith(ACH_TEAM_PREFIX):
        return None, f"key sits in an ach-owned team ({current})"

    if md.get("source") != "token-factory":
        return None, f"not minted by this service (metadata.source={md.get('source')!r})"

    user_id = row.get("user_id")
    if not isinstance(user_id, str) or "@" not in user_id:
        return None, f"no usable owner email (user_id={user_id!r})"

    dest = f"{prefix}{user_id.strip().lower()}"
    if dest.startswith(ACH_TEAM_PREFIX):
        return None, f"destination would be an ach-owned team ({dest})"
    if current == dest:
        return None, "already in its personal team"
    return dest, None


# ── main ─────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="migrate-personal-teams.py",
        description="Move existing token-factory keys into their owner's personal team. "
        "Dry run unless --apply is given.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--apply", action="store_true", help="perform the writes (default: dry run)")
    p.add_argument("--email", help="limit to one user's keys")
    p.add_argument("--litellm-url", default=os.environ.get("LITELLM_URL"))
    p.add_argument("--master-key", default=os.environ.get("LITELLM_MASTER_KEY"))
    p.add_argument("--team-prefix", default="user-", help="personal team id prefix (default user-)")
    p.add_argument(
        "--max-budget",
        type=float,
        help="max_budget for teams this run CREATES (existing teams are never touched)",
    )
    p.add_argument(
        "--budget-duration",
        help="budget_duration for teams this run CREATES, e.g. 30d",
    )
    p.add_argument(
        "--settle",
        type=int,
        default=20,
        help="seconds to wait before the after-counts re-read (default 20, 0 to skip)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()
    if not args.litellm_url:
        sys.exit("error: LITELLM_URL is not set (or pass --litellm-url)")
    if not args.master_key:
        sys.exit("error: LITELLM_MASTER_KEY is not set (or pass --master-key)")

    mode = "APPLY -- WRITES WILL HAPPEN" if args.apply else "DRY RUN -- nothing will be written"
    print(f"LiteLLM: {args.litellm_url}")
    print(f"Mode:    {mode}")
    if args.email:
        print(f"Filter:  {args.email}")
    print(
        "\nNOTE: this script does NOT attach access groups. A migrated key\n"
        "      reaches NOTHING until its owner signs in again (the service\n"
        "      attaches groups on login). Team changes also take ~15-60s to\n"
        "      reach a live key -- they are not instant.\n"
    )

    client = httpx.Client(
        base_url=args.litellm_url.rstrip("/"),
        headers={"Authorization": f"Bearer {args.master_key}"},
        timeout=30.0,
    )

    try:
        rows = fetch_keys(client, args.email)
    except httpx.HTTPStatusError as exc:
        return fail(f"LiteLLM /key/list refused the master key ({exc.response.status_code})")
    except httpx.HTTPError as exc:
        return fail(f"could not reach LiteLLM at {args.litellm_url}: {exc}")

    print(f"{len(rows)} key(s) returned by /key/list\n")

    skipped: list[tuple[str, str]] = []
    planned: list[tuple[dict, str]] = []
    known_teams: dict[str, bool] = {}

    for row in rows:
        dest, reason = classify(row, args.team_prefix)
        label = describe(row)
        # classify returns exactly one of the two; assert it so a future edit
        # that returns neither fails here rather than writing team_id=None.
        if reason is not None or dest is None:
            skipped.append((label, reason or "classify returned no destination"))
            continue
        if dest not in known_teams:
            try:
                known_teams[dest] = team_exists(client, dest)
            except httpx.HTTPError as exc:
                skipped.append((label, f"could not check destination team: {exc}"))
                continue
        planned.append((row, dest))

    for row, dest in planned:
        md = parse_metadata(row.get("metadata"))
        print(f"  key   {md.get('key_alias') or row.get('key_alias') or '<no alias>'}")
        print(f"    token   {short(row.get('token'))}")
        print(f"    owner   {row.get('user_id')}")
        print(f"    from    {row.get('team_id') or '<none>'}")
        print(f"    to      {dest}  ({'exists' if known_teams[dest] else 'WILL BE CREATED'})")

    if not args.apply:
        summary(planned, skipped)
        print("\nDry run only. Re-run with --apply to perform the moves.")
        return 0

    print("\n--- applying ---\n")
    moved: list[tuple[str, str, int | None]] = []
    for row, dest in planned:
        md = parse_metadata(row.get("metadata"))
        label = md.get("key_alias") or row.get("key_alias") or short(row.get("token"))
        token = row.get("token")
        # No token means nothing to address the update to. Sending key=null would
        # be a write with an unknown target, so refuse rather than find out.
        if not isinstance(token, str) or not token:
            skipped.append((label, "row carries no token to update"))
            continue
        before = model_count(client, token)

        try:
            if not known_teams[dest]:
                create_team(client, dest, args.max_budget, args.budget_duration)
            # Verify existence regardless of what /team/new claimed: LiteLLM
            # accepts a nonexistent team_id on /key/update and the key then
            # fails OPEN. This check is the whole safety of the operation.
            if not team_exists(client, dest):
                skipped.append((label, f"destination team {dest} not confirmed by /team/info"))
                continue
            known_teams[dest] = True

            resp = client.post("/key/update", json={"key": token, "team_id": dest})
            if not resp.is_success:
                skipped.append(
                    (label, f"/key/update failed ({resp.status_code}): {resp.text[:200]}")
                )
                continue
        except (httpx.HTTPError, RuntimeError) as exc:
            skipped.append((label, f"{type(exc).__name__}: {exc}"))
            continue

        print(f"  moved {label} -> {dest}   (models before: {fmt(before)})")
        moved.append((label, token, before))

    if moved and args.settle > 0:
        print(f"\nWaiting {args.settle}s before re-reading model counts...")
        time.sleep(args.settle)
        print(
            "\nBefore/after model-catalog counts. Propagation takes ~15-60s, so an\n"
            "UNCHANGED number here is NOT yet proof of anything -- re-check later.\n"
            "A count that has already DROPPED to 0 is expected: the personal team is\n"
            "deny-all until the owner signs in again.\n"
        )
        for label, token, before in moved:
            after = model_count(client, token)
            print(f"  {label:<40} {fmt(before)} -> {fmt(after)}")

    summary(planned, skipped, applied=len(moved))
    return 0


def describe(row) -> str:
    if not isinstance(row, dict):
        return f"<non-dict row: {type(row).__name__}>"
    md = parse_metadata(row.get("metadata"))
    return (
        md.get("key_alias")
        or row.get("key_alias")
        or row.get("user_id")
        or short(row.get("token"))
    )


def fmt(n: int | None) -> str:
    return "?" if n is None else str(n)


def summary(planned, skipped, applied: int | None = None) -> None:
    print("\n--- summary ---")
    if applied is None:
        print(f"  would move : {len(planned)}")
    else:
        print(f"  moved      : {applied} of {len(planned)} planned")
    print(f"  skipped    : {len(skipped)}")
    for label, reason in skipped:
        print(f"    - {label}: {reason}")


def fail(msg: str) -> int:
    print(f"error: {msg}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
