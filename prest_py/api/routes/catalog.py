"""Catalog endpoints for database, schema, and table metadata listing.

Ports Go behavior from `controllers/catalog.go` and `controllers/table.go`:
- GET /databases
- GET /schemas
- GET /tables
- GET /{database}/{schema}
- GET /show/{database}/{schema}/{table}
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlparse

import asyncpg
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from prest_py.api.routes.crud import _validate_database_alias, _validate_path_segments
from prest_py.domain import identifiers as ident
from prest_py.postgres.executor import execute_query
from prest_py.postgres.query_builder import (
    DATABASES_ORDER_BY,
    DATABASES_SELECT,
    DATABASES_WHERE,
    SCHEMA_TABLES_ORDER_BY,
    SCHEMA_TABLES_SELECT,
    SCHEMA_TABLES_WHERE,
    SCHEMAS_ORDER_BY,
    SCHEMAS_SELECT,
    TABLES_ORDER_BY,
    TABLES_SELECT,
    TABLES_WHERE,
    QueryBuilderError,
    distinct_clause,
    order_by_request,
    paginate_if_possible,
    where_by_request,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["catalog"])

FIELD_DATABASE_NAME = "datname"
FIELD_COUNT_DATABASE_NAME = "COUNT(datname)"
FIELD_SCHEMA_NAME = "schema_name"
FIELD_COUNT_SCHEMA_NAME = "COUNT(schema_name)"

SHOW_TABLE_SQL = """SELECT table_schema, table_name, ordinal_position as position,
    column_name, data_type,
    CASE WHEN character_maximum_length is not null
        THEN character_maximum_length
        ELSE numeric_precision END as max_length,
    is_nullable, is_generated, is_updatable, column_default as default_value
