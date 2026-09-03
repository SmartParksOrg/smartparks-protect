"""Versioned API routers. Everything under /api/v1 (decision D29)."""

from fastapi import APIRouter

from protect_api.auth.routes import router as auth_router
from protect_api.routers.admin import router as admin_router
from protect_api.routers.catalog import router as catalog_router
from protect_api.routers.data_sources import router as data_sources_router
from protect_api.routers.devices import router as devices_router
from protect_api.routers.entities import router as entities_router
from protect_api.routers.projects import router as projects_router

v1_router = APIRouter()
for router in (
    auth_router,
    projects_router,
    entities_router,
    devices_router,
    catalog_router,
    data_sources_router,
    admin_router,
):
    v1_router.include_router(router)
