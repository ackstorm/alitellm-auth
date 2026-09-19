# SPDX-License-Identifier: Apache-2.0
"""Key/value store for the OpenWork Den's transient state: single-use sign-in
grants and desktop session tokens. Ported from mcp-oauth/auth/broker.py: three
verbs, JSON-in-Redis shape.

MemoryStore is for tests and a one-replica dev box. Two replicas on it means a
grant minted on one is unknown on the other, and a restart drops every desktop
session. Settings refuse to enable OpenWork without AS_REDIS_URL for that reason.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Protocol

logger = logging.getLogger(__name__)
_PREFIX = "alitellm-auth:as"


class Store(Protocol):
    async def get(self, kind: str, key: str) -> dict | None: ...

    async def put(self, kind: str, key: str, value: dict, ttl: int | None = None) -> None: ...

    async def pop(self, kind: str, key: str) -> dict | None: ...

    async def acquire(self, name: str, ttl: int) -> bool: ...

    async def release(self, name: str) -> None: ...


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

    async def acquire(self, name: str, ttl: int) -> bool:
        self._expire("lock")
        if name in self._bucket("lock"):
            return False
        await self.put("lock", name, {}, ttl=ttl)
        return True

    async def release(self, name: str) -> None:
        self._bucket("lock").pop(name, None)


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

    async def acquire(self, name: str, ttl: int) -> bool:
        return bool(await self._r.set(self._key("lock", name), "1", ex=ttl, nx=True))

    async def release(self, name: str) -> None:
        await self._r.delete(self._key("lock", name))


def create_store(settings: Any) -> Store:
    if settings.as_redis_url == "memory://":
        logger.critical(
            "AS_REDIS_URL=memory://: desktop sessions will NOT survive a restart — dev/test only"
        )
        return MemoryStore()
    import redis.asyncio as redis  # lazy import; production path needs Redis

    return RedisStore(redis.from_url(settings.as_redis_url, decode_responses=True))
