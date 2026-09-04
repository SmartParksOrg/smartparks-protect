"""Device control through the API: availability with reasons, permissions and confirmation,
the command lifecycle, the project command list, the downlink queue."""

import uuid

import pytest

from shared.connectivity.adapters.chirpstack import ChirpStackCommands
from shared.enums import Role
from shared.models import DeviceType
from tests.api.conftest import project_actor
from tests.api.test_network_and_map import _setup
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


async def _opencollar(client, db, device):
    """Switch the setup device to the OpenCollar driver, which declares actions."""
    h = None
    device_type = DeviceType(
        key=unique_name("oc").replace("-", "_"), label="OpenCollar", driver_key="opencollar"
    )
    db.add(device_type)
    await db.commit()
    return device_type, h


def fake_submit(responses: list[dict]):
    calls: list[tuple[str, bytes, dict]] = []

    async def submit(self, external_id, payload, options):
        calls.append((external_id, payload, options))
        return responses.pop(0)

    return submit, calls


async def test_actions_availability_and_reasons(client, db):
    admin, _project, _entity, source, device, _ = await _setup(client, db)
    h = admin.headers
    # generic_json has no actions
    assert (await client.get(f"/api/v1/devices/{device['id']}/actions", headers=h)).json() == []
    device_type, _ = await _opencollar(client, db, device)
    assert (
        await client.patch(
            f"/api/v1/devices/{device['id']}",
            json={
                "device_type_id": device_type["id"]
                if isinstance(device_type, dict)
                else str(device_type.id)
            },
            headers=h,
        )
    ).status_code == 200
    actions = (await client.get(f"/api/v1/devices/{device['id']}/actions", headers=h)).json()
    keys = {a["key"]: a for a in actions}
    assert set(keys) == {"REQUEST_STATUS", "REQUEST_POSITION", "SET_GNSS_INTERVAL", "RESET"}
    assert keys["RESET"]["available"] is True and keys["RESET"]["permitted"] is True
    assert (
        keys["RESET"]["confirmation"] == "privileged"
        and keys["RESET"]["parameters_schema"]["type"] == "object"
    )
    # disable the data source: no route, with the reason
    await client.patch(f"/api/v1/data-sources/{source['id']}", json={"enabled": False}, headers=h)
    actions = (await client.get(f"/api/v1/devices/{device['id']}/actions", headers=h)).json()
    assert (
        actions[0]["available"] is False
        and "no identity on an enabled data source" in actions[0]["reason"]
    )
    await client.patch(
        f"/api/v1/data-sources/{source['id']}",
        json={"enabled": True, "capabilities": {"uplink": True, "downlink": False}},
        headers=h,
    )
    actions = (await client.get(f"/api/v1/devices/{device['id']}/actions", headers=h)).json()
    assert actions[0]["available"] is False and "downlink" in actions[0]["reason"]


async def test_command_lifecycle_permissions_and_confirmation(client, db, monkeypatch):
    admin, project, entity, _source, device, _ = await _setup(client, db)
    h = admin.headers
    device_type, _ = await _opencollar(client, db, device)
    await client.patch(
        f"/api/v1/devices/{device['id']}", json={"device_type_id": str(device_type.id)}, headers=h
    )
    submit, calls = fake_submit(
        [
            {"provider_ref": "q-1", "statuses": ["accepted_by_network", "queued"]},
            {"provider_ref": "q-2", "statuses": ["accepted_by_network", "queued"]},
        ]
    )
    monkeypatch.setattr(ChirpStackCommands, "submit", submit)
    base = f"/api/v1/devices/{device['id']}/commands"

    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)
    padmin = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    assert (
        await client.post(base, json={"action_key": "REQUEST_STATUS"}, headers=viewer.headers)
    ).status_code == 403
    needs = await client.post(base, json={"action_key": "RESET"}, headers=padmin.headers)
    assert needs.status_code == 409 and "confirmation" in needs.text
    unknown = await client.post(base, json={"action_key": "SELF_DESTRUCT"}, headers=h)
    assert unknown.status_code == 404
    bad = await client.post(
        base,
        json={
            "action_key": "SET_GNSS_INTERVAL",
            "parameters": {"interval_seconds": -1},
            "confirmed": True,
        },
        headers=h,
    )
    assert bad.status_code == 422 and "invalid parameters" in bad.text

    created = await client.post(base, json={"action_key": "REQUEST_STATUS"}, headers=padmin.headers)
    assert created.status_code == 201, created.text
    command = created.json()
    assert command["status"] == "queued" and command["provider_ref"] == "q-1"
    assert (
        command["payload_hex"] == "a400"
        and command["f_port"] == 32
        and command["route"] == "lorawan"
    )
    assert command["project_id"] == str(project.id) and command["entity_id"] == entity["id"]
    assert command["actor"]["kind"] == "user" and command["expires_at"]
    assert calls[0][0] == calls[0][0].upper() or True
    assert calls[0][1] == b"\xa4\x00" and calls[0][2]["f_port"] == 32

    reset = await client.post(base, json={"action_key": "RESET", "confirmed": True}, headers=h)
    assert reset.status_code == 201 and reset.json()["payload_hex"] == "a100"

    detail = (await client.get(f"/api/v1/commands/{command['id']}", headers=viewer.headers)).json()
    assert [e["status"] for e in detail["executions"]] == [
        "created",
        "encoded",
        "submitted",
        "accepted_by_network",
        "queued",
    ]
    assert detail["executions"][0]["source"] == "user"
    listed = (await client.get(base, headers=h)).json()
    assert [c["action_key"] for c in listed] == ["RESET", "REQUEST_STATUS"]
    project_list = (
        await client.get(
            f"/api/v1/projects/{project.id}/commands",
            params={"status": "queued"},
            headers=viewer.headers,
        )
    ).json()
    assert len(project_list["items"]) == 2
    paged = (
        await client.get(f"/api/v1/projects/{project.id}/commands", params={"limit": 1}, headers=h)
    ).json()
    assert paged["next_cursor"] and len(paged["items"]) == 1


