"""Request-time dependencies for protected routes.

Ports Go middleware behavior:
- AuthMiddleware: validates JWT Bearer token, extracts user info
- AccessControl: checks table permissions by HTTP method

These are applied as FastAPI dependencies on CRUD routes only,
matching Go's CRUDStack that wraps /{database}/{schema}/{table}.
"""

from __future__ import annotations

import logging
import re
import time

import jwt as pyjwt
from fastapi import HTTPException, Request

from prest_py.domain.permissions import table_permissions
from prest_py.settings.models import Settings

logger = logging.getLogger(__name__)

_METHOD_PERMISSIONS = {
    "GET": "read",
    "POST": "write",
    "PUT": "write",
    "PATCH": "write",
    "DELETE": "delete",
}


class JWTValidationError(Exception):
    """Raised when a bearer token is missing or cannot be validated."""


def _match_whitelist(url: str, patterns: list[str]) -> bool:
    """Check if URL matches any whitelist regex pattern."""
    for pattern in patterns:
        try:
            if re.search(pattern, url):
                return True
        except re.error:
            continue
    return False


def validate_jwt_request(request: Request, settings: Settings) -> dict | None:
    """Validate a bearer token unless the URL is whitelisted.

    Returns the decoded claims, or ``None`` when the URL is whitelisted.
    Callers choose whether the claims should become request user context:
    CRUD auth does; global default JWT intentionally only validates, matching
    Go's separate `JwtMiddleware` behavior.
    """
    if _match_whitelist(request.url.path, settings.jwt.whitelist):
        return None

    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "", 1) if auth_header else ""
    if not token:
        raise JWTValidationError("authorization token is empty")
    if not settings.jwt.key:
        raise JWTValidationError("JWT verification key is empty; refusing to validate token")

    try:
        payload = pyjwt.decode(token, settings.jwt.key, algorithms=[settings.jwt.algo])
    except pyjwt.PyJWTError as exc:
        if isinstance(exc, (pyjwt.ExpiredSignatureError, pyjwt.ImmatureSignatureError)):
            raise JWTValidationError("failed claims validated") from None
        raise JWTValidationError("failed JWT token parser") from None

    # Keep explicit checks for claims omitted from PyJWT's configured defaults.
    now = int(time.time())
    nbf = payload.get("nbf", 0)
    exp = payload.get("exp", 0)
    if exp and now > exp:
        raise JWTValidationError("failed claims validated")
    if nbf and now < nbf:
        raise JWTValidationError("failed claims validated")
    return payload


async def auth_dependency(request: Request) -> None:
    """Validate JWT token when CRUD auth is enabled.

    Raises HTTPException(401) on failure. Claims are stored for table and field
    permission resolution only on this CRUD-specific auth path.
    """
    settings: Settings = request.app.state.settings
    if not settings.auth.enabled:
        return

    try:
        payload = validate_jwt_request(request, settings)
    except JWTValidationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from None

    if payload is not None:
        request.state.user_info = payload.get("UserInfo", {})


async def access_control_dependency(request: Request) -> None:
    """Check table permissions for CRUD routes.

    Raises HTTPException(401) on failure. Matches Go AccessControl.
    Must run after auth_dependency so user_info is available.
    """
    settings: Settings = request.app.state.settings

    database = request.path_params.get("database", "")
    schema = request.path_params.get("schema", "")
    table = request.path_params.get("table", "")

    if not database or not schema or not table:
        return

    permission = _METHOD_PERMISSIONS.get(request.method, "")
    if not permission:
        return

    user_info = getattr(request.state, "user_info", {})
    username = user_info.get("username", "") if isinstance(user_info, dict) else ""

    if table_permissions(settings, database, schema, table, permission, username):
        return

    raise HTTPException(status_code=401, detail="authorization required")


async def crud_protection(request: Request) -> None:
    """Combined auth + access control for CRUD routes.

    Runs auth first, then access control. If auth rejects,
    access control never runs.
    """
    await auth_dependency(request)
    await access_control_dependency(request)