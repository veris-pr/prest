from __future__ import annotations

import datetime as dt
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

from prest_py.postgres.executor import _coerce_parameter


def _type(name: str):
    return SimpleNamespace(name=name)


def test_coerce_postgres_scalar_types():
    assert _coerce_parameter(_type("int4"), "42") == 42
    assert _coerce_parameter(_type("float8"), "1.5") == 1.5
    assert _coerce_parameter(_type("numeric"), "1.25") == Decimal("1.25")
    assert _coerce_parameter(_type("bool"), "true") is True
    assert _coerce_parameter(_type("bool"), "false") is False
    assert _coerce_parameter(_type("date"), "2026-07-10") == dt.date(2026, 7, 10)


def test_coerce_uuid_and_timestamp():
    value = "12345678-1234-5678-1234-567812345678"
    assert _coerce_parameter(_type("uuid"), value) == UUID(value)
    assert _coerce_parameter(
        _type("timestamptz"),
        "2026-07-10T12:30:00Z",
    ) == dt.datetime(2026, 7, 10, 12, 30, tzinfo=dt.UTC)


def test_coerce_preserves_text_and_invalid_typed_values():
    assert _coerce_parameter(_type("text"), "001") == "001"
    assert _coerce_parameter(_type("int4"), "not-an-int") == "not-an-int"
    assert _coerce_parameter(_type("int4"), 7) == 7
