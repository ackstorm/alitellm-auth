# SPDX-License-Identifier: Apache-2.0
from app.oauth_as.store import MemoryStore


async def test_put_get_pop_roundtrip():
    store = MemoryStore()
    await store.put("code", "abc", {"sub": "u@x"})
    assert await store.get("code", "abc") == {"sub": "u@x"}
    assert await store.pop("code", "abc") == {"sub": "u@x"}
    assert await store.get("code", "abc") is None


async def test_kinds_are_separate_namespaces():
    store = MemoryStore()
    await store.put("code", "k", {"a": 1})
    assert await store.get("client", "k") is None


async def test_ttl_expires(monkeypatch):
    import app.oauth_as.store as store_module

    now = [1000.0]
    monkeypatch.setattr(store_module.time, "time", lambda: now[0])
    store = MemoryStore()
    await store.put("code", "k", {"a": 1}, ttl=10)
    now[0] = 1009.0
    assert await store.get("code", "k") == {"a": 1}
    now[0] = 1011.0
    assert await store.get("code", "k") is None


def test_create_store_picks_memory_without_redis_url():
    from app.oauth_as.store import create_store

    class Settings:
        as_redis_url = ""

    assert isinstance(create_store(Settings()), MemoryStore)
