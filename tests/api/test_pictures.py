"""Profile pictures of entities and devices (decision D110): a project admin sets an entity's
picture from any JPEG or PNG and gets back a small WebP square, a viewer may see it but not
change it, removing it clears it, a server admin does the same for a device, and a file that
is not a picture is refused with the reason."""

import io

import pytest
from PIL import Image

from shared.enums import Role
from shared.pictures import PICTURE_SIZE
from tests.api.conftest import actor, create_project, project_actor
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


def _png(width: int = 900, height: int = 600) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "green").save(out, format="PNG")
    return out.getvalue()


async def test_entity_picture_lifecycle(client, db):
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    manager = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    entity_type = (
        await client.post(
            "/api/v1/entity-types",
            json={
                "key": unique_name("et").replace("-", "_"),
                "label": "Animal",
                "group_key": "tracked",
                "icon_key": "wildlife.generic",
            },
            headers=admin.headers,
        )
    ).json()
    entity = (
        await client.post(
            f"/api/v1/projects/{project.id}/entities",
            json={"entity_type_id": entity_type["id"], "name": "Rhino 14"},
            headers=manager.headers,
        )
    ).json()
    assert entity["picture_updated_at"] is None
    base = f"/api/v1/projects/{project.id}/entities/{entity['id']}/picture"

    missing = await client.get(base, headers=viewer.headers)
    assert missing.status_code == 404

    refused = await client.put(
        base, files={"file": ("rhino.png", _png(), "image/png")}, headers=viewer.headers
    )
    assert refused.status_code == 403

    set_response = await client.put(
        base, files={"file": ("rhino.png", _png(), "image/png")}, headers=manager.headers
    )
    assert set_response.status_code == 200, set_response.text
    assert set_response.json()["picture_updated_at"] is not None

    picture = await client.get(base, headers=viewer.headers)
    assert picture.status_code == 200
    assert picture.headers["content-type"] == "image/webp"
    assert picture.headers["cache-control"] == "private, max-age=86400"
    image = Image.open(io.BytesIO(picture.content))
    assert image.format == "WEBP" and image.size == (PICTURE_SIZE, PICTURE_SIZE)

    read = (
        await client.get(
            f"/api/v1/projects/{project.id}/entities/{entity['id']}", headers=viewer.headers
        )
    ).json()
    assert read["picture_updated_at"] == set_response.json()["picture_updated_at"]

    not_a_picture = await client.put(
        base, files={"file": ("notes.txt", b"hello", "text/plain")}, headers=manager.headers
    )
    assert not_a_picture.status_code == 422
    assert "not a JPEG, PNG or WebP" in not_a_picture.text

    removed = await client.delete(base, headers=manager.headers)
    assert removed.status_code == 200 and removed.json()["picture_updated_at"] is None
    assert (await client.get(base, headers=viewer.headers)).status_code == 404

    audit = (await client.get("/api/v1/admin/audit", headers=admin.headers)).json()
    actions = {row["action"] for row in audit if row["object_id"] == entity["id"]}
    assert {"entity.picture_set", "entity.picture_removed"} <= actions


async def test_device_picture_by_server_admin_only(client, db):
    admin = await actor(client, db, superuser=True)
    project = await create_project(db)
    manager = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    device_type = (
        await client.post(
            "/api/v1/device-types",
            json={
                "key": unique_name("gj").replace("-", "_"),
                "label": "Generic",
                "driver_key": "generic_json",
            },
            headers=admin.headers,
        )
    ).json()
    device = (
        await client.post(
            "/api/v1/devices",
            json={"device_type_id": device_type["id"], "name": unique_name("SP")},
            headers=admin.headers,
        )
    ).json()
    await client.post(
        f"/api/v1/devices/{device['id']}/project-assignments",
        json={"project_id": str(project.id), "valid_from": "2026-01-01T00:00:00+00:00"},
        headers=admin.headers,
    )
    base = f"/api/v1/devices/{device['id']}/picture"
    assert (
        await client.put(
            base, files={"file": ("d.png", _png(), "image/png")}, headers=manager.headers
        )
    ).status_code == 403
    set_response = await client.put(
        base, files={"file": ("d.jpg", _png(), "image/png")}, headers=admin.headers
    )
    assert set_response.status_code == 200, set_response.text
    assert set_response.json()["picture_updated_at"] is not None
    # a member of a project the device is assigned to sees it
    picture = await client.get(base, headers=manager.headers)
    assert picture.status_code == 200 and picture.headers["content-type"] == "image/webp"
    assert (await client.delete(base, headers=admin.headers)).status_code == 200
    assert (await client.get(base, headers=manager.headers)).status_code == 404
