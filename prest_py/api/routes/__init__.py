from fastapi import APIRouter, Depends

from prest_py.api.deps import crud_protection
from prest_py.api.routes.auth import router as auth_router
from prest_py.api.routes.catalog import router as catalog_router
from prest_py.api.routes.crud import router as crud_router
from prest_py.api.routes.health import router as health_router
from prest_py.api.routes.scripts import router as scripts_router


def build_api_router() -> APIRouter:
    router = APIRouter()
    # Register health first so /_health and /_ready don't get caught by
    # the broader /{database}/{schema}/{table} CRUD pattern.
    router.include_router(health_router)
    # Auth endpoint is public (not behind JWT middleware).
    router.include_router(auth_router)
    # Scripts use /_QUERIES prefix — register before CRUD to avoid
    # /{database}/{schema}/{table} matching.
    router.include_router(scripts_router)
    # Catalog before CRUD so /databases, /schemas, /tables, /show/... and
    # /{database}/{schema} are matched before the 3-segment CRUD pattern.
    router.include_router(catalog_router)
    # CRUD routes get auth + access control protection, matching Go's CRUDStack.
    router.include_router(crud_router, dependencies=[Depends(crud_protection)])
    return router