from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from prest_py.postgres.pool import PoolManager
from prest_py.settings.models import Settings


def _base_settings(**overrides) -> Settings:
    defaults = {
        "app_name": "test-prest",
        "debug": True,
        "http": {"host": "0.0.0.0", "port": 3000, "timeout": 60},
        "pg": {
            "host": "localhost",
            "port": 5432,
            "user": "postgres",
            "pass": "postgres",
            "database": "prest",
        },
    }
    defaults.update(overrides)
    return Settings.model_validate(defaults)


def test_pool_manager_keyed_by_uri():
    settings = _base_settings()
    manager = PoolManager(settings)

    assert manager.registered_aliases() == []


def test_is_registered_returns_true_without_registry():
    settings = _base_settings()
    manager = PoolManager(settings)

    assert manager.is_registered("anything") is True


def test_is_registered_checks_registry():
    settings = _base_settings(
        databases=[{"alias": "tenant-a", "host": "host-a", "database": "db_a"}],
    )
    manager = PoolManager(settings)

    assert manager.is_registered("tenant-a") is True
    assert manager.is_registered("unknown") is False


def test_physical_name_resolves_alias():
    settings = _base_settings(
        databases=[{"alias": "tenant-a", "host": "host-a", "database": "physical_a"}],
    )
    manager = PoolManager(settings)

    assert manager.physical_name("tenant-a") == "physical_a"
    assert manager.physical_name("") == "prest"


@pytest.mark.asyncio
async def test_pg_single_rejects_non_default_alias():
    settings = _base_settings(
        pg={
            "host": "localhost",
            "port": 5432,
            "user": "postgres",
            "pass": "postgres",
            "database": "prest",
            "single": True,
        },
        databases=[{"alias": "tenant-a", "host": "host-a", "database": "db_a"}],
    )
    manager = PoolManager(settings)

    with pytest.raises(ValueError, match="pg.single"):
        await manager.get("tenant-a")


def test_pg_single_allows_default_alias():
    settings = _base_settings(
        pg={
            "host": "localhost",
            "port": 5432,
            "user": "postgres",
            "pass": "postgres",
            "database": "prest",
            "single": True,
        },
        databases=[{"alias": "prest", "host": "host-a", "database": "db_a"}],
    )
    manager = PoolManager(settings)

    # Should not raise — default alias is always allowed
    resolved = manager._validate_alias("prest")
    assert resolved == "prest"


def test_validate_alias_rejects_unregistered():
    settings = _base_settings(
        pg={
            "host": "localhost",
            "port": 5432,
            "user": "postgres",
            "pass": "postgres",
            "database": "prest",
            "single": False,
        },
        databases=[{"alias": "tenant-a", "host": "host-a", "database": "db_a"}],
    )
    manager = PoolManager(settings)

    with pytest.raises(ValueError, match="not registered"):
        manager._validate_alias("unknown-alias")


@pytest.mark.asyncio
async def test_ping_returns_false_on_connect_failure():
    settings = _base_settings(
        pg={"host": "invalid-host", "port": 1, "user": "x", "pass": "x", "database": "x"}
    )
    manager = PoolManager(settings)

    ok = await manager.ping()

    assert ok is False
    await manager.close()


@pytest.mark.asyncio
async def test_ping_all_without_registry_pings_default_only():
    settings = _base_settings()
    manager = PoolManager(settings)
    manager.ping = AsyncMock(return_value=True)

    ok = await manager.ping_all()

    assert ok is True
    manager.ping.assert_called_once_with()


@pytest.mark.asyncio
async def test_ping_all_with_registry_pings_all_aliases():
    settings = _base_settings(
        pg={
            "host": "localhost",
            "port": 5432,
            "user": "postgres",
            "pass": "postgres",
            "database": "prest",
            "single": False,
        },
        databases=[
            {"alias": "tenant-a", "host": "host-a", "database": "db_a"},
            {"alias": "tenant-b", "host": "host-b", "database": "db_b"},
        ],
    )
    manager = PoolManager(settings)
    manager.ping = AsyncMock(return_value=True)

    ok = await manager.ping_all()

    assert ok is True
    assert manager.ping.call_count == 3  # default + 2 aliases


