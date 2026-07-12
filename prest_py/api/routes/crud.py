from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from prest_py.domain import identifiers as ident
from prest_py.domain.permissions import fields_permissions
from prest_py.postgres.executor import (
    execute_batch_copy,
    execute_batch_insert,
    execute_count,
    execute_insert,
    execute_query,
    execute_write,
)
from prest_py.postgres.query_builder import (
    BodyEmpty,
    QueryBuilderError,
    count_by_request,
    delete_sql,
    distinct_clause,
    group_by_clause,
    insert_sql,
    join_by_request,
    normalize_group_function,
    order_by_request,
    paginate_if_possible,
    parse_batch_insert_request,
    parse_insert_request,
    returning_by_request,
    select_fields,
    select_sql,
    set_by_request,
    update_sql,
    where_by_request,
)
from prest_py.settings.models import Settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["crud"])


def _validate_database_alias(settings: Settings, database: str) -> JSONResponse | None:
    """Return error response if database alias is invalid, else None."""
    if settings.has_database_registry:
        if not settings.profile_by_alias(database):
            return JSONResponse({"error": f"database not registered: {database}"}, status_code=400)
        if settings.pg.single and database != settings.pg.database:
            return JSONResponse({"error": f"database not registered: {database}"}, status_code=400)
    return None


def _validate_path_segments(database: str, schema: str, table: str) -> JSONResponse | None:
    """Return error response if any path segment is invalid, else None."""
    if not all(
        ident.is_safe_segment(seg) for seg in (database, schema, table)
    ):
        return JSONResponse({"error": "invalid identifier in path"}, status_code=400)
    return None


@router.get("/{database}/{schema}/{table}")
async def select_table(request: Request) -> Response:
    """GET /{database}/{schema}/{table} — select rows from a table or view."""
    settings = request.app.state.settings
    pool_manager = getattr(request.app.state, "pool_manager", None)

    database = request.path_params["database"]
    schema = request.path_params["schema"]
    table = request.path_params["table"]

    if err := _validate_database_alias(settings, database):
        return err
    if err := _validate_path_segments(database, schema, table):
        return err

    query_params = parse_qs(urlparse(str(request.url)).query, keep_blank_values=True)

    # Field permissions (user-specific when authenticated)
    user_info = getattr(request.state, "user_info", {})
    username = user_info.get("username", "") if isinstance(user_info, dict) else ""

    try:
        requested_cols = _columns_by_request(query_params)
    except QueryBuilderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    cols = fields_permissions(settings, requested_cols, database, schema, table, "read", username)
    if not cols:
        return JSONResponse(
            {"error": "you don't have permission for this action, "
             "please check the permitted fields for this table"},
            status_code=400,
        )

    try:
        select_str = select_fields(cols)
    except QueryBuilderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    has_registry = settings.has_database_registry
    query = select_sql(select_str, database, schema, table, has_registry)

    # DISTINCT
    try:
        distinct = distinct_clause(query_params)
    except QueryBuilderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if distinct:
        query = query.replace("SELECT", distinct, 1)

    # COUNT
    try:
        count_query = count_by_request(query_params)
    except QueryBuilderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    count_first = False
    if count_query:
        query = select_sql(count_query, database, schema, table, has_registry)
        if query_params.get("_count_first", [""])[0]:
            count_first = True

    # JOIN
    try:
        join_result = join_by_request(query_params)
    except QueryBuilderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    for j in join_result.clauses:
        query = query + j

    # WHERE
    try:
        where_result = where_by_request(query_params, 1)
    except QueryBuilderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    sql_select = query
    if where_result.sql:
        sql_select = query + " WHERE " + where_result.sql

    # GROUP BY
    group_by_sql = group_by_clause(query_params)
    if group_by_sql:
        sql_select = f"{sql_select} {group_by_sql}"

    # ORDER BY
    try:
        order = order_by_request(query_params)
    except QueryBuilderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if order:
        sql_select = f"{sql_select} {order}"

    # PAGINATION
    try:
        page = paginate_if_possible(query_params)
    except (ValueError, QueryBuilderError) as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    sql_select = f"{sql_select} {page}"

    if pool_manager is None:
        return JSONResponse({"error": "database not available"}, status_code=503)

    timeout = float(settings.http.timeout) if settings.http.timeout > 0 else None

    try:
        pool = await pool_manager.get(database)
        if count_query:
            body = await execute_count(pool, sql_select, where_result.values, count_first, timeout)
        else:
            body = await execute_query(
                pool, sql_select, where_result.values,
                settings.json_agg_type, timeout,
            )
    except Exception as e:
        logger.exception("query execution failed")
        if _is_relation_not_found(e, schema, table):
            return JSONResponse(
                {"error": f'relation "{schema}.{table}" does not exist'},
                status_code=404,
            )
        return JSONResponse({"error": "could not perform query"}, status_code=400)

    return Response(content=body, media_type="application/json")


