from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import Response

from prest_py.postgres.pool import PoolManager
from prest_py.settings import Settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


def _timeout_seconds(request: Request) -> float:
    settings: Settings = request.app.state.settings
    timeout = settings.http.timeout
    return float(timeout) if timeout > 0 else 60.0


@router.get("/_health")
async def health(request: Request) -> Response:
    """Liveness: ping the default database.

    Returns 200 on success, 503 on failure. Body is empty to match Go contract.
    """
    manager: PoolManager | None = getattr(request.app.state, "pool_manager", None)
    if manager is None:
        return Response(status_code=503)

    timeout = _timeout_seconds(request)
    try:
        ok = await asyncio.wait_for(manager.ping(), timeout=timeout)
    except Exception:
        logger.exception("health check failed")
        ok = False

    return Response(status_code=200 if ok else 503)


@router.get("/_ready")
async def ready(request: Request) -> Response:
    """Readiness: ping default + every registered alias.

    Returns 200 on success, 503 on failure. Body is empty to match Go contract.
    """
    manager: PoolManager | None = getattr(request.app.state, "pool_manager", None)
    if manager is None:
        return Response(status_code=503)

    timeout = _timeout_seconds(request)
    try:
        ok = await asyncio.wait_for(manager.ping_all(), timeout=timeout)
    except Exception:
        logger.exception("ready check failed")
        ok = False

    return Response(status_code=200 if ok else 503)