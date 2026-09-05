"""A source is its channels: the form's guidance comes from the registry, the status from
what arrived, the connector state and the last API answer."""

import pytest

from shared.connectivity.registry import ADAPTERS, channels_of, describe_adapter
from shared.connectivity.state import report_api_test, report_connector
from tests.api.test_ingest_and_attention import _setup
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio


def test_every_adapter_has_channels_with_needs():
    for key, adapter in ADAPTERS.items():
        channels = channels_of(adapter)
        if getattr(adapter, "builtin", False):
            continue
        assert channels, key
        for channel in channels:
            assert {
                "key",
                "label",
                "direction",
                "purpose",
                "config_keys",
                "credential_keys",
            } <= set(channel), (key, channel)
            assert channel["direction"] in ("in", "out")
            # Every key a channel names must exist in the adapter's schemas, so the form can
            # render a field for it (required ones from `config_keys`, the rest optional).
            properties = set((getattr(adapter, "config_schema", None) or {}).get("properties", {}))
            credentials = set(getattr(adapter, "credentials_schema", None) or {})
            for name in [*channel["config_keys"], *channel.get("optional_keys", [])]:
                assert name in properties, (key, channel["key"], name)
            for name in [*channel["credential_keys"], *channel.get("optional_credential_keys", [])]:
                assert name in credentials, (key, channel["key"], name)
        assert describe_adapter(adapter)["channels"] == channels
    chirpstack = {c["key"]: c for c in channels_of(ADAPTERS["chirpstack"])}
    assert set(chirpstack) == {"http", "mqtt", "api"}
    assert chirpstack["mqtt"]["config_keys"] == ["mqtt_host"]
    assert (
        chirpstack["api"]["credential_keys"] == ["api_token"]
        and "downlink" in chirpstack["api"]["capabilities"]
    )


async def test_status_per_channel(client, db):
    admin, _project, _type, source, _device, external_id = await _setup(client, db)
    base = f"/api/v1/data-sources/{source['id']}"
    before = (await client.get(f"{base}/status", headers=admin.headers)).json()
    http = next(c for c in before["channels"] if c["key"] == "http")
    assert http["configured"] and http["state"] == "waiting" and http["count_24h"] == 0
    auth = {"Authorization": f"Bearer {source['webhook_token']}"}
    body = {
        "device_id": external_id,
        "time": "2026-03-21T10:00:00+00:00",
        "lat": -24.8,
        "lon": 31.4,
    }
    assert (
        await client.post(f"/api/v1/ingest/http/{source['id']}", json=body, headers=auth)
    ).status_code == 202
    after = (await client.get(f"{base}/status", headers=admin.headers)).json()
    http = next(c for c in after["channels"] if c["key"] == "http")
    assert http["state"] == "ok" and http["count_24h"] == 1 and http["last_at"]

    chirpstack = (
        await client.post(
            "/api/v1/data-sources",
            json={
                "name": unique_name("cs"),
                "adapter_key": "chirpstack",
                "config": {"web_url": "https://cs.example", "tenant_id": "t1"},
            },
            headers=admin.headers,
        )
    ).json()
    status = (
        await client.get(f"/api/v1/data-sources/{chirpstack['id']}/status", headers=admin.headers)
    ).json()
    by_key = {c["key"]: c for c in status["channels"]}
    assert by_key["http"]["configured"] and by_key["http"]["state"] == "waiting"
    assert (
        not by_key["mqtt"]["configured"]
        and by_key["mqtt"]["missing"] == ["mqtt_host"]
        and by_key["mqtt"]["state"] == "off"
    )
    assert not by_key["api"]["configured"] and by_key["api"]["missing"] == ["api_url", "api_token"]
    assert (
        "downlink" in status["limited_capabilities"]
        and status["effective_capabilities"]["downlink"] is False
    )
    assert status["effective_capabilities"]["uplink"] is True

    configured = await client.patch(
        f"/api/v1/data-sources/{chirpstack['id']}",
        json={
            "config": {
                "web_url": "https://cs.example",
                "tenant_id": "t1",
                "mqtt_host": "mq.example",
                "api_url": "https://cs.example/rest",
            },
            "credentials": {"api_token": "k"},
        },
        headers=admin.headers,
    )
    assert configured.status_code == 200, configured.text
    await report_connector(chirpstack["id"], "reconnecting", "mq.example: refused")
    await report_api_test(chirpstack["id"], False, "ChirpStack refused the API key")
    status = (
        await client.get(f"/api/v1/data-sources/{chirpstack['id']}/status", headers=admin.headers)
    ).json()
    by_key = {c["key"]: c for c in status["channels"]}
    assert (
        by_key["mqtt"]["configured"]
        and by_key["mqtt"]["state"] == "reconnecting"
        and "refused" in by_key["mqtt"]["detail"]
    )
    assert (
        by_key["api"]["configured"]
        and by_key["api"]["state"] == "error"
        and by_key["api"]["last_at"]
    )
    assert (
        status["limited_capabilities"] == []
        and status["effective_capabilities"]["downlink"] is True
    )
    await report_connector(chirpstack["id"], "connected", "subscribed")
    await report_api_test(chirpstack["id"], True, "The platform answered.")
    status = (
        await client.get(f"/api/v1/data-sources/{chirpstack['id']}/status", headers=admin.headers)
    ).json()
    by_key = {c["key"]: c for c in status["channels"]}
    assert by_key["mqtt"]["state"] == "connected" and by_key["api"]["state"] == "ok"


