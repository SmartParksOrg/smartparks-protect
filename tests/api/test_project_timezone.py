"""The project timezone must be a real IANA zone (Tim, 2026-09-16)."""

import pytest

from tests.api.conftest import actor
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


async def test_a_project_timezone_must_be_a_real_zone(client, db):
    admin = await actor(client, db, superuser=True)
    h = admin.headers
    for bad in ("CAT", "Africa/Windhoek ", "Europe/Nowhere"):
        refused = await client.post(
            "/api/v1/projects",
            json={"name": unique_name("Park"), "slug": unique_name("park"), "timezone": bad},
            headers=h,
        )
        assert refused.status_code == 422, refused.text
        assert "IANA name" in refused.text
    created = await client.post(
        "/api/v1/projects",
        json={
            "name": unique_name("Park"),
            "slug": unique_name("park"),
            "timezone": "Africa/Windhoek",
        },
        headers=h,
    )
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]
    changed = await client.patch(
        f"/api/v1/projects/{project_id}", json={"timezone": "Etc/GMT-2"}, headers=h
    )
    assert changed.status_code == 200 and changed.json()["timezone"] == "Etc/GMT-2"
    refused = await client.patch(
        f"/api/v1/projects/{project_id}", json={"timezone": "SAST"}, headers=h
    )
    assert refused.status_code == 422
