from __future__ import annotations

from fastapi.testclient import TestClient

from prest_py.app import create_app
from prest_py.settings import Settings


def test_health_endpoint_returns_503_without_pool():
    """Without a pool manager, health should return 503 (no DB to ping)."""
    app = create_app(Settings(app_name="test-prest", debug=True))
    # Remove pool manager to simulate no DB
    app.state.pool_manager = None
    client = TestClient(app)

    response = client.get("/_health")

    assert response.status_code == 503
    assert response.content == b""


def test_ready_endpoint_returns_503_without_pool():
    app = create_app(Settings(app_name="test-prest", debug=True))
    app.state.pool_manager = None
    client = TestClient(app)

    response = client.get("/_ready")

    assert response.status_code == 503
    assert response.content == b""


def test_app_stores_settings():
    settings = Settings(app_name="test-prest")
    app = create_app(settings)

    assert app.state.settings is settings