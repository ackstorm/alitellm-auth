# SPDX-License-Identifier: Apache-2.0
"""Which MCP services does a user hold a grant for?

Read from the pods' own cleartext projection (mcp-oauth failure mode 20):
`oauth:{store}:state:{email}` = {"granted": bool, …}. No decryption, no
credentials, one GET per service. This is what turns into `scope` on a token.

The key's `{email}` is the identity the pod resolved for the request. Through
the front door that is the LiteLLM `user_id` of the user's front key -- the same
lowercased `sub` we mint that key for -- so the key we read and the key the pod
wrote agree by construction. A grant stored under a differently-cased email (a
console key from before the front door) is invisible here; all 14 projection
keys in production were lowercase on 2026-09-17.
"""

from __future__ import annotations

import json
from typing import Any


class Grants:
    def __init__(self, redis: Any, services: dict[str, dict]) -> None:
        self._r = redis
        self._services = services

    async def granted(self, email: str, scope: str) -> bool:
        svc = self._services.get(scope)
        if svc is None:
            return False
        raw = await self._r.get(f"oauth:{svc['store']}:state:{email}")
        if not raw:
            return False
        try:
            return bool(json.loads(raw).get("granted"))
        except (ValueError, AttributeError):
            return False

    async def scopes_for(self, email: str, requested: list[str], audience: str) -> list[str]:
        out = [audience]
        for s in requested:
            if s != audience and await self.granted(email, s):
                out.append(s)
        return out


class _Empty:
    async def get(self, _key):
        return None


def create_grants(settings: Any) -> Grants:
    url = settings.as_mcp_redis_url or settings.as_redis_url
    if url == "memory://":
        return Grants(_Empty(), settings.services)
    import redis.asyncio as redis  # lazy import; production path needs Redis

    return Grants(redis.from_url(url, decode_responses=True), settings.services)