@router.post("/{database}/{schema}/{table}")
async def insert_table(request: Request) -> Response:
    """POST /{database}/{schema}/{table} — insert a single row."""
    settings = request.app.state.settings
    pool_manager = getattr(request.app.state, "pool_manager", None)

    database = request.path_params["database"]
    schema = request.path_params["schema"]
    table = request.path_params["table"]

    if err := _validate_database_alias(settings, database):
        return err
    if err := _validate_path_segments(database, schema, table):
        return err

    # Parse body
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "could not parse request body"}, status_code=400)

    try:
        insert_result = parse_insert_request(body)
    except BodyEmpty:
        return JSONResponse({"error": "body is empty"}, status_code=400)
    except QueryBuilderError as e:
        return JSONResponse({"error": f"could not perform InsertInTables: {e}"}, status_code=400)

    has_registry = settings.has_database_registry
    sql = insert_sql(
        database, schema, table,
        insert_result.cols_name, insert_result.cols_value, has_registry,
    )

    if pool_manager is None:
        return JSONResponse({"error": "database not available"}, status_code=503)

    timeout = float(settings.http.timeout) if settings.http.timeout > 0 else None

    try:
        pool = await pool_manager.get(database)
        body_json = await execute_insert(pool, sql, insert_result.values, table, timeout)
    except Exception as e:
        logger.exception("insert execution failed")
        if _is_relation_not_found(e, schema, table):
            return JSONResponse(
                {"error": f'relation "{schema}.{table}" does not exist'},
                status_code=404,
            )
        return JSONResponse({"error": "could not perform InsertInTables"}, status_code=400)

    return Response(content=body_json, status_code=201, media_type="application/json")


@router.post("/batch/{database}/{schema}/{table}")
async def batch_insert_table(request: Request) -> Response:
    """POST /batch/{database}/{schema}/{table} — insert multiple rows."""
    settings = request.app.state.settings
    pool_manager = getattr(request.app.state, "pool_manager", None)

    database = request.path_params["database"]
    schema = request.path_params["schema"]
    table = request.path_params["table"]

    if err := _validate_database_alias(settings, database):
        return err
    if err := _validate_path_segments(database, schema, table):
        return err

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "could not parse request body"}, status_code=400)

    try:
        batch_result = parse_batch_insert_request(body)
    except BodyEmpty:
        return JSONResponse({"error": "body is empty"}, status_code=400)
    except QueryBuilderError as e:
        return JSONResponse(
            {"error": f"could not perform BatchInsertInTables: {e}"}, status_code=400,
        )

    if pool_manager is None:
        return JSONResponse({"error": "database not available"}, status_code=503)

    timeout = float(settings.http.timeout) if settings.http.timeout > 0 else None
    has_registry = settings.has_database_registry

    try:
        pool = await pool_manager.get(database)
        method = request.headers.get("Prest-Batch-Method", "")
        if method.lower() != "copy":
            sql = insert_sql(
                database, schema, table,
                batch_result.cols_name, batch_result.placeholders, has_registry,
            )
            body_json = await execute_batch_insert(
                pool, sql, batch_result.values, table, timeout,
            )
        else:
            body_json = await execute_batch_copy(
                pool, schema, table, batch_result.columns,
                batch_result.values, timeout,
            )
    except Exception as e:
        logger.exception("batch insert execution failed")
        if _is_relation_not_found(e, schema, table):
            return JSONResponse(
                {"error": f'relation "{schema}.{table}" does not exist'}, status_code=404,
            )
        return JSONResponse(
            {"error": "could not perform BatchInsertInTables"}, status_code=400,
        )

    return Response(content=body_json, status_code=201, media_type="application/json")


