"""Authentication handler for POST /auth endpoint.

Ports Go behavior from `controllers/auth.go`:
- Parses username/password from JSON body or HTTP Basic auth
- Validates credentials against configured table
- Supports bcrypt, MD5, and SHA1 password verification
- Generates HS256 JWT with 6-hour expiry
- Returns {"user_info": {...}, "token": "..."}
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import logging

import bcrypt
import jwt as pyjwt
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

JWT_ALGORITHM = "HS256"
TOKEN_EXPIRY_HOURS = 6


@router.post("/auth")
async def login(request: Request) -> Response:
    """POST /auth — authenticate user and return JWT token."""
    settings = request.app.state.settings
    pool_manager = getattr(request.app.state, "pool_manager", None)

    if not settings.auth.enabled:
        return JSONResponse({"error": "auth not enabled"}, status_code=404)

    credentials, error_response = await _credentials_from_request(request, settings.auth.type)
    if error_response is not None:
        return error_response
    username, password = credentials

    if not username or not password:
        return JSONResponse({"error": "missing username or password"}, status_code=401)

    # Validate against configured table
    if pool_manager is None:
        return JSONResponse({"error": "database not available"}, status_code=503)

    timeout = float(settings.http.timeout) if settings.http.timeout > 0 else None

    try:
        pool = await pool_manager.get()

        auth_query = _build_auth_query(settings)
        user = await _validate_credentials(
            pool, settings, auth_query, username, password, timeout,
        )
    except Exception:
        logger.exception("auth validation failed")
        return JSONResponse({"error": "user not found"}, status_code=401)

    if user is None:
        return JSONResponse({"error": "user not found"}, status_code=401)

    # Generate JWT
    if not settings.jwt.key:
        return JSONResponse({"error": "JWT key not configured"}, status_code=500)

    token = _generate_token(user, settings.jwt.key)

    return Response(
        content=_json_response({"user_info": user, "token": token}),
        media_type="application/json",
    )


async def _credentials_from_request(
    request: Request,
    auth_type: str,
) -> tuple[tuple[str, str], JSONResponse | None]:
    """Read credentials using Go-compatible body or Basic auth modes."""
    if auth_type.lower() == "basic":
        header = request.headers.get("Authorization", "")
        scheme, _, encoded = header.partition(" ")
        if scheme.lower() != "basic" or not encoded:
            return ("", ""), JSONResponse({"error": "user not found"}, status_code=400)
        try:
            decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
            username, separator, password = decoded.partition(":")
        except (binascii.Error, UnicodeDecodeError):
            return ("", ""), JSONResponse({"error": "user not found"}, status_code=400)
        if not separator:
            return ("", ""), JSONResponse({"error": "user not found"}, status_code=400)
        return (username, password), None

    if auth_type.lower() != "body":
        return ("", ""), JSONResponse({"error": "unknown auth type"}, status_code=400)

    raw_body = await request.body()
    if not raw_body:
        # Go ignores EOF while decoding, then treats empty credentials as an
        # authentication failure (401), not malformed JSON (400).
        return ("", ""), None
    try:
        body = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ("", ""), JSONResponse(
            {"error": "could not parse request body"},
            status_code=400,
        )
    if not isinstance(body, dict):
        return ("", ""), JSONResponse(
            {"error": "could not parse request body"},
            status_code=400,
        )
    return (str(body.get("username", "")), str(body.get("password", ""))), None


def _build_auth_query(settings) -> str:
    """Build SELECT query for auth table.

    Mirrors Go `selectQueryByUsername`/`selectQuery`: unquoted schema.table
    reference (config-owned values, not request input). The connection is
    already scoped to the configured database, so no database qualifier.

    For bcrypt: SELECT by username only (verify hash in app).
    For MD5/SHA1: SELECT by username AND password hash.
    """
    schema = settings.auth.schema_
    table = settings.auth.table
    username_col = settings.auth.username
    password_col = settings.auth.password

    encrypt = settings.auth.encrypt.upper()
    if encrypt == "BCRYPT":
        return f"SELECT * FROM {schema}.{table} WHERE {username_col}=$1 LIMIT 1"
    return (
        f"SELECT * FROM {schema}.{table} WHERE {username_col}=$1 "
        f"AND {password_col}=$2 LIMIT 1"
    )


async def _validate_credentials(
    pool, settings, query, username, password, timeout,
) -> dict | None:
    """Execute auth query and validate password.

    Returns user dict on success, None on failure.
    """
    encrypt = settings.auth.encrypt.upper()
    username_lower = username.lower()

    if encrypt == "BCRYPT":
        rows = await _fetch_rows(pool, query, [username_lower], settings, timeout)
        if not rows:
            return None
        row = rows[0]
        stored_password = row.get(settings.auth.password, "")
        if _verify_bcrypt(password, stored_password):
            return _extract_user(row, settings)
        return None

    if encrypt in ("MD5", "SHA1"):
        digest = _legacy_digest(password, encrypt)
        rows = await _fetch_rows(pool, query, [username_lower, digest], settings, timeout)
        if not rows:
            return None
        return _extract_user(rows[0], settings)

    return None


async def _fetch_rows(pool, query, values, settings, timeout) -> list[dict]:
    """Execute auth query and return rows as list of dicts."""
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *values, timeout=timeout)
    return [dict(row) for row in rows]


def _verify_bcrypt(password: str, stored: str) -> bool:
    """Verify password against bcrypt hash."""
    if stored.startswith(("$2a$", "$2b$", "$2y$")):
        try:
            return bcrypt.checkpw(password.encode(), stored.encode())
        except Exception:
            return False

    # Legacy fallback: check MD5/SHA1 stored hashes
    if _is_hex(stored):
        if len(stored) == 32:
            return _legacy_digest(password, "MD5") == stored
        if len(stored) == 40:
            return _legacy_digest(password, "SHA1") == stored

    return False


def _legacy_digest(password: str, algorithm: str) -> str:
    """Compute MD5 or SHA1 digest of password."""
    if algorithm.upper() == "MD5":
        return hashlib.md5(password.encode()).hexdigest()  # noqa: S324
    if algorithm.upper() == "SHA1":
        return hashlib.sha1(password.encode()).hexdigest()  # noqa: S324
    raise ValueError(f"unknown algorithm: {algorithm}")


def _is_hex(s: str) -> bool:
    if not s or len(s) % 2 != 0:
        return False
    try:
        bytes.fromhex(s)
        return True
    except ValueError:
        return False


def _extract_user(row: dict, settings) -> dict:
    """Extract user info from auth row, including configured metadata fields."""
    user = {
        "id": row.get("id"),
        "name": row.get("name"),
        "username": row.get(settings.auth.username),
    }
    metadata = {}
    for field in settings.auth.metadata:
        if field in row:
            metadata[field] = row[field]
    if metadata:
        user["metadata"] = metadata
    return user


def _generate_token(user: dict, jwt_key: str) -> str:
    """Generate HS256 JWT with 6-hour expiry."""
    import datetime

    now = datetime.datetime.now(datetime.UTC)
    expire = now + datetime.timedelta(hours=TOKEN_EXPIRY_HOURS)

    claims = {
        "UserInfo": user,
        "nbf": int(now.timestamp()),
        "exp": int(expire.timestamp()),
    }
    return pyjwt.encode(claims, jwt_key, algorithm=JWT_ALGORITHM)


def _json_response(data: dict) -> str:
    return json.dumps(data, default=str)