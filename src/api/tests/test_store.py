# SPDX-License-Identifier: Apache-2.0
import logging

from app.store import MemoryStore


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
    import app.store as store_module

    now = [1000.0]
    monkeypatch.setattr(store_module.time, "time", lambda: now[0])
    store = MemoryStore()
    await store.put("code", "k", {"a": 1}, ttl=10)
    now[0] = 1009.0
    assert await store.get("code", "k") == {"a": 1}
    now[0] = 1011.0
    assert await store.get("code", "k") is None


async def test_acquire_is_exclusive_until_released_or_expired(monkeypatch):
    import app.store as store_module

    now = [1000.0]
    monkeypatch.setattr(store_module.time, "time", lambda: now[0])
    store = MemoryStore()
    assert await store.acquire("mint:u", ttl=10) is True
    assert await store.acquire("mint:u", ttl=10) is False
    await store.release("mint:u")
    assert await store.acquire("mint:u", ttl=10) is True
    now[0] = 1011.0
    assert await store.acquire("mint:u", ttl=10) is True


def test_create_store_memory_sentinel_is_loud(caplog):
    from app.store import create_store

    class Settings:
        as_redis_url = "memory://"

    with caplog.at_level(logging.CRITICAL):
        assert isinstance(create_store(Settings()), MemoryStore)
    assert "memory://" in caplog.text


def test_create_store_uses_redis_otherwise():
    from app.store import RedisStore, create_store

    class Settings:
        as_redis_url = "redis://localhost:6379/0"

    assert isinstance(create_store(Settings()), RedisStore)
