"""Entity types with sub-types and the standard catalogue (decisions D166 and D167): every
server holds the seeded types, a sub-type sits one level under a type, and an entity takes the
most specific row."""

import pytest

from shared.catalog.entity_fields import STANDARD_FIELDS
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


async def _new_type(client, headers, **more):
    created = await client.post(
        "/api/v1/entity-types",
        json={
            "key": unique_name("et").replace("-", "_"),
            "label": "Made by hand",
            "group_key": "tracked",
            "icon_key": "wildlife.generic",
            **more,
        },
        headers=headers,
    )
    return created


async def test_a_type_reads_with_the_fields_its_entities_have(client, db):
    """Decision D399: the standard fields, then the type's own, a sub-type's after its type's."""
    admin = await actor(client, db, superuser=True)
    h = admin.headers
    by_key = {t["key"]: t for t in await _all_types(client, h)}
    standard = [f.key for f in STANDARD_FIELDS["wildlife"]]
    assert [f["key"] for f in by_key["wildlife"]["fields"]] == standard
    elephant = by_key["elephant"]["fields"]
    assert [f["key"] for f in elephant] == standard
    assert all(f["inherited"] and f["origin"] == "standard" for f in elephant)
    vhf = next(f for f in elephant if f["key"] == "vhf_frequency_mhz")
    assert vhf["unit"] == "MHz" and vhf["panel"] and vhf["kind"] == "number"
    assert by_key["four_by_four"]["fields"][0]["key"] == "licence_plate"

    herd = {"key": "herd", "label": "Herd", "kind": "text"}
    created = await _new_type(
        client, h, parent_id=by_key["wildlife"]["id"], attribute_schema={"fields": [herd]}
    )
    assert created.status_code == 201, created.text
    okapi = created.json()
    assert [f["key"] for f in okapi["fields"]] == [*standard, "herd"]
    assert okapi["fields"][-1]["origin"] == "own" and not okapi["fields"][-1]["inherited"]
    read = await client.get(f"/api/v1/entity-types/{okapi['id']}", headers=h)
    assert read.json()["fields"] == okapi["fields"]

    # an own field is added, ordered and removed by writing the list again
    stripes = {"key": "stripes", "label": "Stripes", "kind": "integer", "min": 0}
    patched = await client.patch(
        f"/api/v1/entity-types/{okapi['id']}",
        json={"attribute_schema": {"fields": [stripes, herd]}},
        headers=h,
    )
    assert patched.status_code == 200, patched.text
    assert [f["key"] for f in patched.json()["fields"]] == [*standard, "stripes", "herd"]
    await client.delete(f"/api/v1/entity-types/{okapi['id']}", headers=h)


async def test_own_fields_that_cannot_stand_are_refused(client, db):
    admin = await actor(client, db, superuser=True)
    h = admin.headers
    by_key = {t["key"]: t for t in await _all_types(client, h)}
    wildlife = by_key["wildlife"]

    # not a list of fields, a key twice, a kind nobody knows
    for schema in (
        {"type": "object"},
        {"fields": [{"key": "a", "label": "A", "kind": "text"}] * 2},
        {"fields": [{"key": "a", "label": "A", "kind": "colour"}]},
    ):
        assert (await _new_type(client, h, attribute_schema=schema)).status_code == 422, schema

    # a sub-type's own field under a key its type has: the standard ear tag
    ear_tag = {"fields": [{"key": "ear_tag", "label": "Tag", "kind": "text"}]}
    clash = await _new_type(client, h, parent_id=wildlife["id"], attribute_schema=ear_tag)
    assert clash.status_code == 422 and "ear_tag" in clash.text
    # and a standard key on the type itself
    own = await client.patch(
        f"/api/v1/entity-types/{by_key['vehicle']['id']}",
        json={"attribute_schema": {"fields": [{"key": "make", "label": "M", "kind": "text"}]}},
        headers=h,
    )
    assert own.status_code == 422 and "make" in own.text

    # a type cannot take a key one of its sub-types holds already
    parent = (await _new_type(client, h)).json()
    herd = {"fields": [{"key": "herd", "label": "Herd", "kind": "text"}]}
    child = await _new_type(client, h, parent_id=parent["id"], attribute_schema=herd)
    assert child.status_code == 201, child.text
    taken = await client.patch(
        f"/api/v1/entity-types/{parent['id']}", json={"attribute_schema": herd}, headers=h
    )
    assert taken.status_code == 422 and "herd" in taken.text
    await client.delete(f"/api/v1/entity-types/{child.json()['id']}", headers=h)
    await client.delete(f"/api/v1/entity-types/{parent['id']}", headers=h)

    # only a server admin writes fields
    project = await create_project(db)
    manager = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    refused = await client.patch(
        f"/api/v1/entity-types/{wildlife['id']}",
        json={"attribute_schema": herd},
        headers=manager.headers,
    )
    assert refused.status_code == 403