@router.delete("/{database}/{schema}/{table}")
async def delete_table(request: Request) -> Response:
    """DELETE /{database}/{schema}/{table} — delete rows from a table."""
    settings = request.app.state.settings
    pool_manager = getattr(request.app.state, "pool_manager", None)

    database = request.path_params["database"]
    schema = request.path_params["schema"]
    table = request.path_params["table"]

    if err := _validate_database_alias(settings, database):
        return err
    if err := _validate_path_segments(database, schema, table):
        return err

    query_params = parse_qs(urlparse(str(request.url)).query, keep_blank_values=True)

    try:
        where_result = where_by_request(query_params, 1)
    except QueryBuilderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    has_registry = settings.has_database_registry
    sql = delete_sql(database, schema, table, has_registry)
    if where_result.sql:
        sql = f"{sql} WHERE {where_result.sql}"

    try:
        returning = returning_by_request(query_params)
    except QueryBuilderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if returning:
        sql = f"{sql} RETURNING {returning}"

    if pool_manager is None:
        return JSONResponse({"error": "database not available"}, status_code=503)

    timeout = float(settings.http.timeout) if settings.http.timeout > 0 else None

    try:
        pool = await pool_manager.get(database)
        body = await execute_write(pool, sql, where_result.values, timeout)
    except Exception as e:
        logger.exception("delete execution failed")
        if _is_relation_not_found(e, schema, table):
            return JSONResponse(
                {"error": f'relation "{schema}.{table}" does not exist'},
                status_code=404,
            )
        return JSONResponse({"error": "could not perform DeleteFromTable"}, status_code=400)

    return Response(content=body, media_type="application/json")


@router.put("/{database}/{schema}/{table}")
@router.patch("/{database}/{schema}/{table}")
async def update_table(request: Request) -> Response:
    """PUT/PATCH /{database}/{schema}/{table} — update rows in a table."""
    settings = request.app.state.settings
    pool_manager = getattr(request.app.state, "pool_manager", None)

    database = request.path_params["database"]
    schema = request.path_params["schema"]
    table = request.path_params["table"]

    if err := _validate_database_alias(settings, database):
        return err
    if err := _validate_path_segments(database, schema, table):
        return err

    query_params = parse_qs(urlparse(str(request.url)).query, keep_blank_values=True)

    # Parse body for SET clause
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "could not parse request body"}, status_code=400)

    try:
        set_result = set_by_request(body, 1)
    except BodyEmpty:
        return JSONResponse({"error": "body is empty"}, status_code=400)
    except QueryBuilderError as e:
        return JSONResponse({"error": f"could not perform UPDATE: {e}"}, status_code=400)

    has_registry = settings.has_database_registry
    sql = update_sql(database, schema, table, set_result.sql, has_registry)

    # WHERE clause continues placeholder numbering from SET values
    pid = len(set_result.values) + 1
    try:
        where_result = where_by_request(query_params, pid)
    except QueryBuilderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    if where_result.sql:
        sql = f"{sql} WHERE {where_result.sql}"

    all_values = set_result.values + where_result.values

    try:
        returning = returning_by_request(query_params)
    except QueryBuilderError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    if returning:
        sql = f"{sql} RETURNING {returning}"

    if pool_manager is None:
        return JSONResponse({"error": "database not available"}, status_code=503)

    timeout = float(settings.http.timeout) if settings.http.timeout > 0 else None

    try:
        pool = await pool_manager.get(database)
        body_json = await execute_write(pool, sql, all_values, timeout)
    except Exception as e:
        logger.exception("update execution failed")
        if _is_relation_not_found(e, schema, table):
            return JSONResponse(
                {"error": f'relation "{schema}.{table}" does not exist'},
                status_code=404,
            )
        return JSONResponse({"error": "could not perform UPDATE"}, status_code=400)

    return Response(content=body_json, media_type="application/json")


def _columns_by_request(query_params: dict[str, list[str]]) -> list[str]:
    """Extract _select columns, normalizing group-function syntax when _groupby is present."""
    columns: list[str] = []
    for j in query_params.get("_select", []):
        for arg in j.split(","):
            fld = arg.strip()
            if fld:
                columns.append(fld)

    if query_params.get("_groupby", [""])[0]:
        normalized = []
        for col in columns:
            if ":" in col:
                normalized.append(normalize_group_function(col))
            else:
                normalized.append(col)
        columns = normalized

    return columns


def _is_relation_not_found(exc: Exception, schema: str, table: str) -> bool:
    """Check if exception indicates the relation does not exist."""
    error_msg = str(exc)
    return f'relation "{schema}.{table}" does not exist' in error_msg or (
        f'relation "{schema}"."{table}" does not exist' in error_msg
    )
