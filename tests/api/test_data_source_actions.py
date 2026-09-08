"""Test connection and Sync devices on a data source: the platform's API called with the
stored credentials, its device list turned into identities to link."""

import uuid

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


async def test_connect_applications_needs_the_token_copy_and_reports_per_application(
    client, db, monkeypatch
):
    """Decision D125: the action writes the webhook with its token to every application through
    the connector; a source without the encrypted copy is told to rotate the token first."""
    from sqlalchemy import select

    from shared.models import AuditLog, DataSource
    from shared.secrets import decrypt_json, encrypt_json

    admin = await actor(client, db, superuser=True)
    created = await client.post(
        "/api/v1/data-sources",
        json={
            "name": unique_name("ChirpStack"),
            "adapter_key": "chirpstack",
            "config": {"api_url": "grpc://cs:8080", "tenant_id": "t1"},
            "credentials": {"api_token": "key"},
        },
        headers=admin.headers,
    )
    assert created.status_code == 201, created.text
    source = created.json()
    token = source["webhook_token"]
    assert token and source["webhook_url"].endswith(f"?token={token}")
    base = f"/api/v1/data-sources/{source['id']}"
    seen: dict[str, str] = {}

    async def connect(self, url):
        seen["url"] = url
        return [
            {"application_id": "a1", "name": "smartparks", "outcome": "connected", "urls": [url]},
            {"application_id": "a2", "name": "other", "outcome": "failed", "error": "refused"},
        ]

    async def status(self, base_url):
        seen["base"] = base_url
        return [{"application_id": "a1", "name": "smartparks", "state": "connected", "urls": []}]

    async def ok(self):
        return {"ok": True}

    monkeypatch.setattr(chirpstack.ChirpStackManagement, "connect_applications", connect)
    monkeypatch.setattr(chirpstack.ChirpStackManagement, "integration_status", status)
    monkeypatch.setattr(chirpstack.ChirpStackManagement, "test_connection", ok)
    result = await client.post(f"{base}/connect-applications", headers=admin.headers)
    assert result.status_code == 200, result.text
    body = result.json()
    assert (body["connected"], body["failed"], body["already"]) == (1, 1, 0)
    assert seen["url"].endswith(f"/api/v1/ingest/http/{source['id']}?token={token}")
    assert body["applications"][1]["error"] == "refused"
    audit = await db.scalar(
        select(AuditLog)
        .where(AuditLog.action == "data_source.applications_connected")
        .order_by(AuditLog.id.desc())
    )
    assert audit is not None and audit.details["connected"] == 1

    tested = (await client.post(f"{base}/test", headers=admin.headers)).json()
    assert tested["result"]["connected"] == 1 and seen["base"].endswith(source["id"])

    # a rotation keeps the copy in step with the hash
    rotated = (await client.post(f"{base}/webhook-token", headers=admin.headers)).json()
    row = await db.get(DataSource, uuid.UUID(source["id"]))
    await db.refresh(row)
    assert decrypt_json(row.credentials_encrypted)["webhook_token"] == rotated["webhook_token"]

    # a source from before the copy: told to rotate once
    row.credentials_encrypted = encrypt_json({"api_token": "key"})
    await db.commit()
    refused = await client.post(f"{base}/connect-applications", headers=admin.headers)
    assert refused.status_code == 409 and "new token" in refused.text
