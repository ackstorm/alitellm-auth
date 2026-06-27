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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

logging.basicConfig(level=logging.INFO, format="%(asctime)s mock-litellm %(message)s")
log = logging.getLogger("mock-litellm")

MOCK_EMAIL = "alice@example.com"
MOCK_NAME = "Mock User"
TEAM_ID = "team-platform"

# Multi-team membership for the mock user so the /ui team picker, the keys-table
# Team column, and the dashboard Team tile show >1 team locally. /user/info and
# /team/list both read this single source of truth.
_TEAMS = [
    {"team_id": TEAM_ID, "team_alias": "platform"},
    {"team_id": "run", "team_alias": "Run Squad"},
    {"team_id": "dream", "team_alias": "Dream Team"},
]

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
    "teams": copy.deepcopy(_TEAMS),
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


@app.get("/team/list")
async def team_list():
    # list_user_teams resolves member team_id → team_alias from here.
    return copy.deepcopy(_TEAMS)


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
    # Honor a caller-chosen team_id (multi-team create); default to TEAM_ID.
    team_id = body.get("team_id") or TEAM_ID
    new_key = {
        "token": sk,
        "key": sk,
        "key_alias": alias,
        "user_id": body.get("user_id", MOCK_EMAIL),
        "team_id": team_id,
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
        "team_id": team_id,
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


@app.post("/key/update")
async def key_update(request: Request):
    body = await _json(request)
    token = body.get("key")
    # Update ONLY the fields present in the body (mirrors real /key/update). The
    # change-team call sends {key, team_id} with NO metadata — must not wipe it.
    updated = None
    for k in _KEYS:
        if k.get("token") == token or k.get("key") == token:
            updated = k
            if "metadata" in body:
                k["metadata"] = body["metadata"]
            if "team_id" in body:
                k["team_id"] = body["team_id"]
            break
    log.info(
        "key/update token=%s team_id=%s is_default=%s (%s)",
        token,
        body.get("team_id"),
        (body.get("metadata") or {}).get("is_default"),
        "ok" if updated else "not-found",
    )
    return updated or {"key": token, **{k: v for k, v in body.items() if k != "key"}}


def _set_key_blocked(token: str | None, blocked: bool) -> dict | None:
    """Flip the in-memory key's `blocked` flag (mirrors /key/block | /key/unblock)."""
    for k in _KEYS:
        if k.get("token") == token or k.get("key") == token:
            k["blocked"] = blocked
            return k
    return None


@app.post("/key/block")
async def key_block(request: Request):
    token = (await _json(request)).get("key")
    updated = _set_key_blocked(token, True)
    log.info("key/block token=%s (%s)", token, "ok" if updated else "not-found")
    return updated or {"key": token, "blocked": True}


@app.post("/key/unblock")
async def key_unblock(request: Request):
    token = (await _json(request)).get("key")
    updated = _set_key_blocked(token, False)
    log.info("key/unblock token=%s (%s)", token, "ok" if updated else "not-found")
    return updated or {"key": token, "blocked": False}


# ── Usage / spend ───────────────────────────────────────────────────────────

# The repo fixtures carry a SINGLE day. For a usable dev chart we expand that one
# day's shape across the whole requested window, varying each day's metrics by a
# deterministic factor so the line/bar charts show real movement (not one point).
_MAX_MOCK_DAYS = 92  # payload cap for very wide custom ranges


def _scale_metrics(node: Any, f: float) -> None:
    """Recursively scale every numeric metric leaf in a day node IN PLACE by ``f``.

    Ints (tokens / requests) round to a non-negative int; floats (spend) scale as
    floats. Bools and strings (``date``, null ``key_alias``) are left untouched.
    Every numeric leaf in a day node is a metric, so a blanket walk is safe.
    """
    if isinstance(node, dict):
        for k, v in node.items():
            if isinstance(v, (dict, list)):
                _scale_metrics(v, f)
            elif isinstance(v, bool):
                continue
            elif isinstance(v, int):
                node[k] = max(0, round(v * f))
            elif isinstance(v, float):
                node[k] = v * f
    elif isinstance(node, list):
        for item in node:
            _scale_metrics(item, f)


def _expand_days(fixture: dict, start_date: str | None, end_date: str | None) -> dict:
    """Replicate the fixture's single template day across [start_date, end_date].

    Returns the fixture unchanged when no/invalid window or no template day. The
    metadata ``total_*`` are recomputed as the SUM of the generated per-day metrics
    so the KPI headline matches the chart series.
    """
    results_tmpl = fixture.get("results") or []
    if not results_tmpl or not (start_date and end_date):
        return copy.deepcopy(fixture)
    try:
        sd = date.fromisoformat(start_date)
        ed = date.fromisoformat(end_date)
    except ValueError:
        return copy.deepcopy(fixture)
    if ed < sd:
        sd, ed = ed, sd
    span = min((ed - sd).days + 1, _MAX_MOCK_DAYS)
    template = results_tmpl[0]

    results: list[dict] = []
    totals = {
        "total_spend": 0.0,
        "total_prompt_tokens": 0,
        "total_completion_tokens": 0,
        "total_tokens": 0,
        "total_api_requests": 0,
        "total_successful_requests": 0,
        "total_failed_requests": 0,
        "total_cache_read_input_tokens": 0,
        "total_cache_creation_input_tokens": 0,
    }
    for i in range(span):
        # Deterministic jagged factor in [0.2, 2.0] → a visibly varied chart.
        f = ((i * 7 + 3) % 10 + 1) / 5.0
        day = copy.deepcopy(template)
        day["date"] = (sd + timedelta(days=i)).isoformat()
        _scale_metrics(day, f)
        results.append(day)
        m = day.get("metrics") or {}
        # DEV-ONLY synthetic signals so the Stats "failed requests" + "cached
        # input" UI is visible on localhost — the LOCKED repo fixtures carry 0 for
        # both (never edited). Deterministic per day; mutating `m` (a reference to
        # day["metrics"]) also feeds the per-day series, and the sums below roll up
        # into metadata.total_*.
        reqs = int(m.get("api_requests", 0) or 0)
        prompt = int(m.get("prompt_tokens", 0) or 0)
        m["failed_requests"] = max(0, round(reqs * 0.06))  # ~6% failed
        m["successful_requests"] = max(0, reqs - m["failed_requests"])
        m["cache_read_input_tokens"] = round(prompt * 0.4)  # ~40% cached input
        totals["total_spend"] += m.get("spend", 0)
        totals["total_prompt_tokens"] += m.get("prompt_tokens", 0)
        totals["total_completion_tokens"] += m.get("completion_tokens", 0)
        totals["total_tokens"] += m.get("total_tokens", 0)
        totals["total_api_requests"] += m.get("api_requests", 0)
        totals["total_successful_requests"] += m.get("successful_requests", 0)
        totals["total_failed_requests"] += m.get("failed_requests", 0)
        totals["total_cache_read_input_tokens"] += m.get("cache_read_input_tokens", 0)
        totals["total_cache_creation_input_tokens"] += m.get(
            "cache_creation_input_tokens", 0
        )

    return {"results": results, "metadata": dict(totals)}


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
    out = _expand_days(fixture, start_date, end_date)
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


# ── Model catalog + MCP gateway ───────────────────────────────────────────────
# Canned /model_group/info rows (the public per-alias group view — costs are
# per-token floats, token counts are floats, as real LiteLLM emits).
_MODEL_GROUPS = [
    {
        "model_group": "ackstorm.fast",
        "providers": ["openai"],
        "mode": "chat",
        "max_input_tokens": 128000.0,
        "max_output_tokens": 16384.0,
        "input_cost_per_token": 1.5e-07,
        "output_cost_per_token": 6e-07,
        "supports_vision": True,
        "supports_function_calling": True,
        "supports_reasoning": False,
        "supports_web_search": True,
        "supported_openai_params": ["temperature", "max_tokens", "stream", "tools"],
    },
    {
        "model_group": "ackstorm.smart",
        "providers": ["anthropic"],
        "mode": "chat",
        "max_input_tokens": 200000.0,
        "max_output_tokens": 64000.0,
        "input_cost_per_token": 3e-06,
        "output_cost_per_token": 1.5e-05,
        "supports_vision": True,
        "supports_function_calling": True,
        "supports_reasoning": True,
        "supports_web_search": True,
        "supported_openai_params": ["temperature", "max_tokens", "stream", "tools"],
    },
    {
        "model_group": "ackstorm.cheap",
        "providers": ["openai"],
        "mode": "chat",
        "max_input_tokens": 128000.0,
        "max_output_tokens": 16384.0,
        "input_cost_per_token": 5e-08,
        "output_cost_per_token": 2e-07,
        "supports_vision": False,
        "supports_function_calling": True,
        "supports_reasoning": False,
        "supports_web_search": False,
        "supported_openai_params": ["temperature", "max_tokens", "stream"],
    },
    {
        "model_group": "ackstorm.reason",
        "providers": ["openai"],
        "mode": "chat",
        "max_input_tokens": 200000.0,
        "max_output_tokens": 100000.0,
        "input_cost_per_token": 1.1e-06,
        "output_cost_per_token": 4.4e-06,
        "supports_vision": True,
        "supports_function_calling": True,
        "supports_reasoning": True,
        "supports_web_search": False,
        "supported_openai_params": ["max_tokens", "stream", "tools", "reasoning_effort"],
    },
    {
        "model_group": "ackstorm.vision",
        "providers": ["google"],
        "mode": "chat",
        "max_input_tokens": 1048576.0,
        "max_output_tokens": 8192.0,
        "input_cost_per_token": 1.25e-07,
        "output_cost_per_token": 5e-07,
        "supports_vision": True,
        "supports_function_calling": True,
        "supports_reasoning": False,
        "supports_web_search": True,
        "supported_openai_params": ["temperature", "max_tokens", "stream", "tools"],
    },
    {
        "model_group": "ackstorm.embed",
        "providers": ["openai"],
        "mode": "embedding",
        "max_input_tokens": 8192.0,
        "max_output_tokens": None,
        "input_cost_per_token": 2e-08,
        "output_cost_per_token": 0.0,
        "supports_vision": False,
        "supports_function_calling": False,
        "supports_reasoning": False,
        "supports_web_search": False,
        "supported_openai_params": ["encoding_format", "dimensions"],
    },
]

# Canned /v1/mcp/server rows. NOTE: each carries `credentials`/`env`/`static_headers`
# ON PURPOSE — the backend projection (_project_mcp_server) MUST strip them, so
# seeding them here proves they never reach the browser.
_MCP_SERVERS = [
    {
        "server_id": "github-mcp",
        "server_name": "github",
        "alias": "GitHub",
        "description": "Repositories, issues, and pull requests.",
        "url": "https://mcp.internal.ackstorm.ai/github",
        "transport": "http",
        "auth_type": "oauth2",
        "status": "healthy",
        "allowed_tools": ["list_repos", "create_issue", "get_pull_request", "search_code"],
        "mcp_access_groups": ["platform"],
        "teams": [{"team_id": TEAM_ID, "team_alias": "platform"}],
        "allow_all_keys": True,
        "credentials": {"api_key": "SHOULD-NOT-LEAK"},
        "env": {"GITHUB_TOKEN": "ghp_SHOULD_NOT_LEAK"},
        "static_headers": {"x-internal": "SHOULD-NOT-LEAK"},
    },
    {
        "server_id": "filesystem-mcp",
        "server_name": "filesystem",
        "alias": "Filesystem",
        "description": "Sandboxed read/write access to a working directory.",
        "url": None,
        "transport": "stdio",
        "auth_type": "none",
        "status": "healthy",
        "allowed_tools": ["read_file", "write_file", "list_directory"],
        "mcp_access_groups": [],
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/data"],
        "env": {"SECRET": "SHOULD-NOT-LEAK"},
    },
    {
        "server_id": "web-search-mcp",
        "server_name": "web-search",
        "alias": "Web Search",
        "description": "Live web search and page fetch.",
        "url": "https://mcp.internal.ackstorm.ai/search",
        "transport": "http",
        "auth_type": "api_key",
        "status": "healthy",
        "allowed_tools": ["search", "fetch_page"],
        "mcp_access_groups": ["platform"],
        "credentials": {"api_key": "SHOULD-NOT-LEAK"},
    },
    {
        "server_id": "postgres-mcp",
        "server_name": "postgres",
        "alias": "Postgres",
        "description": "Read-only SQL over the analytics warehouse.",
        "url": "https://mcp.internal.ackstorm.ai/postgres",
        "transport": "sse",
        "auth_type": "bearer_token",
        "status": "unhealthy",
        "health_check_error": "connection refused",
        "allowed_tools": ["query", "list_tables", "describe_table"],
        "mcp_access_groups": ["data"],
        "credentials": {"token": "SHOULD-NOT-LEAK"},
    },
]


# Canned /v1/agents rows (LiteLLM AgentResponse shape). Display metadata lives in
# `agent_card_params` (the A2A AgentCard). Each carries `litellm_params`/
# `static_headers`/`extra_headers`/`securitySchemes` ON PURPOSE — the backend
# projection (_project_a2a_agent) MUST strip them, so seeding them proves they
# never reach the browser.
_A2A_AGENTS = [
    {
        "agent_id": "research-agent",
        "agent_name": "Research Agent",
        "agent_card_params": {
            "name": "Research Agent",
            "description": "Multi-step web research with inline citations.",
            "url": "https://a2a.internal.ackstorm.ai/research",
            "version": "1.2.0",
            "preferredTransport": "JSONRPC",
            "capabilities": {"streaming": True, "pushNotifications": False},
            "skills": [
                {"id": "deep_research", "name": "deep_research"},
                {"id": "summarize", "name": "summarize"},
                {"id": "cite_sources", "name": "cite_sources"},
            ],
            "securitySchemes": {"oauth2": {"token": "SHOULD-NOT-LEAK"}},
        },
        "litellm_params": {"api_key": "SHOULD-NOT-LEAK"},
        "static_headers": {"x-internal": "SHOULD-NOT-LEAK"},
        "extra_headers": ["x-secret"],
        "spend": 1.2345,
        "created_by": "admin@example.com",
    },
    {
        "agent_id": "coder-agent",
        "agent_name": "Coder Agent",
        "agent_card_params": {
            "name": "Coder Agent",
            "description": "Writes and reviews code changes across a repository.",
            "url": "https://a2a.internal.ackstorm.ai/coder",
            "version": "0.9.1",
            "preferredTransport": "GRPC",
            "capabilities": {"streaming": False},
            "skills": [
                {"id": "write_patch", "name": "write_patch"},
                {"id": "review_pr", "name": "review_pr"},
            ],
        },
        "litellm_params": {"api_key": "SHOULD-NOT-LEAK"},
    },
    {
        "agent_id": "ops-agent",
        "agent_name": "Ops Agent",
        "agent_card_params": {
            "name": "Ops Agent",
            "description": "Runbook automation and incident triage.",
            "url": "https://a2a.internal.ackstorm.ai/ops",
            "version": "2.0.0",
            "preferredTransport": "JSONRPC",
            "capabilities": {"streaming": True},
            "skills": [
                {"id": "triage", "name": "triage"},
                {"id": "rollback", "name": "rollback"},
                {"id": "page_oncall", "name": "page_oncall"},
            ],
        },
    },
]


@app.get("/model_group/info")
async def model_group_info(
    model_group: str | None = None,
    x_user_id: str | None = Header(default=None),
):
    # Real per-user scoping is the deployment's custom auth; the mock just logs
    # the header to prove the x-user-id path is exercised (and must not 500 on it).
    if x_user_id:
        log.info("model_group/info scoped to x-user-id=%s", x_user_id)
    data = [copy.deepcopy(m) for m in _MODEL_GROUPS]
    if model_group:
        data = [m for m in data if m["model_group"] == model_group]
    return {"data": data}


@app.get("/v1/mcp/server")
async def mcp_server_list(
    team_id: str | None = None,
    x_user_id: str | None = Header(default=None),
):
    if x_user_id:
        log.info("v1/mcp/server scoped to x-user-id=%s", x_user_id)
    # Bare JSON array (matches LiteLLM's response_model=List[LiteLLM_MCPServerTable]).
    return [copy.deepcopy(s) for s in _MCP_SERVERS]


@app.get("/v1/agents")
async def a2a_agent_list(
    health_check: bool = False,
    x_user_id: str | None = Header(default=None),
):
    if x_user_id:
        log.info("v1/agents scoped to x-user-id=%s", x_user_id)
    # Bare JSON array (matches LiteLLM's response_model=List[AgentResponse]).
    return [copy.deepcopy(a) for a in _A2A_AGENTS]


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
