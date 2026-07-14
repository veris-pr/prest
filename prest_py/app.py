from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from prest_py.api.middleware import (
    CacheMiddleware,
    GlobalPolicyMiddleware,
    XMLRendererMiddleware,
)
from prest_py.api.routes import build_api_router
from prest_py.cache.response_cache import ResponseCache
from prest_py.plugins import LoadedPlugin, PluginLoadError, load_plugins
from prest_py.postgres.pool import PoolManager
from prest_py.settings import Settings, load_settings

logger = logging.getLogger(__name__)


def _validate_security_configuration(settings: Settings) -> None:
    """Reject security configuration that this runtime cannot enforce.

    JWKS and OpenID discovery need asymmetric-key resolution, which is not yet
    implemented. Starting with either setting would falsely imply protection,
    so fail closed during app creation instead. HMAC global JWT is supported.
    """
    if settings.jwt.jwks or settings.jwt.wellknownurl:
        raise ValueError(
            "jwt.jwks and jwt.wellknownurl are not supported by the Python runtime; "
            "remove them or disable jwt.default"
        )
    if settings.jwt.default and not settings.debug and not settings.jwt.key:
        raise ValueError(
            "jwt.default is enabled but jwt.key is empty; configure an HMAC key "
            "or disable jwt.default"
        )


def create_lifespan(settings: Settings):
    """Create a lifespan context manager that manages the pool lifecycle."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        manager = PoolManager(settings)
        try:
            await manager.connect()
        except Exception:
            logger.exception("pool connect failed on startup")
        app.state.pool_manager = manager
        yield
        await manager.close()
        app.state.pool_manager = None

    return lifespan


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the FastAPI application.

    Keep composition here so later phases can inject settings, pools, gateways,
    middleware, and route dependencies without importing infrastructure from
    route modules.
    """

    resolved = settings or load_settings()
    _validate_security_configuration(resolved)
    loaded_plugins = load_plugins(resolved.plugins.entries)
    app = FastAPI(
        title=resolved.app_name,
        debug=resolved.debug,
        lifespan=create_lifespan(resolved),
    )
    app.state.settings = resolved
    app.state.plugin_entries = tuple(plugin.entry for plugin in loaded_plugins)
    app.state.response_cache = ResponseCache(
        enabled=resolved.cache.enabled,
        default_ttl_minutes=resolved.cache.time,
    )
    _add_plugin_middleware(app, loaded_plugins)
    app.add_middleware(CacheMiddleware)
    # Global policy runs before cache; renderer is outermost and sees every
    # downstream response, matching Go's HandlerSet middleware ordering.
    app.add_middleware(GlobalPolicyMiddleware)
    app.add_middleware(XMLRendererMiddleware)

    # Plugin routes must precede pREST's broad /{database}/{schema} and CRUD
    # patterns, matching Go's plugin route ordering. Exact path+method
    # collisions are rejected first so a plugin cannot silently replace auth,
    # health, catalog, or another plugin route.
    core_router = build_api_router()
    _validate_plugin_route_conflicts(core_router.routes, loaded_plugins)
    for plugin in loaded_plugins:
        for plugin_router in plugin.registration.routers:
            app.include_router(plugin_router)
    app.include_router(core_router)

    if loaded_plugins:
        try:
            # Starlette normally constructs middleware lazily on first request.
            # Build now so an invalid configured plugin fails app creation.
            app.middleware_stack = app.build_middleware_stack()
        except Exception as exc:
            raise PluginLoadError(f"plugin middleware initialization failed: {exc}") from exc
    return app


def _route_signatures(routes, prefix: str = ""):
    """Yield effective path/method pairs from nested FastAPI router wrappers."""
    for route in routes:
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            include_context = getattr(route, "include_context", None)
            included_prefix = getattr(include_context, "prefix", "")
            yield from _route_signatures(
                original_router.routes,
                prefix=f"{prefix}{included_prefix}",
            )
            continue

        path = getattr(route, "path", None)
        if path is not None:
            methods = frozenset(getattr(route, "methods", ()) or {"WEBSOCKET"})
            yield f"{prefix}{path}", methods


def _validate_plugin_route_conflicts(core_routes, plugins: tuple[LoadedPlugin, ...]) -> None:
    seen = [(path, methods, "core") for path, methods in _route_signatures(core_routes)]

    for plugin in plugins:
        for router in plugin.registration.routers:
            for path, methods in _route_signatures(router.routes):
                for seen_path, seen_methods, owner in seen:
                    overlap = methods & seen_methods
                    if path == seen_path and overlap:
                        method_list = ",".join(sorted(overlap))
                        raise PluginLoadError(
                            f"plugin {plugin.entry!r} route conflict with {owner}: "
                            f"{method_list} {path}"
                        )
                seen.append((path, methods, plugin.entry))


def _add_plugin_middleware(app: FastAPI, plugins: tuple[LoadedPlugin, ...]) -> None:
    middleware = [
        middleware_class
        for plugin in plugins
        for middleware_class in plugin.registration.middleware
    ]
    # Starlette executes the last-added middleware first. Reverse configured
    # plugin order here so runtime order still follows configuration order.
    for middleware_class in reversed(middleware):
        app.add_middleware(middleware_class)
