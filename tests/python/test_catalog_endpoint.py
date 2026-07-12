from __future__ import annotations

import asyncpg
from fastapi.testclient import TestClient

from prest_py.api.routes.catalog import _catalog_error_response
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


def test_catalog_undefined_column_preserves_safe_contract_message():
    response = _catalog_error_response(
        asyncpg.UndefinedColumnError('column "missing" does not exist')
    )

    assert response.status_code == 400
    assert b"does not exist" in response.body


def test_databases_without_pool_returns_503():
    app = create_app(_settings())
    app.state.pool_manager = None
    client = TestClient(app)

    response = client.get("/databases")

    assert response.status_code == 503


def test_databases_invalid_where_identifier():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.get("/databases?0datname=prest")

    assert response.status_code == 400


def test_databases_invalid_order():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.get("/databases?_order=$eq.prest")

    assert response.status_code == 400


def test_databases_invalid_pagination():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.get("/databases?_page=A")

    assert response.status_code == 400


def test_schemas_without_pool_returns_503():
    app = create_app(_settings())
    app.state.pool_manager = None
    client = TestClient(app)

    response = client.get("/schemas")

    assert response.status_code == 503


def test_schemas_invalid_where_identifier():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.get("/schemas?0schema_name=$eq.public")

    assert response.status_code == 400


def test_tables_without_pool_returns_503():
    app = create_app(_settings())
    app.state.pool_manager = None
    client = TestClient(app)

    response = client.get("/tables")

    assert response.status_code == 503


def test_tables_invalid_where_identifier():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.get("/tables?0c.relname=$eq.test")

    assert response.status_code == 400


def test_tables_by_db_schema_invalid_path_segment():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.get("/bad;db/public")

    assert response.status_code == 400
    assert "invalid identifier" in response.json()["error"].lower()


def test_tables_by_db_schema_unregistered_database():
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

    response = client.get("/unknown-db/public")

    assert response.status_code == 400
    assert "not registered" in response.json()["error"].lower()


def test_tables_by_db_schema_without_pool_returns_503():
    app = create_app(_settings())
    app.state.pool_manager = None
    client = TestClient(app)

    response = client.get("/prest-test/public")

    assert response.status_code == 503


def test_tables_by_db_schema_invalid_where_identifier():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.get("/prest-test/public?0t.tablename=$eq.test")

    assert response.status_code == 400


def test_show_table_invalid_path_segment():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.get("/show/bad;db/public/test")

    assert response.status_code == 400
    assert "invalid identifier" in response.json()["error"].lower()


def test_show_table_unregistered_database():
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

    response = client.get("/show/unknown-db/public/test")

    assert response.status_code == 400
    assert "not registered" in response.json()["error"].lower()


def test_show_table_without_pool_returns_503():
    app = create_app(_settings())
    app.state.pool_manager = None
    client = TestClient(app)

    response = client.get("/show/prest-test/public/test")

    assert response.status_code == 503