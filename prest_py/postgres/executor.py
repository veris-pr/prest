"""Async query executor for PostgreSQL.

Wraps raw SQL with ``jsonb_agg`` to produce JSON output matching the Go
contract, or executes count queries and returns the count as JSON.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

import asyncpg

from prest_py.domain.identifiers import is_safe_segment

logger = logging.getLogger(__name__)

VALID_JSON_AGG_TYPES = frozenset({"jsonb_agg", "json_agg"})
_INTEGER_TYPES = frozenset({"int2", "int4", "int8", "oid"})
_FLOAT_TYPES = frozenset({"float4", "float8"})


def _coerce_parameter(type_info: object, value: Any) -> Any:
    """Coerce URL-string values using PostgreSQL's inferred parameter type.

    Go's pq driver sends text parameters and PostgreSQL casts them from query
    context. asyncpg uses binary codecs and requires matching Python types.
    Preparing first gives us the inferred types without schema-specific route
    logic or unsafe lexical guesses for text columns.
    """
    if value is None or not isinstance(value, str):
        return value

    name = getattr(type_info, "name", "")
    try:
        if name in _INTEGER_TYPES:
            return int(value)
        if name in _FLOAT_TYPES:
            return float(value)
        if name == "numeric":
            return Decimal(value)
        if name == "bool":
            lowered = value.strip().lower()
            if lowered in {"1", "t", "true", "yes", "on"}:
                return True
            if lowered in {"0", "f", "false", "no", "off"}:
                return False
            return value
        if name == "uuid":
            return UUID(value)
        if name == "date":
            return dt.date.fromisoformat(value)
        if name in {"timestamp", "timestamptz"}:
            return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        if name in {"time", "timetz"}:
            return dt.time.fromisoformat(value)
    except (ValueError, InvalidOperation):
        # Leave invalid text unchanged so asyncpg raises its normal typed-data
        # error and the HTTP layer returns the existing 400 contract.
        return value
    return value


async def _prepare(
    conn: asyncpg.Connection,
    sql: str,
    values: list[Any],
    timeout: float | None,
):
    statement = await conn.prepare(sql, timeout=timeout)
    parameter_types = statement.get_parameters()
    coerced = [
        _coerce_parameter(type_info, value)
        for type_info, value in zip(parameter_types, values, strict=True)
    ]
    return statement, coerced


async def execute_query(
    pool: asyncpg.Pool,
    sql: str,
    values: list[Any],
    json_agg_type: str = "jsonb_agg",
    timeout: float | None = None,
) -> str:
    """Execute a SELECT and return JSON-encoded results.

    Wraps the query in ``SELECT {json_agg_type}(s) FROM ({sql}) s`` and returns
    the JSON string. Empty results return ``[]``.
    """
    if json_agg_type not in VALID_JSON_AGG_TYPES:
        json_agg_type = "jsonb_agg"
    wrapped = f"SELECT {json_agg_type}(s) FROM ({sql}) s"
    logger.debug(
        "executing query",
        extra={"sql_length": len(wrapped), "param_count": len(values)},
    )

    async with pool.acquire() as conn:
        statement, coerced = await _prepare(conn, wrapped, values, timeout)
        row = await statement.fetchrow(*coerced, timeout=timeout)

    if row is None:
        return "[]"

    result = row[0]
    if result is None:
        return "[]"
    if isinstance(result, str):
        return result
    if isinstance(result, (dict, list)):
        return json.dumps(result)
    return str(result)


async def execute_insert(
    pool: asyncpg.Pool,
    sql: str,
    values: list[Any],
    table: str,
    timeout: float | None = None,
) -> str:
    """Execute an INSERT with RETURNING and return JSON-encoded result.

    Appends ``RETURNING row_to_json("table")`` to the SQL (matching Go
    ``fullInsert`` behavior) and returns the JSON string of the inserted row.

    Defense-in-depth: validates ``table`` as a safe segment even though the
    route handler already validates it.
    """
    if not is_safe_segment(table):
        raise ValueError(f"invalid table identifier: {table}")
    full_sql = f'{sql} RETURNING row_to_json("{table}")'
    logger.debug(
        "executing insert",
        extra={"sql_length": len(full_sql), "param_count": len(values)},
    )

    async with pool.acquire() as conn:
        statement, coerced = await _prepare(conn, full_sql, values, timeout)
        row = await statement.fetchrow(*coerced, timeout=timeout)

    if row is None:
        return "{}"
    result = row[0]
    if result is None:
        return "{}"
    if isinstance(result, str):
        return result
    if isinstance(result, (dict, list)):
        return json.dumps(result)
    return str(result)


async def execute_batch_insert(
    pool: asyncpg.Pool,
    sql: str,
    values: list[Any],
    table: str,
    timeout: float | None = None,
) -> str:
    """Execute a batch INSERT with RETURNING and return JSON array.

    Appends ``RETURNING row_to_json("table")`` (matching Go ``fullInsert``)
    and returns a JSON array of inserted rows. Empty result returns ``[]``.
    """
    if not is_safe_segment(table):
        raise ValueError(f"invalid table identifier: {table}")
    full_sql = f'{sql} RETURNING row_to_json("{table}")'
    logger.debug(
        "executing batch insert",
        extra={"sql_length": len(full_sql), "param_count": len(values)},
    )

    async with pool.acquire() as conn:
        statement, coerced = await _prepare(conn, full_sql, values, timeout)
        rows = await statement.fetch(*coerced, timeout=timeout)

    if not rows:
        return "[]"

    result = []
    for row in rows:
        raw = row[0]
        if isinstance(raw, str):
            result.append(json.loads(raw))
        elif isinstance(raw, (dict, list)):
            result.append(raw)
    return json.dumps(result, default=str)


async def execute_batch_copy(
    pool: asyncpg.Pool,
    schema: str,
    table: str,
    columns: list[str],
    values: list[Any],
    timeout: float | None = None,
) -> str:
    """Execute a batch INSERT via COPY, returning empty body.

    Uses asyncpg ``copy_records_to_table``. Returns empty string to match
    Go contract where COPY batch insert returns 201 with no body.
    """
    if not is_safe_segment(schema) or not is_safe_segment(table):
        raise ValueError(f"invalid identifier: {schema}.{table}")

    num_cols = len(columns)
    if num_cols == 0:
        raise ValueError("no columns specified for batch copy")

    records = [
        tuple(values[i : i + num_cols])
        for i in range(0, len(values), num_cols)
    ]

    logger.debug(
        "executing batch copy",
        extra={"schema": schema, "table": table, "columns": columns, "record_count": len(records)},
    )

    async with pool.acquire() as conn:
        await conn.copy_records_to_table(
            schema_name=schema,
            table_name=table,
            columns=columns,
            records=records,
            timeout=timeout,
        )

    return ""


async def execute_write(
    pool: asyncpg.Pool,
    sql: str,
    values: list[Any],
    timeout: float | None = None,
) -> str:
    """Execute a DELETE or UPDATE, returning JSON-encoded result.

    When SQL contains ``RETURNING``, fetches rows and returns a JSON array.
    Otherwise returns ``{"rows_affected": N}``.
    """
    logger.debug(
        "executing write",
        extra={"sql_length": len(sql), "param_count": len(values)},
    )

    async with pool.acquire() as conn:
        statement, coerced = await _prepare(conn, sql, values, timeout)
        rows = await statement.fetch(*coerced, timeout=timeout)
        if "RETURNING" in sql.upper():
            result = [dict(row) for row in rows]
            return json.dumps(result, default=str)
        status = statement.get_statusmsg() or ""
        rows_affected = _parse_rows_affected(status)
        return json.dumps({"rows_affected": rows_affected})


def _parse_rows_affected(status: str) -> int:
    """Parse asyncpg command status like ``DELETE 5`` or ``UPDATE 3``."""
    parts = status.split()
    if len(parts) >= 2 and parts[-1].isdigit():
        return int(parts[-1])
    return 0


async def execute_count(
    pool: asyncpg.Pool,
    sql: str,
    values: list[Any],
    count_first: bool = False,
    timeout: float | None = None,
) -> str:
    """Execute a COUNT query and return JSON-encoded result.

    Returns ``[{"count": N}]`` (list form) or ``{"count": N}`` (object form
    when ``count_first`` is True).
    """
    logger.debug(
        "executing count query",
        extra={"sql_length": len(sql), "param_count": len(values)},
    )

    async with pool.acquire() as conn:
        statement, coerced = await _prepare(conn, sql, values, timeout)
        row = await statement.fetchrow(*coerced, timeout=timeout)

    if row is None:
        count = 0
    else:
        count = row[0]

    if count_first:
        return json.dumps({"count": count}, separators=(",", ":"))
    return json.dumps([{"count": count}], separators=(",", ":"))