"""The map's runtime configuration (decision D141): any account reads the MapTiler key, which
is empty until a server sets one; nobody reads it without a login (the access matrix)."""

import pytest

from shared.config import get_settings
from tests.api.conftest import actor

pytestmark = pytest.mark.asyncio


async def test_map_config_serves_the_maptiler_key(client, db):
    user = await actor(client, db)
    response = await client.get("/api/v1/map/config", headers=user.headers)
    assert response.status_code == 200
    assert response.json() == {"maptiler_key": get_settings().maptiler_key or None}
