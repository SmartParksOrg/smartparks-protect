"""Versioned API routers. Everything under /api/v1 (decision D29)."""

from fastapi import APIRouter

from protect_api.auth.routes import router as auth_router
from protect_api.oauth.routes import router as oauth_router
from protect_api.realtime import router as realtime_router
from protect_api.routers.admin import router as admin_router
from protect_api.routers.analytics import router as analytics_router
from protect_api.routers.attention import router as attention_router
from protect_api.routers.automations import admin_router as admin_automations_router
from protect_api.routers.automations import router as automations_router
from protect_api.routers.backups import router as backups_router
from protect_api.routers.catalog import router as catalog_router
from protect_api.routers.control import router as control_router
from protect_api.routers.curation import router as curation_router
from protect_api.routers.data import router as data_router
from protect_api.routers.data_sources import router as data_sources_router
from protect_api.routers.devices import router as devices_router
from protect_api.routers.entities import router as entities_router
from protect_api.routers.events import admin_router as admin_events_router
from protect_api.routers.events import router as events_router
from protect_api.routers.exports import router as exports_router
from protect_api.routers.gateways import admin_router as admin_gateways_router
from protect_api.routers.gateways import router as gateways_router
from protect_api.routers.ingest import router as ingest_router
from protect_api.routers.integrations import router as integrations_router
from protect_api.routers.log_files import router as log_files_router
from protect_api.routers.map import router as map_router
from protect_api.routers.network import router as network_router
from protect_api.routers.projects import router as projects_router
from protect_api.routers.rules import router as rules_router

v1_router = APIRouter()
for router in (
    auth_router,
    oauth_router,
    projects_router,
    entities_router,
    devices_router,
    catalog_router,
    data_sources_router,
    admin_router,
    ingest_router,
    attention_router,
    data_router,
    network_router,
    map_router,
    analytics_router,
    exports_router,
    rules_router,
    events_router,
    admin_events_router,
    automations_router,
    admin_automations_router,
    control_router,
    curation_router,
    log_files_router,
    integrations_router,
    gateways_router,
    admin_gateways_router,
    backups_router,
    realtime_router,
):
    v1_router.include_router(router)
