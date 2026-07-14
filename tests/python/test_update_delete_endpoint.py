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


# ---------------------------------------------------------------------------
# DELETE
# ---------------------------------------------------------------------------


def test_delete_invalid_path_segment():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.delete("/bad;db/public/test")

    assert response.status_code == 400
    assert "invalid identifier" in response.json()["error"].lower()


def test_delete_invalid_where_identifier():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.delete("/prest-test/public/test?0name=$eq.test")

    assert response.status_code == 400


def test_delete_without_pool_returns_503():
    app = create_app(_settings())
    app.state.pool_manager = None
    client = TestClient(app)

    response = client.delete("/prest-test/public/test")

    assert response.status_code == 503


def test_delete_unregistered_database():
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

    response = client.delete("/unknown-db/public/test")

    assert response.status_code == 400
    assert "not registered" in response.json()["error"].lower()


def test_delete_with_returning_invalid_identifier():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.delete("/prest-test/public/test?_returning=0bad")

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# UPDATE (PUT)
# ---------------------------------------------------------------------------


def test_update_put_invalid_path_segment():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.put("/bad;db/public/test", json={"name": "test"})

    assert response.status_code == 400
    assert "invalid identifier" in response.json()["error"].lower()


def test_update_put_empty_body():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.put("/prest-test/public/test", json={})

    assert response.status_code == 400
    assert "body is empty" in response.json()["error"].lower()


def test_update_put_invalid_body_key():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.put("/prest-test/public/test", json={"0bad": "test"})

    assert response.status_code == 400


def test_update_put_invalid_json():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.put(
        "/prest-test/public/test",
        content="not json",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400


def test_update_put_without_pool_returns_503():
    app = create_app(_settings())
    app.state.pool_manager = None
    client = TestClient(app)

    response = client.put("/prest-test/public/test", json={"name": "test"})

    assert response.status_code == 503


def test_update_put_invalid_where_identifier():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.put("/prest-test/public/test?0name=$eq.test", json={"name": "test"})

    assert response.status_code == 400


def test_update_put_unregistered_database():
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

    response = client.put("/unknown-db/public/test", json={"name": "test"})

    assert response.status_code == 400
    assert "not registered" in response.json()["error"].lower()


def test_update_put_with_returning_invalid_identifier():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.put("/prest-test/public/test?_returning=0bad", json={"name": "test"})

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# UPDATE (PATCH) — same handler, different method
# ---------------------------------------------------------------------------


def test_update_patch_invalid_path_segment():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.patch("/bad;db/public/test", json={"name": "test"})

    assert response.status_code == 400
    assert "invalid identifier" in response.json()["error"].lower()


def test_update_patch_empty_body():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.patch("/prest-test/public/test", json={})

    assert response.status_code == 400
    assert "body is empty" in response.json()["error"].lower()


def test_update_patch_without_pool_returns_503():
    app = create_app(_settings())
    app.state.pool_manager = None
    client = TestClient(app)

    response = client.patch("/prest-test/public/test", json={"name": "test"})

    assert response.status_code == 503


def test_update_patch_unregistered_database():
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

    response = client.patch("/unknown-db/public/test", json={"name": "test"})

    assert response.status_code == 400
    assert "not registered" in response.json()["error"].lower()