FROM information_schema.columns
WHERE table_name=$1 AND table_schema=$2
ORDER BY table_schema, table_name, ordinal_position"""


@router.get("/databases")
async def list_databases(request: Request) -> Response:
    """GET /databases — list all databases from pg_database."""
    settings = request.app.state.settings
    pool_manager = getattr(request.app.state, "pool_manager", None)

    query_params = parse_qs(urlparse(str(request.url)).query, keep_blank_values=True)

    try:
        where_result = where_by_request(query_params, 1)
    except QueryBuilderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    # Count clause
    count_field = query_params.get("_count", [""])[0] if query_params.get("_count") else ""
    has_count = bool(count_field)
    field = FIELD_COUNT_DATABASE_NAME if has_count else FIELD_DATABASE_NAME
    sql = DATABASES_SELECT.format(field=field)

    # Where: built-in + user
    where_sql = DATABASES_WHERE
    if where_result.sql:
        where_sql = f"{where_sql} AND {where_result.sql}"
    sql = f"{sql}{where_sql}"

    try:
        distinct = distinct_clause(query_params)
    except QueryBuilderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if distinct:
        sql = sql.replace("SELECT", distinct, 1)

    try:
        order = order_by_request(query_params)
    except QueryBuilderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if not order and not has_count:
        order = DATABASES_ORDER_BY.format(field=FIELD_DATABASE_NAME)
    sql = f"{sql}{order}"

    try:
        page = paginate_if_possible(query_params)
    except (ValueError, QueryBuilderError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    sql = f"{sql} {page}"

    return await _execute_catalog(pool_manager, settings, sql, where_result.values)


@router.get("/schemas")
async def list_schemas(request: Request) -> Response:
    """GET /schemas — list all schemas from information_schema.schemata."""
    settings = request.app.state.settings
    pool_manager = getattr(request.app.state, "pool_manager", None)

    query_params = parse_qs(urlparse(str(request.url)).query, keep_blank_values=True)

    try:
        where_result = where_by_request(query_params, 1)
    except QueryBuilderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    count_field = query_params.get("_count", [""])[0] if query_params.get("_count") else ""
    has_count = bool(count_field)
    field = FIELD_COUNT_SCHEMA_NAME if has_count else FIELD_SCHEMA_NAME
    sql = SCHEMAS_SELECT.format(field=field)

    if where_result.sql:
        sql = f"{sql} WHERE {where_result.sql}"

    try:
        distinct = distinct_clause(query_params)
    except QueryBuilderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if distinct:
        sql = sql.replace("SELECT", distinct, 1)

    try:
        order = order_by_request(query_params)
    except QueryBuilderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if not order and not has_count:
        order = SCHEMAS_ORDER_BY.format(field=FIELD_SCHEMA_NAME)

    try:
        page = paginate_if_possible(query_params)
    except (ValueError, QueryBuilderError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    sql = f"{sql}{order} {page}"

    return await _execute_catalog(pool_manager, settings, sql, where_result.values)


@router.get("/tables")
async def list_tables(request: Request) -> Response:
    """GET /tables — list all tables from pg_catalog."""
    settings = request.app.state.settings
    pool_manager = getattr(request.app.state, "pool_manager", None)

    query_params = parse_qs(urlparse(str(request.url)).query, keep_blank_values=True)

    try:
        where_result = where_by_request(query_params, 1)
    except QueryBuilderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    # Where: built-in + user
    where_sql = TABLES_WHERE
    if where_result.sql:
        where_sql = f"{where_sql} AND {where_result.sql}"

    sql = TABLES_SELECT

    try:
        distinct = distinct_clause(query_params)
    except QueryBuilderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if distinct:
        sql = sql.replace("SELECT", distinct, 1)

    sql = f"{sql}{where_sql}"

    try:
        order = order_by_request(query_params)
    except QueryBuilderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if not order:
        order = TABLES_ORDER_BY

    try:
        page = paginate_if_possible(query_params)
    except (ValueError, QueryBuilderError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    sql = f"{sql}{order} {page}"

    return await _execute_catalog(pool_manager, settings, sql, where_result.values)


@router.get("/{database}/{schema}")
async def list_tables_by_database_and_schema(request: Request) -> Response:
    """GET /{database}/{schema} — list tables for a specific database and schema."""
    settings = request.app.state.settings
    pool_manager = getattr(request.app.state, "pool_manager", None)

    database = request.path_params["database"]
    schema = request.path_params["schema"]

    if err := _validate_database_alias(settings, database):
        return err

    if not all(ident.is_safe_segment(seg) for seg in (database, schema)):
        return JSONResponse({"error": "invalid identifier in path"}, status_code=400)

    query_params = parse_qs(urlparse(str(request.url)).query, keep_blank_values=True)

    # WHERE clause starts at placeholder 3 ($1=database, $2=schema)
    try:
        where_result = where_by_request(query_params, 3)
    except QueryBuilderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    where_sql = SCHEMA_TABLES_WHERE
    if where_result.sql:
        where_sql = f"{where_sql} AND {where_result.sql}"

    sql = f"{SCHEMA_TABLES_SELECT}{where_sql}"

    try:
        order = order_by_request(query_params)
    except QueryBuilderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if not order:
        order = SCHEMA_TABLES_ORDER_BY

    try:
        page = paginate_if_possible(query_params)
    except (ValueError, QueryBuilderError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    sql = f"{sql}{order} {page}"

    # Values: database, schema, then user filter values
    values = [database, schema] + where_result.values

    if pool_manager is None:
        return JSONResponse({"error": "database not available"}, status_code=503)

    timeout = float(settings.http.timeout) if settings.http.timeout > 0 else None

    try:
        pool = await pool_manager.get(database)
        body = await execute_query(
            pool, sql, values, settings.json_agg_type, timeout,
        )
    except Exception as exc:
        logger.exception("catalog query failed")
        return _catalog_error_response(exc)

    return Response(content=body, media_type="application/json")


@router.get("/show/{database}/{schema}/{table}")
async def show_table(request: Request) -> Response:
    """GET /show/{database}/{schema}/{table} — show table column metadata."""
    settings = request.app.state.settings
    pool_manager = getattr(request.app.state, "pool_manager", None)

    database = request.path_params["database"]
    schema = request.path_params["schema"]
    table = request.path_params["table"]

    if err := _validate_database_alias(settings, database):
        return err
    if err := _validate_path_segments(database, schema, table):
        return err

    if pool_manager is None:
        return JSONResponse({"error": "database not available"}, status_code=503)

    timeout = float(settings.http.timeout) if settings.http.timeout > 0 else None

    try:
        pool = await pool_manager.get(database)
        body = await execute_query(
            pool, SHOW_TABLE_SQL, [table, schema],
            settings.json_agg_type, timeout,
        )
    except Exception as exc:
        logger.exception("show table query failed")
        return _catalog_error_response(exc)

    return Response(content=body, media_type="application/json")


async def _execute_catalog(pool_manager, settings, sql: str, values: list) -> Response:
    """Shared executor for catalog endpoints that use the default pool."""
    if pool_manager is None:
        return JSONResponse({"error": "database not available"}, status_code=503)

    timeout = float(settings.http.timeout) if settings.http.timeout > 0 else None

    try:
        pool = await pool_manager.get()
        body = await execute_query(
            pool, sql, values, settings.json_agg_type, timeout,
        )
    except Exception as exc:
        logger.exception("catalog query failed")
        return _catalog_error_response(exc)

    return Response(content=body, media_type="application/json")


def _catalog_error_response(exc: Exception) -> JSONResponse:
    """Expose only contract-safe PostgreSQL identifier errors."""
    if isinstance(exc, asyncpg.UndefinedColumnError):
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse({"error": "could not perform query"}, status_code=400)