from __future__ import annotations

from fastapi.testclient import TestClient

from prest_py.app import create_app
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


def test_select_invalid_path_segment():
    """Segments with special characters like ; are rejected."""
    app = create_app(_settings())
    client = TestClient(app)

    response = client.get("/bad;db/public/test")

    assert response.status_code == 400
    assert "invalid identifier" in response.json()["error"].lower()


def test_select_invalid_schema_segment():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.get("/prest-test/bad;schema/test")

    assert response.status_code == 400
    assert "invalid identifier" in response.json()["error"].lower()


def test_select_invalid_table_segment():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.get("/prest-test/public/bad;table")

    assert response.status_code == 400
    assert "invalid identifier" in response.json()["error"].lower()


def test_select_without_pool_returns_503():
    app = create_app(_settings())
    app.state.pool_manager = None
    client = TestClient(app)

    response = client.get("/prest-test/public/test")

    assert response.status_code == 503


def test_select_invalid_where_identifier():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.get("/prest-test/public/test?0name=$eq.test")

    assert response.status_code == 400
    assert "invalid identifier" in response.json()["error"].lower()


def test_select_invalid_order():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.get("/prest-test/public/test?_order=0name")

    assert response.status_code == 400


def test_select_invalid_pagination():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.get("/prest-test/public/test?_page=A")

    assert response.status_code == 400


def test_select_invalid_join():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.get("/prest-test/public/test?_join=inner:test2:test2.name")

    assert response.status_code == 400


def test_select_invalid_count():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.get("/prest-test/public/test?_count=0name")

    assert response.status_code == 400


def test_select_unregistered_database_with_registry():
    settings = _settings(
        pg={
            "host": "localhost",
            "port": 5432,
            "user": "postgres",
            "pass": "postgres",
            "database": "prest-test",
            "single": False,
        },
        databases=[{"alias": "known-db", "host": "host-a", "database": "db_a"}],
    )
    app = create_app(settings)
    client = TestClient(app)

    response = client.get("/unknown-db/public/test")

    assert response.status_code == 400
    assert "not registered" in response.json()["error"].lower()


def test_select_pg_single_rejects_non_default():
    settings = _settings(
        pg={
            "host": "localhost",
            "port": 5432,
            "user": "postgres",
            "pass": "postgres",
            "database": "prest-test",
            "single": True,
        },
        databases=[{"alias": "tenant-a", "host": "host-a", "database": "db_a"}],
    )
    app = create_app(settings)
    client = TestClient(app)

    response = client.get("/tenant-a/public/test")

    assert response.status_code == 400
    assert "not registered" in response.json()["error"].lower()


def test_select_registered_alias_passes_validation():
    """A registered alias should pass validation but fail on pool (503)."""
    settings = _settings(
        pg={
            "host": "localhost",
            "port": 5432,
            "user": "postgres",
            "pass": "postgres",
            "database": "prest-test",
            "single": False,
        },
        databases=[{"alias": "known-db", "host": "host-a", "database": "db_a"}],
    )
    app = create_app(settings)
    app.state.pool_manager = None
    client = TestClient(app)

    response = client.get("/known-db/public/test")

    assert response.status_code == 503
