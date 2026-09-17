# Task 2 report: Memory and Redis store

## Changes

- Added `app.oauth_as.store` with a `Store` protocol, TTL-aware `MemoryStore`, JSON-backed `RedisStore`, atomic single-use `pop()` via Redis `GETDEL`, and lazy Redis client construction in `create_store()`.
- Added the OAuth AS package initializer and four planned tests for round trips, namespace separation, expiration, and memory selection without a Redis URL.
- Added `redis>=5.0.0` and `cryptography>=43.0.0` to the API dependencies and regenerated `src/api/uv.lock`. The lockfile is ignored by the repository `.gitignore`, so it is explicitly included in the task commit.

## Verification

Command: `cd src/api && uv run pytest tests/test_oauth_as_store.py -v`
Result: 4 passed.

`git diff --check` also completed without errors.

## Review notes

The MemoryStore copies values on write/read/pop to avoid handing callers its stored top-level dictionary. Redis `pop()` uses `GETDEL` so consuming a code is atomic. Redis construction remains lazy and the no-Redis path does not import the Redis client.

No known concerns for this task. Multi-replica deployments must configure `AS_REDIS_URL`, as documented by the store module.

## Canonical revision 2 follow-up

Added `acquire`/`release` to the store protocol and both backends. Memory locks expire with TTL; Redis locks use `SET NX` with expiry and release with `DELETE`. `create_store()` now accepts only the explicit `memory://` sentinel for in-memory operation and logs at CRITICAL; other values use Redis, so an empty URL cannot silently choose memory. Added the planned lock, sentinel, and Redis-construction tests.

Verification: `uv run pytest tests/test_oauth_as_store.py -v` — 6 passed. `uv run ruff check app/oauth_as/store.py tests/test_oauth_as_store.py` — all checks passed. `git diff --check` — clean.
