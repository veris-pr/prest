"""SQL script endpoints for pREST _QUERIES routes.

Ports Go behavior from `controllers/script.go`:
- ANY /_QUERIES/{queriesLocation}/{script} — default database
- ANY /_QUERIES/{database}/{queriesLocation}/{script} — specific database

Script files use Go template syntax, resolved by method suffix.
GET → read (jsonb_agg), POST/PUT/PATCH/DELETE → write (rows_affected).
"""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

from prest_py.api.routes.crud import _validate_database_alias
from prest_py.domain import identifiers as ident
from prest_py.postgres.executor import execute_query, execute_write
from prest_py.postgres.scripts import (
    ScriptParser,
    resolve_script_path,
    sanitize_param,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["scripts"])


@router.api_route(
    "/_QUERIES/{queriesLocation}/{script}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def execute_script_default(request: Request) -> Response:
    """Execute SQL script against default database."""
    settings = request.app.state.settings
    database = settings.pg.database
    queries_location = request.path_params["queriesLocation"]
    script = request.path_params["script"]
    return await _execute_script(request, settings, database, queries_location, script)


@router.api_route(
    "/_QUERIES/{database}/{queriesLocation}/{script}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
)
async def execute_script_with_db(request: Request) -> Response:
    """Execute SQL script against specified database."""
    settings = request.app.state.settings
    database = request.path_params["database"]
    queries_location = request.path_params["queriesLocation"]
    script = request.path_params["script"]

    if err := _validate_database_alias(settings, database):
        return err
    if not all(ident.is_safe_segment(seg) for seg in (database, queries_location, script)):
        return JSONResponse({"error": "invalid identifier in path"}, status_code=400)

    return await _execute_script(request, settings, database, queries_location, script)


async def _execute_script(
    request: Request,
    settings,
    database: str,
    queries_location: str,
    script: str,
) -> Response:
    """Shared script execution logic."""
    pool_manager = getattr(request.app.state, "pool_manager", None)

    # Resolve base queries path
    base_path = settings.queries.location
    if not base_path:
        return JSONResponse({"error": "queries path not configured"}, status_code=400)

    # Resolve script file
    try:
        script_path = resolve_script_path(
            request.method, queries_location, script, base_path,
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)

    if script_path is None:
        return JSONResponse(
            {"error": f"could not get script {queries_location}/{script}"},
            status_code=400,
        )

    # Build template data from query params and headers
    template_data = _extract_template_data(request)

    # Parse template
    try:
        with open(script_path, encoding="utf-8") as f:
            template_str = f.read()
    except OSError as e:
        return JSONResponse(
            {"error": f"could not read script: {e}"},
            status_code=400,
        )

    parser = ScriptParser(template_data)
    sql, values = parser.parse(template_str)

    if pool_manager is None:
        return JSONResponse({"error": "database not available"}, status_code=503)

    timeout = float(settings.http.timeout) if settings.http.timeout > 0 else None

    try:
        pool = await pool_manager.get(database)
        if request.method == "GET":
            body = await execute_query(
                pool, sql, values, settings.json_agg_type, timeout,
            )
        else:
            body = await execute_write(pool, sql, values, timeout)
    except Exception:
        logger.exception("script execution failed")
        return JSONResponse(
            {"error": "could not execute sql, check your prest logs"},
            status_code=400,
        )

    return Response(content=body, media_type="application/json")


def _extract_template_data(request: Request) -> dict:
    """Extract query params and headers into template data, sanitized."""
    query_params = parse_qs(urlparse(str(request.url)).query, keep_blank_values=True)

    template_data: dict = {}
    for key, values in query_params.items():
        if len(values) == 1:
            template_data[key] = sanitize_param(values[0])
        else:
            template_data[key] = [sanitize_param(v) for v in values]

    # Headers
    headers: dict = {}
    for key, value in request.headers.items():
        headers[key] = value
    template_data["header"] = headers

    return template_data