async def test_channel_switches_are_enforced(client, db):
    admin, _project, _type, source, _device, external_id = await _setup(client, db)
    base = f"/api/v1/data-sources/{source['id']}"
    switched = await client.patch(base, json={"channels": {"http": False}}, headers=admin.headers)
    assert switched.status_code == 200 and switched.json()["channels"] == {"http": False}
    auth = {"Authorization": f"Bearer {source['webhook_token']}"}
    body = {
        "device_id": external_id,
        "time": "2026-03-21T10:00:00+00:00",
        "lat": -24.8,
        "lon": 31.4,
    }
    refused = await client.post(f"/api/v1/ingest/http/{source['id']}", json=body, headers=auth)
    assert refused.status_code == 409 and "off" in refused.json()["detail"]
    status = (await client.get(f"{base}/status", headers=admin.headers)).json()
    http = next(c for c in status["channels"] if c["key"] == "http")
    assert http["enabled"] is False and http["state"] == "disabled"
    back = await client.patch(base, json={"channels": {}}, headers=admin.headers)
    assert back.status_code == 200
    assert (
        await client.post(f"/api/v1/ingest/http/{source['id']}", json=body, headers=auth)
    ).status_code == 202

    chirpstack = (
        await client.post(
            "/api/v1/data-sources",
            json={
                "name": unique_name("cs"),
                "adapter_key": "chirpstack",
                "config": {"api_url": "grpcs://cs.example", "tenant_id": "t1"},
                "credentials": {"api_token": "k"},
                "channels": {"api": False},
            },
            headers=admin.headers,
        )
    ).json()
    test = (
        await client.post(f"/api/v1/data-sources/{chirpstack['id']}/test", headers=admin.headers)
    ).json()
    assert test["ok"] is False and "off" in test["detail"]
    assert (
        await client.post(
            f"/api/v1/data-sources/{chirpstack['id']}/sync-devices", headers=admin.headers
        )
    ).status_code == 409
    status = (
        await client.get(f"/api/v1/data-sources/{chirpstack['id']}/status", headers=admin.headers)
    ).json()
    assert next(c for c in status["channels"] if c["key"] == "api")["state"] == "disabled"
    assert (
        status["effective_capabilities"]["downlink"] is False
        and "downlink" in status["limited_capabilities"]
    )
