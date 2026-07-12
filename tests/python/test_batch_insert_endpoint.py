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


def test_batch_insert_invalid_path_segment():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.post("/batch/bad;db/public/test", json=[{"name": "a"}])

    assert response.status_code == 400
    assert "invalid identifier" in response.json()["error"].lower()


def test_batch_insert_empty_body():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.post("/batch/prest-test/public/test", json=[])

    assert response.status_code == 400
    assert "body is empty" in response.json()["error"].lower()


def test_batch_insert_invalid_json():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.post(
        "/batch/prest-test/public/test",
        content="not json",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400


def test_batch_insert_without_pool_returns_503():
    app = create_app(_settings())
    app.state.pool_manager = None
    client = TestClient(app)

    response = client.post("/batch/prest-test/public/test", json=[{"name": "a"}])

    assert response.status_code == 503


def test_batch_insert_unregistered_database():
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

    response = client.post("/batch/unknown-db/public/test", json=[{"name": "a"}])

    assert response.status_code == 400
    assert "not registered" in response.json()["error"].lower()


def test_batch_insert_pg_single_rejects_non_default():
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

    response = client.post("/batch/tenant-a/public/test", json=[{"name": "a"}])

    assert response.status_code == 400
    assert "not registered" in response.json()["error"].lower()


def test_batch_insert_copy_method_without_pool_returns_503():
    app = create_app(_settings())
    app.state.pool_manager = None
    client = TestClient(app)

    response = client.post(
        "/batch/prest-test/public/test",
        json=[{"name": "a"}, {"name": "b"}],
        headers={"Prest-Batch-Method": "copy"},
    )

    assert response.status_code == 503
