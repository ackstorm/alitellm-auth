# SPDX-License-Identifier: Apache-2.0
"""Mock LiteLLM admin API for the local dev stack.

Serves canned responses for every endpoint the alitellm-auth backend
(src/api/app/litellm_client.py) calls, so a developer can run the WHOLE app
end-to-end with no real LiteLLM proxy.

Data sources:
  - /app/repo-fixtures/*.json  → the repo's src/api/tests/fixtures (bind-mounted RO)
  - /app/fixtures/keys.json    → synthetic virtual keys for the mock user

The mock user is alice@example.com (matches user_info.json + keys.json metadata).
Every key/user lives in team-platform (team-{OAUTH_CLIENT_ID}, client_id=platform).

This is DEV TOOLING. It is intentionally permissive and stateful in-memory only.
"""

from __future__ import annotations

import copy
import json
import logging
import random
import string
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s mock-litellm %(message)s")
log = logging.getLogger("mock-litellm")

MOCK_EMAIL = "alice@example.com"
MOCK_NAME = "Mock User"
TEAM_ID = "team-platform"

REPO_FIXTURES = Path("/app/repo-fixtures")
LOCAL_FIXTURES = Path("/app/fixtures")


def _load(path: Path) -> Any:
    return json.loads(path.read_text())


# ── In-memory state ─────────────────────────────────────────────────────────
# Seed the key list from the local fixture; /key/generate appends, /key/delete removes.
_KEYS: list[dict] = _load(LOCAL_FIXTURES / "keys.json")

# Repo fixtures (canned LiteLLM responses).
_DAILY_CURRENT: dict = _load(REPO_FIXTURES / "daily_activity_current.json")
_DAILY_PRIOR: dict = _load(REPO_FIXTURES / "daily_activity_prior.json")
_SPEND_LOGS: list = _load(REPO_FIXTURES / "spend_logs_rows.json")

# The repo user_info.json is a structured test fixture (with_budget / null_budget),
# not a raw /user/info response. Build a coherent user object for the mock user that
# yields a populated /me (real max_budget + non-zero spend → spend.source="user").
_MOCK_USER = {
    "user_id": MOCK_EMAIL,
    "user_email": MOCK_EMAIL,
    "user_alias": MOCK_NAME,
    "user_role": "internal_user",
    "max_budget": 50.0,
    "spend": 15.935,
    "budget_duration": "30d",
    "tpm_limit": 1000000,
    "rpm_limit": 100,
    "max_parallel_requests": None,
    "models": [],
    "teams": [{"team_id": TEAM_ID, "team_alias": "platform"}],
    "created_at": "2026-03-30T16:40:37.106000Z",
    "metadata": {"email": MOCK_EMAIL, "name": MOCK_NAME},
}

app = FastAPI(title="mock-litellm")


@app.middleware("http")
async def _log_requests(request: Request, call_next):
    log.info("%s %s?%s", request.method, request.url.path, request.url.query)
    return await call_next(request)


def _rand_sk() -> str:
    return "sk-mock-" + "".join(random.choices(string.ascii_letters + string.digits, k=24))


# ── User lifecycle ──────────────────────────────────────────────────────────


@app.get("/user/info")
async def user_info(user_id: str | None = None):
    # Always return the mock user (never the v1.83 default_user_id placeholder, H1).
    return {"user_id": user_id or MOCK_EMAIL, "user_info": copy.deepcopy(_MOCK_USER)}


@app.get("/user/list")
async def user_list(user_email: str | None = None, page: int = 1, page_size: int = 100):
    return {"users": [copy.deepcopy(_MOCK_USER)]}


@app.post("/user/new")
async def user_new(request: Request):
    body = await _json(request)
    return {**copy.deepcopy(_MOCK_USER), "user_id": body.get("user_id", MOCK_EMAIL)}


@app.post("/user/update")
async def user_update(request: Request):
    await _json(request)
    return {"status": "updated"}


@app.post("/user/delete")
async def user_delete(request: Request):
    await _json(request)
    return {"status": "deleted"}


# ── Team lifecycle ──────────────────────────────────────────────────────────


@app.post("/team/new")
async def team_new(request: Request):
    body = await _json(request)
    return {"team_id": body.get("team_id", TEAM_ID), "team_alias": body.get("team_alias")}


@app.post("/team/member_add")
async def team_member_add(request: Request):
    await _json(request)
    return {"team_id": TEAM_ID, "updated_users": []}


@app.post("/team/member_update")
async def team_member_update(request: Request):
    await _json(request)
    return {"team_id": TEAM_ID}


