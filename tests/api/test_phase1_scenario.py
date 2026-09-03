"""Phase 1 exit criteria as one scenario.

A server admin invites a project admin, who creates a project (server admin does), a data
source, a device with an external identity, assigns it to the project and to an entity with
effective dates, hands it over to a second project, and every step is audited.
"""

from datetime import UTC, datetime

import pytest

from tests.api.conftest import PASSWORD, actor, login
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 3, 1, tzinfo=UTC)
T_ENTITY = datetime(2026, 3, 2, tzinfo=UTC)
T_HANDOVER = datetime(2026, 8, 10, tzinfo=UTC)


async def test_full_onboarding_and_handover(client, db):
    server_admin = await actor(client, db, superuser=True)
    h = server_admin.headers

    # Server admin creates two projects and the catalogues.
    project_a = (
        await client.post(
            "/api/v1/projects",
            json={"name": unique_name("Park A"), "slug": unique_name("park-a")},
            headers=h,
        )
    ).json()
    project_b = (
        await client.post(
            "/api/v1/projects",
            json={"name": unique_name("Park B"), "slug": unique_name("park-b")},
            headers=h,
        )
    ).json()
    entity_type = (
        await client.post(
            "/api/v1/entity-types",
            json={
                "key": unique_name("animal").replace("-", "_"),
                "label": "Animal",
                "group_key": "tracked",
                "icon_key": "wildlife.rhino",
            },
            headers=h,
        )
    ).json()
    device_type = (
        await client.post(
            "/api/v1/device-types",
            json={
                "key": unique_name("collar").replace("-", "_"),
                "label": "OpenCollar",
                "driver_key": "opencollar",
            },
            headers=h,
        )
    ).json()
    data_source = (
        await client.post(
            "/api/v1/data-sources",
            json={
                "name": unique_name("ChirpStack"),
                "adapter_key": "generic_http",
                "credentials": {"api_token": "secret"},
                "project_ids": [project_a["id"]],
            },
            headers=h,
        )
    ).json()
    assert data_source["has_credentials"] is True and "credentials" not in data_source

    # Server admin invites a project admin for A, who registers.
    invitation = await client.post(
        f"/api/v1/projects/{project_a['id']}/invitations",
        json={"email": f"{unique_name('pa')}@example.org", "role": "project-admin"},
        headers=h,
    )
    assert invitation.status_code == 201, invitation.text
    assert invitation.json()["mail_sent"] is False  # no SMTP in tests, logged instead
    token = (
        await db.get(
            type(
                await db.get(
                    __import__("shared.models", fromlist=["Invitation"]).Invitation,
                    invitation.json()["id"],
                )
            ),
            invitation.json()["id"],
        )
    ).token
    registered = await client.post(
        "/api/v1/auth/register",
        json={"token": token, "password": PASSWORD, "full_name": "Park Admin"},
    )
    assert registered.status_code == 201, registered.text
    pa_headers = {"Authorization": f"Bearer {await login(client, registered.json()['email'])}"}

    # Project admin creates an entity in A; cannot touch B.
    rhino = await client.post(
        f"/api/v1/projects/{project_a['id']}/entities",
        json={
            "entity_type_id": entity_type["id"],
            "name": "Rhino 14",
            "geometry": {"type": "Point", "coordinates": [31.5, -24.9]},
        },
        headers=pa_headers,
    )
    assert rhino.status_code == 201, rhino.text
    assert rhino.json()["geometry"] == {"type": "Point", "coordinates": [31.5, -24.9]}
    assert (
        await client.get(f"/api/v1/projects/{project_b['id']}/entities", headers=pa_headers)
    ).status_code == 403

    # Server admin creates the device with an external identity; project admin assigns it to A.
    device = (
        await client.post(
            "/api/v1/devices",
            json={
                "device_type_id": device_type["id"],
                "name": unique_name("SP05"),
                "status": "active",
            },
            headers=h,
        )
    ).json()
    identity = await client.post(
        f"/api/v1/devices/{device['id']}/identities",
        json={"data_source_id": data_source["id"], "external_id": "70B3D57ED0001234"},
        headers=h,
    )
    assert identity.status_code == 201, identity.text
    assigned = await client.post(
        f"/api/v1/devices/{device['id']}/project-assignments",
        json={"project_id": project_a["id"], "valid_from": T0.isoformat()},
        headers=pa_headers,
    )
    assert assigned.status_code == 201, assigned.text
    # A second overlapping project assignment is rejected.
    overlap = await client.post(
        f"/api/v1/devices/{device['id']}/project-assignments",
        json={"project_id": project_b["id"], "valid_from": T_ENTITY.isoformat()},
        headers=h,
    )
    assert overlap.status_code == 409

    # Project admin assigns the device to the rhino.
    entity_assignment = await client.post(
        f"/api/v1/projects/{project_a['id']}/entity-assignments",
        json={
            "device_id": device["id"],
            "entity_id": rhino.json()["id"],
            "valid_from": T_ENTITY.isoformat(),
        },
        headers=pa_headers,
    )
    assert entity_assignment.status_code == 201, entity_assignment.text
    # Before the device joined the project, an entity assignment is refused.
    too_early = await client.post(
        f"/api/v1/projects/{project_a['id']}/entity-assignments",
        json={
            "device_id": device["id"],
            "entity_id": rhino.json()["id"],
            "valid_from": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        },
        headers=pa_headers,
    )
    assert too_early.status_code == 409

    # The project admin sees the device in A's device list and in detail.
    listed = await client.get(
        "/api/v1/devices", params={"project_id": project_a["id"]}, headers=pa_headers
    )
    assert [d["id"] for d in listed.json()["items"]] == [device["id"]]
    detail = await client.get(f"/api/v1/devices/{device['id']}", headers=pa_headers)
    assert detail.status_code == 200
    assert len(detail.json()["project_assignments"]) == 1
    assert detail.json()["external_identities"][0]["external_id"] == "70B3D57ED0001234"

    # Handover to B: the project admin of A alone may not (not admin of B); the server admin may.
    handover_body = {
        "project_id": project_b["id"],
        "effective_at": T_HANDOVER.isoformat(),
        "reason": "moved to Park B",
    }
    assert (
        await client.post(
            f"/api/v1/devices/{device['id']}/handover", json=handover_body, headers=pa_headers
        )
    ).status_code == 403
    handover = await client.post(
        f"/api/v1/devices/{device['id']}/handover", json=handover_body, headers=h
    )
    assert handover.status_code == 201, handover.text
    assert handover.json()["project_id"] == project_b["id"]
    assert handover.json()["valid_from"].startswith("2026-08-10")

    detail = (await client.get(f"/api/v1/devices/{device['id']}", headers=h)).json()
    pa = sorted(detail["project_assignments"], key=lambda a: a["valid_from"])
    assert pa[0]["project_id"] == project_a["id"] and pa[0]["valid_to"].startswith("2026-08-10")
    assert pa[1]["project_id"] == project_b["id"] and pa[1]["valid_to"] is None
    assert detail["entity_assignments"][0]["valid_to"].startswith("2026-08-10")

    # A's admin still sees the historical assignment to A and not the one to B (28.12).
    detail_a = (await client.get(f"/api/v1/devices/{device['id']}", headers=pa_headers)).json()
    assert [a["project_id"] for a in detail_a["project_assignments"]] == [project_a["id"]]
    assert (
        await client.get(
            "/api/v1/devices", params={"project_id": project_a["id"]}, headers=pa_headers
        )
    ).json()["items"] == []

    # Every step is audited.
    audit = (await client.get("/api/v1/admin/audit", params={"limit": 50}, headers=h)).json()
    actions = {entry["action"] for entry in audit}
    assert {
        "project.created",
        "invitation.created",
        "user.registered",
        "entity.created",
        "device.created",
        "external_identity.created",
        "project_assignment.created",
        "entity_assignment.created",
        "device.handover",
        "data_source.created",
    } <= actions
    project_audit = (
        await client.get(f"/api/v1/projects/{project_a['id']}/audit", headers=pa_headers)
    ).json()
    assert any(entry["action"] == "entity.created" for entry in project_audit)
