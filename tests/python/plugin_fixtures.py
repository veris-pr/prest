from __future__ import annotations

from fastapi import APIRouter
from starlette.middleware.base import BaseHTTPMiddleware

from prest_py.plugins import PluginRegistration

router = APIRouter()
conflict_router = APIRouter()


@router.get("/plugin/hello")
async def plugin_hello():
    return {"plugin": "hello"}


@conflict_router.post("/auth")
async def conflicting_auth_route():
    return {"plugin": "must-not-replace-auth"}


class PluginHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-pREST-Plugin"] = "loaded"
        return response


def register() -> PluginRegistration:
    return PluginRegistration(
        routers=(router,),
        middleware=(PluginHeaderMiddleware,),
    )


def conflicting_route_registration() -> PluginRegistration:
    return PluginRegistration(routers=(conflict_router,))


def empty_registration() -> PluginRegistration:
    return PluginRegistration()


def invalid_registration():
    return {"routers": [router]}


def invalid_router_registration() -> PluginRegistration:
    return PluginRegistration(routers=("not-a-router",))


def invalid_middleware_registration() -> PluginRegistration:
    return PluginRegistration(middleware=("not-a-class",))


class BrokenMiddleware:
    pass


def broken_middleware_registration() -> PluginRegistration:
    return PluginRegistration(middleware=(BrokenMiddleware,))


def exploding_registration():
    raise RuntimeError("fixture explosion")


middleware_events: list[str] = []


class FirstOrderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        middleware_events.append("first")
        return await call_next(request)


class SecondOrderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        middleware_events.append("second")
        return await call_next(request)


def register_first_middleware() -> PluginRegistration:
    return PluginRegistration(middleware=(FirstOrderMiddleware,))


def register_second_middleware() -> PluginRegistration:
    return PluginRegistration(middleware=(SecondOrderMiddleware,))


not_callable = PluginRegistration(routers=(router,))
