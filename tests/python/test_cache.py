from __future__ import annotations

import time

from fastapi.testclient import TestClient

from prest_py.app import create_app
from prest_py.cache.response_cache import ResponseCache
from prest_py.settings.models import Settings


def _settings(**overrides) -> Settings:
    defaults = {
        "app_name": "test-prest",
        "debug": True,
        "http": {"host": "0.0.0.0", "port": 3000, "timeout": 60},
        "pg": {
            "host": "localhost",
            "port": 5432,
            "user": "postgres",
            "pass": "postgres",
            "database": "prest-test",
        },
    }
    defaults.update(overrides)
    return Settings.model_validate(defaults)


# ---------------------------------------------------------------------------
# ResponseCache unit tests
# ---------------------------------------------------------------------------


def test_cache_disabled_does_not_cache():
    cache = ResponseCache(enabled=False, default_ttl_minutes=10)
    assert cache.get("key") is None
    cache.set("key", "value", 10)
    assert cache.get("key") is None


def test_cache_enabled_stores_and_retrieves():
    cache = ResponseCache(enabled=True, default_ttl_minutes=10)
    cache.set("key", "value", 10)
    assert cache.get("key") == "value"


def test_cache_expires_after_ttl():
    cache = ResponseCache(enabled=True, default_ttl_minutes=10)
    # Set with 0 TTL → expires immediately
    cache.set("key", "value", 0)
    assert cache.get("key") is None


def test_cache_expired_entry_removed_on_access():
    cache = ResponseCache(enabled=True, default_ttl_minutes=10)
    # Manually set expired entry
    from prest_py.cache.response_cache import CacheEntry

    cache._store["key"] = CacheEntry(value="old", expires_at=time.time() - 1)
    assert cache.get("key") is None
    assert "key" not in cache._store


def test_cache_clear():
    cache = ResponseCache(enabled=True, default_ttl_minutes=10)
    cache.set("key1", "val1", 10)
    cache.set("key2", "val2", 10)
    assert len(cache) == 2
    cache.clear()
    assert len(cache) == 0


def test_cache_evicts_at_max_entries():
    cache = ResponseCache(enabled=True, default_ttl_minutes=10, max_entries=2)
    cache.set("key1", "val1", 10)
    cache.set("key2", "val2", 10)
    cache.set("key3", "val3", 10)

    assert len(cache) == 2
    assert cache.get("key3") == "val3"


def test_endpoint_rules_disabled():
    cache = ResponseCache(enabled=False)
    should, _ = cache.endpoint_rules("/prest-test/public/test")
    assert should is False


def test_endpoint_rules_no_endpoints():
    cache = ResponseCache(enabled=True, default_ttl_minutes=5)
    should, ttl = cache.endpoint_rules("/any/path")
    assert should is True
    assert ttl == 5


def test_endpoint_rules_matching_endpoint():
    cache = ResponseCache(enabled=True, default_ttl_minutes=10)
    endpoints = [{"endpoint": "/prest-test/public/test", "enabled": True, "time": 5}]
    should, ttl = cache.endpoint_rules("/prest-test/public/test", endpoints)
    assert should is True
    assert ttl == 5


def test_endpoint_rules_non_matching_endpoint():
    cache = ResponseCache(enabled=True, default_ttl_minutes=10)
    endpoints = [{"endpoint": "/other/path", "enabled": True, "time": 5}]
    should, _ = cache.endpoint_rules("/prest-test/public/test", endpoints)
    assert should is False


def test_endpoint_rules_disabled_endpoint():
    cache = ResponseCache(enabled=True, default_ttl_minutes=10)
    endpoints = [{"endpoint": "/prest-test/public/test", "enabled": False, "time": 5}]
    should, _ = cache.endpoint_rules("/prest-test/public/test", endpoints)
    assert should is False


# ---------------------------------------------------------------------------
# Middleware integration tests
# ---------------------------------------------------------------------------


def test_cache_middleware_disabled_does_not_cache():
    settings = _settings(cache={"enabled": False})
    app = create_app(settings)
    client = TestClient(app)

    # Without pool, all GETs return 503 — cache should not interfere
    response = client.get("/prest-test/public/test")
    assert response.status_code == 503
    assert response.headers.get("Cache-Server") is None


def test_cache_middleware_enabled_but_no_pool():
    settings = _settings(cache={"enabled": True, "time": 10})
    app = create_app(settings)
    client = TestClient(app)

    # Cache enabled but no pool → 503, should not cache non-200 responses
    response = client.get("/prest-test/public/test")
    assert response.status_code == 503


def test_cache_middleware_only_caches_get():
    settings = _settings(cache={"enabled": True, "time": 10})
    app = create_app(settings)
    app.state.pool_manager = None
    client = TestClient(app)

    # POST should not be cached
    response = client.post("/prest-test/public/test", json={"name": "test"})
    assert response.status_code != 200  # 503 or 401


def test_cache_middleware_endpoint_rules_filter():
    settings = _settings(
        cache={
            "enabled": True,
            "time": 10,
            "endpoints": [
                {"endpoint": "/other/path", "enabled": True, "time": 5},
            ],
        },
    )
    app = create_app(settings)
    app.state.pool_manager = None
    client = TestClient(app)

    # URL doesn't match endpoint rule → no caching, reaches handler (503)
    response = client.get("/prest-test/public/test")
    assert response.status_code == 503
    assert response.headers.get("Cache-Server") is None


def test_cache_middleware_caches_public_route():
    app = create_app(_settings(cache={"enabled": True, "time": 10}))

    @app.get("/cached-public")
    async def cached_public():
        return {"value": "cached"}

    client = TestClient(app)

    first = client.get("/cached-public")
    second = client.get("/cached-public")

    assert first.status_code == 200
    assert second.json() == {"value": "cached"}
    assert second.headers["Cache-Server"] == "prestd"


def test_cache_does_not_bypass_crud_auth():
    settings = _settings(
        auth={"enabled": True},
        jwt={"key": "x" * 32, "algo": "HS256", "whitelist": []},
        cache={"enabled": True, "time": 10},
    )
    app = create_app(settings)
    app.state.response_cache.set(
        "http://testserver/prest-test/public/test",
        '[{"secret":"must-not-leak"}]',
        10,
    )
    client = TestClient(app)

    response = client.get("/prest-test/public/test")

    assert response.status_code == 401
    assert response.headers.get("Cache-Server") is None


def test_cache_never_serves_cached_health_response():
    app = create_app(_settings(cache={"enabled": True, "time": 10}))
    app.state.response_cache.set("http://testserver/_health", "cached", 10)
    client = TestClient(app)

    response = client.get("/_health")

    assert response.status_code == 503
    assert response.headers.get("Cache-Server") is None