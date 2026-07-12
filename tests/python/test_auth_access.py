from __future__ import annotations

import time

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from prest_py.app import create_app
from prest_py.settings.models import Settings

TEST_JWT_KEY = "x" * 32
OTHER_JWT_KEY = "y" * 32


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


def _make_token(jwt_key: str, username: str = "alice", expired: bool = False) -> str:
    now = int(time.time())
    exp = now - 10 if expired else now + 3600
    claims = {
        "UserInfo": {"username": username, "id": 1, "name": "Alice"},
        "nbf": now,
        "exp": exp,
    }
    return pyjwt.encode(claims, jwt_key, algorithm="HS256")


# ---------------------------------------------------------------------------
# /auth endpoint
# ---------------------------------------------------------------------------


def test_auth_disabled_returns_404():
    app = create_app(_settings())
    client = TestClient(app)

    response = client.post("/auth", json={"username": "u", "password": "p"})

    assert response.status_code == 404


def test_auth_enabled_missing_credentials():
    settings = _settings(
        auth={"enabled": True, "username": "username", "password": "password"},
        jwt={"key": TEST_JWT_KEY, "algo": "HS256"},
    )
    app = create_app(settings)
    client = TestClient(app)

    empty_json = client.post("/auth", json={})
    empty_body = client.post("/auth")

    assert empty_json.status_code == 401
    assert empty_body.status_code == 401


def test_auth_enabled_without_pool_returns_503():
    settings = _settings(
        auth={"enabled": True, "username": "username", "password": "password"},
        jwt={"key": TEST_JWT_KEY, "algo": "HS256"},
    )
    app = create_app(settings)
    app.state.pool_manager = None
    client = TestClient(app)

    response = client.post("/auth", json={"username": "u", "password": "p"})

    assert response.status_code == 503


