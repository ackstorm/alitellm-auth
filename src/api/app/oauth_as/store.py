# SPDX-License-Identifier: Apache-2.0
"""Key/value store for the authorization server's transient state.

Four kinds live here: `client` (DCR registrations, no TTL), `pending` (an
/authorize request waiting for Dex, 10 min), `code` (an authorization code,
2 min, single use), `refresh` (a refresh token, rotated on use) and `frontkey`
(the user's encrypted LiteLLM key, Task 9). Ported from mcp-oauth/auth/broker.py:
same three verbs, same JSON-in-Redis shape.

MemoryStore is for one replica and dev. Two replicas with MemoryStore means a
code minted on one is unknown on the other — a 50% failure rate that looks like
flakiness. Set AS_REDIS_URL for anything with replicaCount > 1.
"""

from __future__ import annotations

import json
import time
from typing import Any, Protocol

_PREFIX = "alitellm-auth:as"


class Store(Protocol):
    async def get(self, kind: str, key: str) -> dict | None: ...

    async def put(self, kind: str, key: str, value: dict, ttl: int | None = None) -> None: ...

    async def pop(self, kind: str, key: str) -> dict | None: ...


class MemoryStore:
    def __init__(self) -> None:
        self._data: dict[str, dict[str, tuple[dict, float | None]]] = {}

    def _bucket(self, kind: str) -> dict[str, tuple[dict, float | None]]:
        return self._data.setdefault(kind, {})

    def _expire(self, kind: str) -> None:
        now = time.time()
        bucket = self._bucket(kind)
        for key in [key for key, (_, exp) in bucket.items() if exp is not None and exp <= now]:
            del bucket[key]

    async def get(self, kind: str, key: str) -> dict | None:
        self._expire(kind)
        hit = self._bucket(kind).get(key)
        return dict(hit[0]) if hit else None

    async def put(self, kind: str, key: str, value: dict, ttl: int | None = None) -> None:
        exp = time.time() + ttl if ttl is not None else None
        self._bucket(kind)[key] = (dict(value), exp)

    async def pop(self, kind: str, key: str) -> dict | None:
        self._expire(kind)
        hit = self._bucket(kind).pop(key, None)
        return dict(hit[0]) if hit else None


class RedisStore:
    def __init__(self, client: Any) -> None:
        self._r = client

    @staticmethod
    def _key(kind: str, key: str) -> str:
        return f"{_PREFIX}:{kind}:{key}"

    async def get(self, kind: str, key: str) -> dict | None:
        raw = await self._r.get(self._key(kind, key))
        return json.loads(raw) if raw else None

    async def put(self, kind: str, key: str, value: dict, ttl: int | None = None) -> None:
        await self._r.set(self._key(kind, key), json.dumps(value), ex=ttl)

    async def pop(self, kind: str, key: str) -> dict | None:
        raw = await self._r.getdel(self._key(kind, key))  # atomic single use
        return json.loads(raw) if raw else None


def create_store(settings: Any) -> Store:
    if settings.as_redis_url:
        import redis.asyncio as redis  # lazy import; memory path does not need Redis

        return RedisStore(redis.from_url(settings.as_redis_url, decode_responses=True))
    return MemoryStore()
