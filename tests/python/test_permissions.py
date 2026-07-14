from __future__ import annotations

from prest_py.domain.permissions import fields_permissions, table_permissions
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
            "database": "prest",
        },
        "access": {
            "restrict": True,
            "tables": [
                {
                    "name": "test",
                    "permissions": ["read", "write", "delete"],
                    "fields": ["id", "name"],
                },
                {"name": "readonly", "permissions": ["read"], "fields": ["id"]},
                {"name": "allfields", "permissions": ["read"], "fields": ["*"]},
                {
                    "database": "prest",
                    "schema": "public",
                    "name": "specific",
                    "permissions": ["read"],
                    "fields": ["col1"],
                },
            ],
            "users": [
                {
                    "name": "alice",
                    "tables": [
                        {"name": "test", "permissions": ["read"], "fields": ["name"]},
                    ],
                },
            ],
        },
    }
    defaults.update(overrides)
    return Settings.model_validate(defaults)


def test_table_permissions_unrestricted():
    settings = _settings(access={"restrict": False})
    assert table_permissions(settings, "prest", "public", "anything", "read") is True


def test_table_permissions_restricted_allowed():
    settings = _settings()
    assert table_permissions(settings, "prest", "public", "test", "read") is True


def test_table_permissions_restricted_denied():
    settings = _settings()
    assert table_permissions(settings, "prest", "public", "test", "execute") is False


def test_table_permissions_ignore_table():
    settings = _settings(access={"restrict": True, "ignore_table": ["ignored"], "tables": []})
    assert table_permissions(settings, "prest", "public", "ignored", "read") is True


def test_table_permissions_user_override():
    settings = _settings()
    # alice can read "test"
    assert table_permissions(settings, "prest", "public", "test", "read", "alice") is True
    # alice cannot write "test"
    assert table_permissions(settings, "prest", "public", "test", "write", "alice") is False


def test_fields_permissions_unrestricted():
    settings = _settings(access={"restrict": False})
    fields = fields_permissions(settings, ["name", "age"], "prest", "public", "test", "read")
    assert fields == ["name", "age"]


def test_fields_permissions_unrestricted_no_cols():
    settings = _settings(access={"restrict": False})
    fields = fields_permissions(settings, [], "prest", "public", "test", "read")
    assert fields == ["*"]


def test_fields_permissions_restricted_with_asterisk():
    settings = _settings()
    fields = fields_permissions(settings, [], "prest", "public", "allfields", "read")
    assert fields == ["*"]


def test_fields_permissions_restricted_with_requested_cols():
    settings = _settings()
    fields = fields_permissions(settings, ["id", "name"], "prest", "public", "test", "read")
    assert fields == ["id", "name"]


def test_fields_permissions_restricted_intersection():
    settings = _settings()
    fields = fields_permissions(
        settings, ["id", "name", "secret"], "prest", "public", "test", "read"
    )
    assert fields == ["id", "name"]


def test_fields_permissions_restricted_no_cols_returns_allowed():
    settings = _settings()
    fields = fields_permissions(settings, [], "prest", "public", "test", "read")
    assert fields == ["id", "name"]


def test_fields_permissions_user_specific():
    settings = _settings()
    fields = fields_permissions(settings, [], "prest", "public", "test", "read", "alice")
    assert fields == ["name"]


def test_fields_permissions_specific_table_conf():
    settings = _settings()
    fields = fields_permissions(settings, [], "prest", "public", "specific", "read")
    assert fields == ["col1"]