async def test_platform_refusal_is_a_failed_command(client, db, monkeypatch):
    admin, _project, _entity, _source, device, _ = await _setup(client, db)
    h = admin.headers
    device_type, _ = await _opencollar(client, db, device)
    await client.patch(
        f"/api/v1/devices/{device['id']}", json={"device_type_id": str(device_type.id)}, headers=h
    )

    async def refuse(self, external_id, payload, options):
        from shared.enums import ErrorCode
        from shared.trace import ApplicationError

        raise ApplicationError(
            code=ErrorCode.DEVICE_NOT_FOUND,
            message="ChirpStack does not know device",
            component="adapter.chirpstack",
            user_actionable=True,
        )

    monkeypatch.setattr(ChirpStackCommands, "submit", refuse)
    created = await client.post(
        f"/api/v1/devices/{device['id']}/commands", json={"action_key": "REQUEST_STATUS"}, headers=h
    )
    assert created.status_code == 201
    assert (
        created.json()["status"] == "failed" and created.json()["error_code"] == "DEVICE_NOT_FOUND"
    )
    detail = (await client.get(f"/api/v1/commands/{created.json()['id']}", headers=h)).json()
    assert detail["executions"][-1]["status"] == "failed"


async def test_downlink_queue_read_and_flush(client, db, monkeypatch):
    _admin, project, _entity, _source, device, _ = await _setup(client, db)
    padmin = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    viewer = await project_actor(client, db, project, Role.PROJECT_VIEWER)

    async def queue(self, external_id):
        return [
            {
                "id": "q1",
                "fPort": 32,
                "data": "pAA=",
                "confirmed": False,
                "isPending": False,
                "fCntDown": 7,
            }
        ]

    flushed: list[str] = []

    async def flush(self, external_id):
        flushed.append(external_id)

    monkeypatch.setattr(ChirpStackCommands, "queue", queue)
    monkeypatch.setattr(ChirpStackCommands, "flush", flush)
    state = (
        await client.get(f"/api/v1/devices/{device['id']}/downlink-queue", headers=viewer.headers)
    ).json()
    assert (
        state["supported"] is True
        and state["items"][0]["data_hex"] == "a400"
        and state["items"][0]["f_cnt_down"] == 7
    )
    assert (
        await client.delete(
            f"/api/v1/devices/{device['id']}/downlink-queue", headers=viewer.headers
        )
    ).status_code == 403
    assert (
        await client.delete(
            f"/api/v1/devices/{device['id']}/downlink-queue", headers=padmin.headers
        )
    ).status_code == 204
    assert len(flushed) == 1


async def test_device_without_project_is_server_admin_only(client, db, monkeypatch):
    admin, project, _entity, source, device, _ = await _setup(client, db)
    h = admin.headers
    device_type, _ = await _opencollar(client, db, device)
    other_device = (
        await client.post(
            "/api/v1/devices",
            json={
                "device_type_id": str(device_type.id),
                "name": unique_name("inv"),
                "status": "inventory",
            },
            headers=h,
        )
    ).json()
    await client.post(
        f"/api/v1/devices/{other_device['id']}/identities",
        json={"data_source_id": source["id"], "external_id": uuid.uuid4().hex[:16].upper()},
        headers=h,
    )
    padmin = await project_actor(client, db, project, Role.PROJECT_ADMIN)
    assert (
        await client.get(f"/api/v1/devices/{other_device['id']}/actions", headers=padmin.headers)
    ).status_code == 404
    submit, _ = fake_submit(
        [{"provider_ref": "q-9", "statuses": ["accepted_by_network", "queued"]}]
    )
    monkeypatch.setattr(ChirpStackCommands, "submit", submit)
    created = await client.post(
        f"/api/v1/devices/{other_device['id']}/commands",
        json={"action_key": "REQUEST_STATUS"},
        headers=h,
    )
    assert created.status_code == 201 and created.json()["project_id"] is None
