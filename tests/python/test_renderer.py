from __future__ import annotations

from fastapi.testclient import TestClient

from prest_py.app import create_app
from prest_py.settings.models import Settings


def _app():
    app = create_app(Settings())

    @app.get("/renderer-test")
    async def renderer_test():
        return [{"count": 4}]

    return app


def test_xml_renderer_matches_frozen_count_contract():
    response = TestClient(_app()).get("/renderer-test?_renderer=xml")

    assert response.status_code == 200
    assert response.text == "<objects><object><count>4</count></object></objects>"
    assert response.headers["content-type"].startswith("application/xml")


def test_default_renderer_remains_json():
    response = TestClient(_app()).get("/renderer-test")

    assert response.status_code == 200
    assert response.json() == [{"count": 4}]
    assert response.headers["content-type"].startswith("application/json")
