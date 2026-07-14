"""HTTP middleware for pREST.

Cache middleware: checks endpoint rules, returns cached GET responses, and
stores new responses after handler execution.

Security: the cache acts only on responses that are safe to share by URL.
When auth is enabled, CRUD table routes are user-specific (field permissions
vary by authenticated user) and are excluded so a cached response for one
identity can never be served to another. Health/readiness are always excluded
so cached success cannot mask a database outage. This mirrors Go's placement
of cache lookup behind the auth/access stack for CRUD routes.
"""

from __future__ import annotations

import json
import re
from html import escape
from xml.etree import ElementTree

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from prest_py.api.deps import JWTValidationError, validate_jwt_request
from prest_py.cache.response_cache import ResponseCache
from prest_py.settings.models import Settings

# Paths that must never be served from cache: operational probes.
_NEVER_CACHE_PATHS = frozenset({"/_health", "/_ready"})
_XML_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]")


def _is_crud_path(path: str) -> bool:
    """True for table CRUD routes whose responses can be user-specific."""
    segments = [s for s in path.strip("/").split("/") if s]
    if len(segments) == 3 and not segments[0].startswith("_"):
        return True
    if len(segments) == 4 and segments[0] == "batch":
        return True
    return False


def _exposure_denied(path: str, settings: Settings) -> bool:
    """Return whether global listing exposure policy blocks this request."""
    if not settings.expose.enabled:
        return False
    if path.startswith("/databases"):
        return not settings.expose.databases
    if path.startswith("/schemas"):
        return not settings.expose.schemas
    if path.startswith("/tables"):
        return not settings.expose.tables
    return False


def _xml_name(value: object) -> str:
    name = _XML_NAME_RE.sub("_", str(value))
    if not name or not (name[0].isalpha() or name[0] == "_"):
        name = f"_{name}"
    return name


def _append_xml(parent: ElementTree.Element, key: str, value: object) -> None:
    if isinstance(value, list):
        for item in value:
            child = ElementTree.SubElement(parent, _xml_name(key))
            if isinstance(item, dict):
                for item_key, item_value in item.items():
                    _append_xml(child, str(item_key), item_value)
            elif isinstance(item, list):
                _append_xml(child, "item", item)
            elif item is not None:
                child.text = str(item).lower() if isinstance(item, bool) else str(item)
        return

    child = ElementTree.SubElement(parent, _xml_name(key))
    if isinstance(value, dict):
        for item_key, item_value in value.items():
            _append_xml(child, str(item_key), item_value)
    elif value is not None:
        child.text = str(value).lower() if isinstance(value, bool) else str(value)


def _json_body_to_xml(body: bytes) -> bytes:
    payload = json.loads(body)
    root = ElementTree.Element("objects")
    if isinstance(payload, list):
        _append_xml(root, "object", payload)
    elif isinstance(payload, dict):
        for key, value in payload.items():
            _append_xml(root, str(key), value)
    else:
        _append_xml(root, "object", payload)
    return ElementTree.tostring(root, encoding="utf-8", short_empty_elements=True)


class XMLRendererMiddleware(BaseHTTPMiddleware):
    """Convert JSON responses to the Go-compatible XML envelope on request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        if request.query_params.get("_renderer") != "xml":
            return response

        body = bytearray()
        async for chunk in response.body_iterator:
            body.extend(chunk)

        try:
            xml_body = _json_body_to_xml(bytes(body))
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            error = (
                '<?xml version="1.0" encoding="utf-8"?>\n'
                '<errors xmlns="http://schemas.google.com/g/2005">\n'
                "  <error>\n"
                "    <reason>internal</reason>\n"
                f"    <internalReason>{escape(str(exc))}</internalReason>\n"
                "  </error>\n"
                "  <code>400</code>\n"
                "</errors>"
            )
            return Response(content=error, status_code=400, media_type="application/xml")

        headers = {
            key: value
            for key, value in response.headers.items()
            if key.lower() not in {"content-length", "content-type"}
        }
        return Response(
            content=xml_body,
            status_code=response.status_code,
            headers=headers,
            media_type="application/xml",
        )


class GlobalPolicyMiddleware(BaseHTTPMiddleware):
    """Apply global JWT and catalog-exposure policies before cache and routes.

    This is registered after ``CacheMiddleware`` in ``create_app`` so Starlette
    executes it first. A denied listing or missing global JWT therefore cannot
    be served from a previously cached response.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        settings: Settings = request.app.state.settings

        if settings.jwt.default and not settings.debug:
            try:
                validate_jwt_request(request, settings)
            except JWTValidationError as exc:
                return JSONResponse({"error": str(exc)}, status_code=401)

        if _exposure_denied(request.url.path, settings):
            return JSONResponse({"error": "unauthorized listing"}, status_code=401)

        return await call_next(request)


class CacheMiddleware(BaseHTTPMiddleware):
    """In-memory TTL cache middleware for GET requests.

    Only caches when:
    - Cache is enabled in settings
    - Request method is GET
    - URL path is not an operational probe (health/readiness)
    - URL path is not a user-specific CRUD route when auth is enabled
    - URL path matches endpoint rules (or no endpoint rules configured)
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        settings: Settings = request.app.state.settings
        cache: ResponseCache | None = getattr(request.app.state, "response_cache", None)

        if cache is None or not cache.enabled or request.method != "GET":
            return await call_next(request)

        path = request.url.path
        if path in _NEVER_CACHE_PATHS:
            return await call_next(request)

        # CRUD table responses are user-specific under auth: never cache them by
        # URL, otherwise one user's permitted fields leak to another identity.
        if settings.auth.enabled and _is_crud_path(path):
            return await call_next(request)

        # Check endpoint rules
        endpoints = [
            {"endpoint": ep.endpoint, "enabled": ep.enabled, "time": ep.time}
            for ep in settings.cache.endpoints
        ]
        should_cache, ttl = cache.endpoint_rules(path, endpoints)

        if not should_cache:
            return await call_next(request)

        # Check cache hit
        cache_key = str(request.url)
        cached = cache.get(cache_key)
        if cached is not None:
            return Response(
                content=cached,
                media_type="application/json",
                headers={"Cache-Server": "prestd"},
            )

        # Cache miss — execute handler
        response = await call_next(request)

        # Cache successful GET responses
        if response.status_code == 200:
            body = bytearray()
            async for chunk in response.body_iterator:
                body.extend(chunk)

            cache.set(cache_key, body.decode("utf-8"), ttl)

            # Return a fresh response since we consumed the body iterator
            return Response(
                content=bytes(body),
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        return response