def test_auth_invalid_json():
    settings = _settings(
        auth={"enabled": True},
        jwt={"key": TEST_JWT_KEY, "algo": "HS256"},
    )
    app = create_app(settings)
    client = TestClient(app)

    response = client.post(
        "/auth",
        content="not json",
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 400


def test_basic_auth_valid_header_reaches_pool():
    settings = _settings(
        auth={"enabled": True, "type": "basic"},
        jwt={"key": "x" * 32, "algo": "HS256"},
    )
    app = create_app(settings)
    app.state.pool_manager = None
    client = TestClient(app)

    response = client.post("/auth", auth=("user", "password"))

    assert response.status_code == 503


def test_basic_auth_missing_header_returns_400():
    settings = _settings(
        auth={"enabled": True, "type": "basic"},
        jwt={"key": "x" * 32, "algo": "HS256"},
    )
    app = create_app(settings)
    client = TestClient(app)

    response = client.post("/auth")

    assert response.status_code == 400
    assert response.json() == {"error": "user not found"}


# ---------------------------------------------------------------------------
# Auth middleware on CRUD routes
# ---------------------------------------------------------------------------


def test_crud_auth_disabled_allows_select():
    app = create_app(_settings())
    app.state.pool_manager = None
    client = TestClient(app)

    # Auth disabled — should reach the handler (503 for no pool)
    response = client.get("/prest-test/public/test")

    assert response.status_code == 503


def test_crud_auth_enabled_rejects_without_token():
    settings = _settings(
        auth={"enabled": True},
        jwt={"key": TEST_JWT_KEY, "algo": "HS256", "whitelist": []},
    )
    app = create_app(settings)
    client = TestClient(app)

    response = client.get("/prest-test/public/test")

    assert response.status_code == 401
    assert "authorization token is empty" in response.json()["detail"].lower()


def test_crud_auth_whitelist_allows_without_token():
    settings = _settings(
        auth={"enabled": True},
        jwt={"key": TEST_JWT_KEY, "algo": "HS256", "whitelist": [r"^/prest-test/public/test$"]},
    )
    app = create_app(settings)
    app.state.pool_manager = None
    client = TestClient(app)

    response = client.get("/prest-test/public/test")

    # Whitelisted — should reach handler (503 for no pool)
    assert response.status_code == 503


def test_crud_auth_valid_token_passes_auth():
    settings = _settings(
        auth={"enabled": True},
        jwt={"key": TEST_JWT_KEY, "algo": "HS256", "whitelist": []},
    )
    app = create_app(settings)
    app.state.pool_manager = None
    client = TestClient(app)

    token = _make_token(TEST_JWT_KEY)
    response = client.get(
        "/prest-test/public/test",
        headers={"Authorization": f"Bearer {token}"},
    )

    # Auth passes — reaches handler (503 for no pool)
    assert response.status_code == 503


def test_crud_auth_expired_token_rejected():
    settings = _settings(
        auth={"enabled": True},
        jwt={"key": TEST_JWT_KEY, "algo": "HS256", "whitelist": []},
    )
    app = create_app(settings)
    client = TestClient(app)

    token = _make_token(TEST_JWT_KEY, expired=True)
    response = client.get(
        "/prest-test/public/test",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


def test_crud_auth_invalid_token_rejected():
    settings = _settings(
        auth={"enabled": True},
        jwt={"key": TEST_JWT_KEY, "algo": "HS256", "whitelist": []},
    )
    app = create_app(settings)
    client = TestClient(app)

    response = client.get(
        "/prest-test/public/test",
        headers={"Authorization": "Bearer invalid.token.here"},
    )

    assert response.status_code == 401


def test_crud_auth_empty_key_fails_closed():
    """Security regression: empty JWT key must not validate any token."""
    settings = _settings(
        auth={"enabled": True},
        jwt={"key": "", "algo": "HS256", "whitelist": []},
    )
    app = create_app(settings)
    client = TestClient(app)

    token = _make_token(OTHER_JWT_KEY)
    response = client.get(
        "/prest-test/public/test",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert "empty" in response.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Access control
# ---------------------------------------------------------------------------


def test_access_control_unrestricted_allows():
    settings = _settings(
        auth={"enabled": True},
        jwt={"key": TEST_JWT_KEY, "algo": "HS256", "whitelist": []},
        access={"restrict": False},
    )
    app = create_app(settings)
    app.state.pool_manager = None
    client = TestClient(app)

    token = _make_token(TEST_JWT_KEY)
    response = client.get(
        "/prest-test/public/test",
        headers={"Authorization": f"Bearer {token}"},
    )

    # Access unrestricted — reaches handler (503 for no pool)
    assert response.status_code == 503


def test_access_control_restricted_denies():
    settings = _settings(
        auth={"enabled": True},
        jwt={"key": TEST_JWT_KEY, "algo": "HS256", "whitelist": []},
        access={"restrict": True, "tables": []},
    )
    app = create_app(settings)
    client = TestClient(app)

    token = _make_token(TEST_JWT_KEY)
    response = client.get(
        "/prest-test/public/test",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert "authorization required" in response.json()["detail"].lower()


def test_access_control_restricted_allows_permitted_table():
    settings = _settings(
        auth={"enabled": True},
        jwt={"key": TEST_JWT_KEY, "algo": "HS256", "whitelist": []},
        access={
            "restrict": True,
            "tables": [
                {"name": "test", "permissions": ["read"], "fields": ["*"]},
            ],
        },
    )
    app = create_app(settings)
    app.state.pool_manager = None
    client = TestClient(app)

    token = _make_token(TEST_JWT_KEY)
    response = client.get(
        "/prest-test/public/test",
        headers={"Authorization": f"Bearer {token}"},
    )

    # Table permitted — reaches handler (503 for no pool)
    assert response.status_code == 503


def test_access_control_user_specific_permissions():
    settings = _settings(
        auth={"enabled": True},
        jwt={"key": TEST_JWT_KEY, "algo": "HS256", "whitelist": []},
        access={
            "restrict": True,
            "tables": [],
            "users": [
                {
                    "name": "alice",
                    "tables": [
                        {"name": "test", "permissions": ["read"], "fields": ["id", "name"]},
                    ],
                },
            ],
        },
    )
    app = create_app(settings)
    app.state.pool_manager = None
    client = TestClient(app)

    token = _make_token(TEST_JWT_KEY, username="alice")
    response = client.get(
        "/prest-test/public/test",
        headers={"Authorization": f"Bearer {token}"},
    )

    # alice has read permission — reaches handler (503 for no pool)
    assert response.status_code == 503


def test_access_control_write_denied_for_read_only():
    settings = _settings(
        auth={"enabled": True},
        jwt={"key": TEST_JWT_KEY, "algo": "HS256", "whitelist": []},
        access={
            "restrict": True,
            "tables": [
                {"name": "test", "permissions": ["read"], "fields": ["*"]},
            ],
        },
    )
    app = create_app(settings)
    client = TestClient(app)

    token = _make_token(TEST_JWT_KEY)
    response = client.post(
        "/prest-test/public/test",
        json={"name": "test"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Catalog routes are NOT behind auth
# ---------------------------------------------------------------------------


def test_catalog_not_behind_auth():
    settings = _settings(
        auth={"enabled": True},
        jwt={"key": TEST_JWT_KEY, "algo": "HS256", "whitelist": []},
    )
    app = create_app(settings)
    app.state.pool_manager = None
    client = TestClient(app)

    # /databases should reach handler (503 for no pool), not 401
    response = client.get("/databases")

    assert response.status_code == 503


def test_default_jwt_protects_catalog_routes():
    key = "x" * 32
    settings = _settings(
        debug=False,
        jwt={"default": True, "key": key, "algo": "HS256", "whitelist": []},
    )
    app = create_app(settings)
    app.state.pool_manager = None
    client = TestClient(app)

    denied = client.get("/databases")
    allowed = client.get(
        "/databases",
        headers={"Authorization": f"Bearer {_make_token(key)}"},
    )

    assert denied.status_code == 401
    assert denied.json() == {"error": "authorization token is empty"}
    assert allowed.status_code == 503


def test_default_jwt_whitelist_skips_validation():
    settings = _settings(
        debug=False,
        jwt={
            "default": True,
            "key": "x" * 32,
            "algo": "HS256",
            "whitelist": [r"^/databases$"],
        },
    )
    app = create_app(settings)
    app.state.pool_manager = None
    client = TestClient(app)

    assert client.get("/databases").status_code == 503


def test_default_jwt_runs_before_cache():
    settings = _settings(
        debug=False,
        jwt={"default": True, "key": "x" * 32, "algo": "HS256", "whitelist": []},
        cache={"enabled": True, "time": 10},
    )
    app = create_app(settings)
    app.state.response_cache.set("http://testserver/databases", '[{"secret":true}]', 10)
    client = TestClient(app)

    response = client.get("/databases")

    assert response.status_code == 401
    assert response.headers.get("Cache-Server") is None


def test_exposure_policy_blocks_disabled_listings():
    settings = _settings(
        expose={"enabled": True, "databases": False, "schemas": True, "tables": True},
    )
    app = create_app(settings)
    client = TestClient(app)

    response = client.get("/databases")

    assert response.status_code == 401
    assert response.json() == {"error": "unauthorized listing"}


def test_unsupported_jwks_fails_app_creation():
    settings = _settings(jwt={"jwks": '{"keys":[]}'})

    with pytest.raises(ValueError, match="not supported"):
        create_app(settings)


# ---------------------------------------------------------------------------
# User-specific field permissions flow through the select handler
# ---------------------------------------------------------------------------


def test_select_field_permissions_are_user_specific():
    """The handler must pass the authenticated username into field permission
    resolution. Alice (fields id,name) selecting `name` proceeds to the pool
    (503); Bob (fields id only) selecting `name` is denied at the field layer
    (400). If the username were dropped, Bob would also proceed to 503.
    """
    settings = _settings(
        auth={"enabled": True},
        jwt={"key": TEST_JWT_KEY, "algo": "HS256", "whitelist": []},
        access={
            "restrict": True,
            "tables": [{"name": "test", "permissions": ["read"], "fields": ["id", "name"]}],
            "users": [
                {
                    "name": "alice",
                    "tables": [
                        {
                            "name": "test",
                            "permissions": ["read"],
                            "fields": ["id", "name"],
                        }
                    ],
                },
                {
                    "name": "bob",
                    "tables": [{"name": "test", "permissions": ["read"], "fields": ["id"]}],
                },
            ],
        },
    )
    app = create_app(settings)
    app.state.pool_manager = None
    client = TestClient(app)

    alice_token = _make_token(TEST_JWT_KEY, username="alice")
    bob_token = _make_token(TEST_JWT_KEY, username="bob")

    alice_resp = client.get(
        "/prest-test/public/test?_select=name",
        headers={"Authorization": f"Bearer {alice_token}"},
    )
    bob_resp = client.get(
        "/prest-test/public/test?_select=name",
        headers={"Authorization": f"Bearer {bob_token}"},
    )

    assert alice_resp.status_code == 503  # permitted field -> reaches pool
    assert bob_resp.status_code == 400  # field not permitted -> denied
    assert "permission" in bob_resp.json()["error"].lower()