async def test_an_entitys_fields_are_checked_by_its_type(client, db):
    """Decision D401: a defined field checked, an empty one left out, an unknown key kept, the
    values kept when the type changes, and nothing required."""
    admin = await actor(client, db, superuser=True)
    by_key = {t["key"]: t for t in await _all_types(client, admin.headers)}
    project = await create_project(db)
    manager = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    base = f"/api/v1/projects/{project.id}/entities"

    created = await client.post(
        base,
        json={
            "entity_type_id": by_key["rhino"]["id"],
            "name": unique_name("Rhino"),
            "attributes": {
                "vhf_frequency_mhz": 148.32,
                "ear_tag": "na 1234 5678",
                "breed": " ",
                "species": "Diceros bicornis",
            },
        },
        headers=manager.headers,
    )
    assert created.status_code == 201, created.text
    rhino = created.json()
    assert rhino["attributes"] == {
        "vhf_frequency_mhz": 148.32,
        "ear_tag": "NA12345678",
        "species": "Diceros bicornis",
    }

    # no field is required: a name alone makes an entity
    bare = await client.post(
        base,
        json={"entity_type_id": by_key["vehicle"]["id"], "name": unique_name("Truck")},
        headers=manager.headers,
    )
    assert bare.status_code == 201 and bare.json()["attributes"] == {}
    truck = bare.json()

    wrong = await client.post(
        base,
        json={
            "entity_type_id": by_key["rhino"]["id"],
            "name": unique_name("Rhino"),
            "attributes": {"vhf_frequency_mhz": 5},
        },
        headers=manager.headers,
    )
    assert wrong.status_code == 422 and "vhf_frequency_mhz" in wrong.text
    wrong = await client.patch(
        f"{base}/{rhino['id']}", json={"attributes": {"sex": "bull"}}, headers=manager.headers
    )
    assert wrong.status_code == 422 and "sex" in wrong.text

    # a vehicle has a plate and no ear tag: the tag's key is no field there and kept as typed
    plated = await client.patch(
        f"{base}/{truck['id']}",
        json={"attributes": {"licence_plate": "N 123-456 W", "ear_tag": "x"}},
        headers=manager.headers,
    )
    assert plated.status_code == 200, plated.text
    assert plated.json()["attributes"] == {"licence_plate": "N 123-456 W", "ear_tag": "x"}

    # the type changes and the values stay
    moved = await client.patch(
        f"{base}/{truck['id']}",
        json={"entity_type_id": by_key["equipment"]["id"]},
        headers=manager.headers,
    )
    assert moved.status_code == 200, moved.text
    assert moved.json()["attributes"]["licence_plate"] == "N 123-456 W"

    # a viewer reads the fields and cannot change them
    read = await client.get(f"{base}/{rhino['id']}", headers=viewer.headers)
    assert read.status_code == 200 and read.json()["attributes"]["ear_tag"] == "NA12345678"
    refused = await client.patch(
        f"{base}/{rhino['id']}", json={"attributes": {}}, headers=viewer.headers
    )
    assert refused.status_code == 403


async def test_an_entity_is_found_by_a_searchable_field(client, db):
    """Decision D406: the plate and the ear tag find the entity, in the site-wide search and
    in the list, for those who may see it."""
    admin = await actor(client, db, superuser=True)
    by_key = {t["key"]: t for t in await _all_types(client, admin.headers)}
    project = await create_project(db)
    manager = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    stranger = await project_actor(client, db, await create_project(db), Role.PROJECT_ADMIN)
    base = f"/api/v1/projects/{project.id}/entities"
    plate = unique_name("PL").upper()
    tag = "ZZ" + unique_name("x")[-8:].upper()
    truck = await client.post(
        base,
        json={
            "entity_type_id": by_key["four_by_four"]["id"],
            "name": unique_name("Truck"),
            "attributes": {"licence_plate": plate, "make": "Zebrawagen"},
        },
        headers=manager.headers,
    )
    cow = await client.post(
        base,
        json={
            "entity_type_id": by_key["cow"]["id"],
            "name": unique_name("Cow"),
            "attributes": {"ear_tag": tag},
        },
        headers=manager.headers,
    )
    assert truck.status_code == 201 and cow.status_code == 201, (truck.text, cow.text)

    async def found(q, headers=manager.headers):
        hits = await client.get("/api/v1/search", params={"q": q}, headers=headers)
        assert hits.status_code == 200, hits.text
        return {h["id"] for h in hits.json()["entities"]}

    assert await found(plate.lower()) == {truck.json()["id"]}
    # typed with spaces, stored without
    assert await found(f"{tag[:4]} {tag[4:]}") == {cow.json()["id"]}
    # a field not marked for the search finds nothing, and another project sees nothing
    assert await found("Zebrawagen") == set()
    assert await found(plate, stranger.headers) == set()

    listed = await client.get(base, params={"q": plate[3:]}, headers=manager.headers)
    assert [e["id"] for e in listed.json()["items"]] == [truck.json()["id"]]