@pytest.mark.asyncio
async def test_ping_all_returns_false_if_any_alias_fails():
    settings = _base_settings(
        pg={
            "host": "localhost",
            "port": 5432,
            "user": "postgres",
            "pass": "postgres",
            "database": "prest",
            "single": False,
        },
        databases=[
            {"alias": "tenant-a", "host": "host-a", "database": "db_a"},
            {"alias": "tenant-b", "host": "host-b", "database": "db_b"},
        ],
    )
    manager = PoolManager(settings)
    manager.ping = AsyncMock(side_effect=[True, True, False])

    ok = await manager.ping_all()

    assert ok is False


def test_uri_for_default_uses_pg_settings():
    settings = _base_settings()
    manager = PoolManager(settings)

    uri = manager._uri_for("")

    assert "postgres://postgres:postgres@localhost:5432/prest" in uri
    assert "sslmode=disable" in uri


def test_uri_for_alias_uses_profile():
    settings = _base_settings(
        databases=[
            {
                "alias": "tenant-a",
                "host": "host-a",
                "port": 5433,
                "user": "u",
                "pass": "p",
                "database": "db_a",
            }
        ],
    )
    manager = PoolManager(settings)

    uri = manager._uri_for("tenant-a")

    assert "postgres://u:p@host-a:5433/db_a" in uri


def test_uri_for_alias_with_url_uses_url():
    settings = _base_settings(
        databases=[{"alias": "tenant-a", "url": "postgres://x:y@z:5432/w?sslmode=require"}],
    )
    manager = PoolManager(settings)

    uri = manager._uri_for("tenant-a")

    assert uri == "postgres://x:y@z:5432/w?sslmode=require"


def test_default_uri_percent_encodes_credentials():
    settings = _base_settings(
        pg={
            "host": "localhost",
            "port": 5432,
            "user": "user@example.com",
            "pass": "p@ss:/word",
            "database": "prest",
        }
    )

    uri = PoolManager(settings)._uri_for("")

    assert "user%40example.com:p%40ss%3A%2Fword@" in uri


def test_pg_url_preserves_options_when_routing_legacy_database():
    settings = _base_settings(
        pg={
            "url": (
                "postgres://user:pass@localhost:5432/prest?sslmode=require&application_name=prest"
            ),
            "database": "prest",
            "single": False,
        }
    )
    manager = PoolManager(settings)

    assert manager._uri_for("").endswith("/prest?sslmode=require&application_name=prest")
    assert manager._uri_for("secondary").endswith(
        "/secondary?sslmode=require&application_name=prest"
    )


@pytest.mark.asyncio
async def test_concurrent_first_get_creates_one_supported_pool():
    settings = _base_settings(
        pg={
            "host": "localhost",
            "port": 5432,
            "user": "postgres",
            "pass": "postgres",
            "database": "prest",
            "maxopenconn": 7,
            "maxidleconn": 2,
            "conntimeout": 4,
        }
    )
    manager = PoolManager(settings)
    pool = object()

    with patch("prest_py.postgres.pool.asyncpg.create_pool", new_callable=AsyncMock) as create:
        create.return_value = pool
        first, second = await asyncio.gather(manager.get(), manager.get())

    assert first is pool
    assert second is pool
    create.assert_awaited_once()
    kwargs = create.await_args.kwargs
    assert kwargs["min_size"] == 2
    assert kwargs["max_size"] == 7
    assert kwargs["timeout"] == 4
    assert "max_inactive_session_idle" not in kwargs


def test_pool_limits_for_default():
    settings = _base_settings(
        pg={
            "host": "localhost",
            "port": 5432,
            "user": "postgres",
            "pass": "postgres",
            "database": "prest",
            "maxopenconn": 10,
            "maxidleconn": 0,
        }
    )
    manager = PoolManager(settings)

    max_idle, max_open = manager._pool_limits_for("")

    assert max_idle == 0
    assert max_open == 10


def test_pool_limits_for_alias_override():
    settings = _base_settings(
        pg={
            "host": "localhost",
            "port": 5432,
            "user": "postgres",
            "pass": "postgres",
            "database": "prest",
            "maxopenconn": 10,
            "maxidleconn": 0,
        },
        databases=[
            {
                "alias": "tenant-a",
                "host": "host-a",
                "database": "db_a",
                "maxopenconn": 20,
                "maxidleconn": 5,
            }
        ],
    )
    manager = PoolManager(settings)

    max_idle, max_open = manager._pool_limits_for("tenant-a")

    assert max_idle == 5
    assert max_open == 20
