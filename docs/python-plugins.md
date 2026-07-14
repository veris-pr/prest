# Python plugin API

pREST Python plugins are trusted Python packages loaded from import strings during app creation. They can add FastAPI routes and global middleware without changing pREST source.

Go `.so` plugins are not compatible. Python does not expose the legacy `/_PLUGIN/{file}/{func}` dispatcher.

## Minimal plugin

```python
# my_package/prest_plugin.py
from fastapi import APIRouter
from starlette.middleware.base import BaseHTTPMiddleware

from prest_py.plugins import PluginRegistration

router = APIRouter(prefix="/my-plugin", tags=["my-plugin"])


@router.get("/hello")
async def hello():
    return {"message": "hello"}


class PluginHeaderMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["X-My-Plugin"] = "enabled"
        return response


def register() -> PluginRegistration:
    return PluginRegistration(
        routers=(router,),
        middleware=(PluginHeaderMiddleware,),
    )
```

Install `my_package` in the same Python environment/image as pREST, then configure its callable:

```toml
[plugins]
entries = ["my_package.prest_plugin:register"]
```

Environment alternatives:

```sh
PREST_PLUGIN_ENTRIES='["my_package.prest_plugin:register"]'
# or
PREST_PLUGIN_ENTRIES='my_package.prest_plugin:register,other_package.plugin:register'
```

Entries load in configuration order.

## Contract

Each entry must:

1. Use `package.module:callable` syntax.
2. Resolve to a zero-argument callable.
3. Return `PluginRegistration`.
4. Include at least one FastAPI `APIRouter` or middleware class.

Configuration failures stop app creation. Invalid TOML/env plugin value types raise a configuration `ValueError`; import/registration/middleware failures raise `PluginLoadError`. pREST does not silently skip a configured extension.

## Ordering and security

Runtime order:

```text
XML renderer
→ global JWT and exposure policy
→ response cache
→ plugin middleware (configuration order)
→ plugin/core routes
```

Exact plugin routes register before pREST's broad `/{database}/{schema}` and `/{database}/{schema}/{table}` patterns; otherwise those dynamic routes would consume plugin paths. App creation rejects overlapping methods on an exact built-in or previously registered plugin path, preventing accidental replacement of auth, health, catalog, or another extension.

Plugin middleware runs inside the response cache and is not invoked on cache hits. Do not implement authentication, authorization, audit accounting, or other must-run policy in plugin middleware. Use pREST's outer global policy (`jwt.default`) or an external gateway for those controls.

`auth.enabled` protects core CRUD dependencies; it does not automatically protect custom plugin routes. Enable `jwt.default` outside debug mode or add explicit FastAPI dependencies to the plugin router when custom routes require authentication.

Plugins are trusted in-process code. Install only reviewed packages: plugin code can read process environment, app state, requests, and responses with the same OS permissions as pREST.

## Safe defaults and limits

- Empty `plugins.entries` disables plugins.
- No hot reload: restart pREST after plugin/config changes.
- Middleware constructors receive only the ASGI app; constructor options are not configurable yet.
- No plugin dependency graph or lifecycle/startup hooks.
- Built-in JWT/exposure policy remains outside plugin middleware and cannot be reordered through registration.

## Testing a plugin

Use the normal FastAPI test client:

```python
from fastapi.testclient import TestClient

from prest_py.app import create_app
from prest_py.settings.models import Settings

settings = Settings(
    plugins={"entries": ["my_package.prest_plugin:register"]},
)
client = TestClient(create_app(settings))

assert client.get("/my-plugin/hello").json() == {"message": "hello"}
```
