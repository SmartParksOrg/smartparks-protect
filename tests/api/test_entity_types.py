"""Entity types with sub-types and the standard catalogue (decisions D166 and D167): every
server holds the seeded types, a sub-type sits one level under a type, and an entity takes the
most specific row."""

import pytest

from shared.catalog.entity_types import ENTITY_TYPE_SEEDS
from shared.enums import Role
from tests.api.conftest import actor, create_project, project_actor
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


async def _all_types(client, headers):
    items, cursor = [], None
    while True:
        query = {"limit": 500, **({"cursor": cursor} if cursor else {})}
        page = (await client.get("/api/v1/entity-types", params=query, headers=headers)).json()
        items += page["items"]
        cursor = page["next_cursor"]
        if not cursor:
            return items


async def test_catalogue_is_seeded_and_entities_take_a_subtype(client, db):
    admin = await actor(client, db, superuser=True)
    by_key = {t["key"]: t for t in await _all_types(client, admin.headers)}
    assert {s.key for s in ENTITY_TYPE_SEEDS} <= set(by_key)
    wildlife, elephant = by_key["wildlife"], by_key["elephant"]
    assert wildlife["parent_id"] is None and wildlife["group_key"] == "tracked"
    assert elephant["parent_id"] == wildlife["id"] and elephant["icon_key"] == "wildlife.elephant"
    assert by_key["four_by_four"]["parent_id"] == by_key["vehicle"]["id"]
    assert by_key["weather_station"]["group_key"] == "environmental"

    project = await create_project(db)
    manager = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    created = await client.post(
        f"/api/v1/projects/{project.id}/entities",
        json={
            "entity_type_id": elephant["id"],
            "name": unique_name("Elephant"),
            "icon_key": "wildlife.forest_elephant",
        },
        headers=manager.headers,
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["entity_type_id"] == elephant["id"]
    assert body["icon_key"] == "wildlife.forest_elephant"


async def test_subtypes_go_one_level_deep(client, db):
    admin = await actor(client, db, superuser=True)
    h = admin.headers
    by_key = {t["key"]: t for t in await _all_types(client, h)}
    wildlife, elephant = by_key["wildlife"], by_key["elephant"]

    under_subtype = await client.post(
        "/api/v1/entity-types",
        json={
            "key": unique_name("et").replace("-", "_"),
            "label": "Calf",
            "group_key": "tracked",
            "icon_key": "wildlife.elephant",
            "parent_id": elephant["id"],
        },
        headers=h,
    )
    assert under_subtype.status_code == 422

    created = await client.post(
        "/api/v1/entity-types",
        json={
            "key": unique_name("et").replace("-", "_"),
            "label": "Okapi",
            "group_key": "tracked",
            "icon_key": "wildlife.generic",
            "parent_id": wildlife["id"],
        },
        headers=h,
    )
    assert created.status_code == 201, created.text
    okapi = created.json()
    assert okapi["parent_id"] == wildlife["id"]

    # a type with sub-types cannot become a sub-type, and not of itself
    demoted = await client.patch(
        f"/api/v1/entity-types/{wildlife['id']}",
        json={"parent_id": by_key["person"]["id"]},
        headers=h,
    )
    assert demoted.status_code == 422
    own = await client.patch(
        f"/api/v1/entity-types/{okapi['id']}", json={"parent_id": okapi["id"]}, headers=h
    )
    assert own.status_code == 422

    # a type in use by its sub-types cannot be deleted
    refused = await client.delete(f"/api/v1/entity-types/{wildlife['id']}", headers=h)
    assert refused.status_code == 409
    gone = await client.delete(f"/api/v1/entity-types/{okapi['id']}", headers=h)
    assert gone.status_code == 204