# ── Access groups ───────────────────────────────────────────────────────────

_ACCESS_GROUP = {"access_group_id": "ag-mock-platform", "access_group_name": "platform"}


@app.post("/v1/access_group")
async def access_group_new(request: Request):
    await _json(request)
    return dict(_ACCESS_GROUP)


@app.get("/v1/access_group")
async def access_group_list():
    return [dict(_ACCESS_GROUP)]


# ── Keys ────────────────────────────────────────────────────────────────────


@app.get("/key/list")
async def key_list(
    user_id: str | None = None,
    team_id: str | None = None,
    return_full_object: bool = False,
    size: int = 100,
):
    # Return full objects; the backend filters client-side by metadata.email/team.
    return {"keys": [copy.deepcopy(k) for k in _KEYS]}


@app.get("/key/info")
async def key_info(key: str | None = None):
    for k in _KEYS:
        if k.get("token") == key or k.get("key") == key:
            return {"info": copy.deepcopy(k)}
    # Unknown key → 404 (auth.py maps to 401).
    return JSONResponse({"error": {"message": "key not found"}}, status_code=404)


@app.post("/key/generate")
async def key_generate(request: Request):
    body = await _json(request)
    now = datetime.now(timezone.utc).isoformat()
    alias = body.get("key_alias") or f"key-{now}"
    sk = _rand_sk()
    new_key = {
        "token": sk,
        "key": sk,
        "key_alias": alias,
        "user_id": body.get("user_id", MOCK_EMAIL),
        "team_id": TEAM_ID,
        "spend": 0.0,
        "tpm_limit": 1000000,
        "rpm_limit": 100,
        "max_budget": None,
        "budget_duration": None,
        "models": body.get("models", ["all-team-models"]),
        "expires": None,
        "created_at": now,
        "metadata": body.get("metadata")
        or {
            "email": MOCK_EMAIL,
            "name": MOCK_NAME,
            "source": "token-factory",
            "created_at": now,
            "key_alias": alias,
        },
    }
    _KEYS.append(new_key)
    return {
        "key": sk,
        "token": sk,
        "key_alias": alias,
        "team_id": TEAM_ID,
        "user_id": new_key["user_id"],
        "expires": None,
        "models": new_key["models"],
        "metadata": new_key["metadata"],
    }


@app.post("/key/delete")
async def key_delete(request: Request):
    body = await _json(request)
    targets = set(body.get("keys", []))
    before = len(_KEYS)
    _KEYS[:] = [k for k in _KEYS if k.get("token") not in targets and k.get("key") not in targets]
    log.info("key/delete removed %d key(s)", before - len(_KEYS))
    return {"deleted_keys": list(targets)}


# ── Usage / spend ───────────────────────────────────────────────────────────


@app.get("/user/daily/activity")
async def daily_activity(
    user_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    page: int = 1,
    page_size: int = 100,
):
    # /stats fires the current (recent) + prior (older) windows CONCURRENTLY, so we
    # cannot rely on arrival order. Decide purely from the dates: the current window's
    # end_date is at/near today; the prior window's end_date sits a full span earlier.
    # Serve the prior fixture for any window whose end_date is meaningfully older than
    # today (> half its own span), the current fixture otherwise. Fully deterministic
    # and order-independent → non-trivial period-over-period deltas.
    fixture = _DAILY_CURRENT
    if start_date and end_date:
        try:
            sd = date.fromisoformat(start_date)
            ed = date.fromisoformat(end_date)
            span = (ed - sd).days + 1
            today = datetime.now(timezone.utc).date()
            if (today - ed).days > span / 2:
                fixture = _DAILY_PRIOR
        except ValueError:
            pass
    out = copy.deepcopy(fixture)
    # Always force has_more=false so the backend's page loop terminates after one page.
    out.setdefault("metadata", {})["has_more"] = False
    out["metadata"]["page"] = 1
    out["metadata"]["total_pages"] = 1
    return out


@app.get("/spend/logs")
async def spend_logs(
    user_id: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    summarize: str | None = None,
):
    return copy.deepcopy(_SPEND_LOGS)


# ── Helpers + catch-all ─────────────────────────────────────────────────────


async def _json(request: Request) -> dict:
    try:
        return await request.json()
    except Exception:
        return {}


@app.get("/health")
async def health():
    return {"status": "ok", "keys": len(_KEYS)}


@app.api_route("/{path:path}", methods=["GET", "POST"])
async def catch_all(path: str, request: Request):
    log.warning("UNHANDLED %s /%s", request.method, path)
    return JSONResponse({"status": "ok", "unhandled": path}, status_code=200)
