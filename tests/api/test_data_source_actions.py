"""Test connection and Sync devices on a data source: the platform's API called with the
stored credentials, its device list turned into identities to link."""

import pytest

from shared.connectivity.adapters import chirpstack
from tests.api.conftest import actor
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


async def test_connection_and_device_sync(client, db, monkeypatch):
    admin = await actor(client, db, superuser=True)
    source = (
        await client.post(
            "/api/v1/data-sources",
            json={
                "name": unique_name("cs"),
                "adapter_key": "chirpstack",
                "config": {"api_url": "grpcs://cs.example:443", "tenant_id": "t1"},
                "credentials": {"api_token": "k"},
            },
            headers=admin.headers,
        )
    ).json()
    base = f"/api/v1/data-sources/{source['id']}"

    async def ok(self):
        return {"ok": True, "tenant": "Smart Parks"}

    async def devices(self):
        return [
            {
                "external_id": "0016C001F01192A0",
                "identity_type": "dev_eui",
                "name": "SP051307",
                "attributes": {"application_id": "a1"},
            },
            {
                "external_id": "0016C001F01192A1",
                "identity_type": "dev_eui",
                "name": "SP051308",
                "attributes": {},
            },
        ]

    monkeypatch.setattr(chirpstack.ChirpStackManagement, "test_connection", ok)
    monkeypatch.setattr(chirpstack.ChirpStackManagement, "list_devices", devices)
    tested = (await client.post(f"{base}/test", headers=admin.headers)).json()
    assert tested["ok"] is True and tested["result"]["tenant"] == "Smart Parks"
    synced = (await client.post(f"{base}/sync-devices", headers=admin.headers)).json()
    assert synced == {"listed": 2, "created": 2, "updated": 0}
    again = (await client.post(f"{base}/sync-devices", headers=admin.headers)).json()
    assert again == {"listed": 2, "created": 0, "updated": 2}
    identities = (await client.get(f"{base}/identities", headers=admin.headers)).json()["items"]
    by_id = {i["external_id"]: i for i in identities}
    assert by_id["0016C001F01192A0"]["attributes"]["name"] == "SP051307"
    assert by_id["0016C001F01192A0"]["device_id"] is None  # to be linked from Needs attention

    async def refused(self):
        from shared.enums import ErrorCode
        from shared.trace import ApplicationError

        raise ApplicationError(
            code=ErrorCode.CONNECTIVITY_AUTH_FAILED,
            message="ChirpStack refused the API key",
            component="adapter.chirpstack",
        )

    monkeypatch.setattr(chirpstack.ChirpStackManagement, "test_connection", refused)
    failed = (await client.post(f"{base}/test", headers=admin.headers)).json()
    assert failed["ok"] is False and "refused" in failed["detail"]

    push_only = (
        await client.post(
            "/api/v1/data-sources",
            json={"name": unique_name("hook"), "adapter_key": "generic_http"},
            headers=admin.headers,
        )
    ).json()
    webhook = (
        await client.post(f"/api/v1/data-sources/{push_only['id']}/test", headers=admin.headers)
    ).json()
    assert webhook["ok"] is True and "webhook" in webhook["detail"]
    assert (
        await client.post(
            f"/api/v1/data-sources/{push_only['id']}/sync-devices", headers=admin.headers
        )
    ).status_code == 422
