from __future__ import annotations

import time

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from prest_py.app import create_app
from prest_py.plugins import PluginLoadError, load_plugins
from prest_py.settings.models import Settings
from tests.python import plugin_fixtures

ENTRY = "tests.python.plugin_fixtures:register"


def test_load_plugin_registration():
    loaded = load_plugins([ENTRY])

    assert len(loaded) == 1
    assert loaded[0].entry == ENTRY
    assert len(loaded[0].registration.routers) == 1
    assert len(loaded[0].registration.middleware) == 1


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ("missing-format", "expected 'package.module:register'"),
        ("tests.python.missing_plugin:register", "could not import plugin module"),
        ("tests.python.plugin_fixtures:missing", "plugin callable not found"),
        ("tests.python.plugin_fixtures:not_callable", "not callable"),
        ("tests.python.plugin_fixtures:empty_registration", "empty registration"),
        ("tests.python.plugin_fixtures:invalid_registration", "must return"),
        ("tests.python.plugin_fixtures:invalid_router_registration", "non-APIRouter"),
        ("tests.python.plugin_fixtures:invalid_middleware_registration", "non-class"),
        ("tests.python.plugin_fixtures:exploding_registration", "registration failed"),
    ],
)
def test_invalid_plugin_fails_fast(entry, message):
    with pytest.raises(PluginLoadError, match=message):
        load_plugins([entry])


def test_duplicate_plugin_fails_fast():
    with pytest.raises(PluginLoadError, match="duplicate plugin entry"):
        load_plugins([ENTRY, ENTRY])


def test_create_app_registers_plugin_route_and_middleware():
    app = create_app(Settings(plugins={"entries": [ENTRY]}))
    client = TestClient(app)

    response = client.get("/plugin/hello")

    assert response.status_code == 200
    assert response.json() == {"plugin": "hello"}
    assert response.headers["X-pREST-Plugin"] == "loaded"
    assert app.state.plugin_entries == (ENTRY,)


def test_empty_plugin_config_has_no_extension_route():
    app = create_app(Settings())
    response = TestClient(app).get("/plugin/hello")

    # The broad /{database}/{schema} route still matches the request, but no
    # exact plugin route was registered.
    assert not any(getattr(route, "path", None) == "/plugin/hello" for route in app.routes)
    assert response.status_code == 503
    assert response.headers.get("X-pREST-Plugin") is None


def test_plugin_middleware_runs_in_configuration_order():
    plugin_fixtures.middleware_events.clear()
    settings = Settings(
        plugins={
            "entries": [
                "tests.python.plugin_fixtures:register_first_middleware",
                "tests.python.plugin_fixtures:register_second_middleware",
            ]
        }
    )
    client = TestClient(create_app(settings))

    client.get("/_health")

    assert plugin_fixtures.middleware_events == ["first", "second"]


def test_global_jwt_policy_runs_before_plugin_middleware():
    key = "x" * 32
    settings = Settings(
        debug=False,
        jwt={"default": True, "key": key, "whitelist": []},
        plugins={"entries": [ENTRY]},
    )
    client = TestClient(create_app(settings))

    denied = client.get("/plugin/hello")
    now = int(time.time())
    token = pyjwt.encode(
        {"UserInfo": {"username": "plugin-user"}, "nbf": now, "exp": now + 60},
        key,
        algorithm="HS256",
    )
    allowed = client.get(
        "/plugin/hello",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert denied.status_code == 401
    assert denied.headers.get("X-pREST-Plugin") is None
    assert allowed.status_code == 200
    assert allowed.headers["X-pREST-Plugin"] == "loaded"


def test_invalid_configured_plugin_fails_app_creation():
    settings = Settings(plugins={"entries": ["tests.python.plugin_fixtures:missing"]})

    with pytest.raises(PluginLoadError, match="callable not found"):
        create_app(settings)


def test_broken_plugin_middleware_fails_app_creation():
    settings = Settings(
        plugins={"entries": ["tests.python.plugin_fixtures:broken_middleware_registration"]}
    )

    with pytest.raises(PluginLoadError, match="middleware initialization failed"):
        create_app(settings)


def test_plugin_cannot_replace_exact_core_route():
    settings = Settings(
        plugins={"entries": ["tests.python.plugin_fixtures:conflicting_route_registration"]}
    )

    with pytest.raises(PluginLoadError, match=r"route conflict with core: POST /auth"):
        create_app(settings)
