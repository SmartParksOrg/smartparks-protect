"""A ThingPark push authenticates itself: the Token in its URL is verified with the AS key
stored on the source (decision D95); the source's bearer token stays the alternative."""

import json
from pathlib import Path

import pytest

from tests.api.conftest import actor
from tests.conftest import unique_name

pytestmark = pytest.mark.asyncio

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "payloads" / "kpn_thingpark"


async def _kpn_source(client, headers, credentials):
    response = await client.post(
        "/api/v1/data-sources",
        json={
            "name": unique_name("KPN"),
            "adapter_key": "kpn_thingpark",
            "credentials": credentials,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_thingpark_token_authenticates_the_push(client, db):
    admin = await actor(client, db, superuser=True)
    fixture = json.loads((FIXTURES / "kpn_uplink_hookbin_2016.json").read_text())
    source = await _kpn_source(client, admin.headers, {"as_key": fixture["as_key"]})
    url = f"/api/v1/ingest/http/{source['id']}"
    query, body = fixture["query"], fixture["body"]

    # no header at all, only ThingPark's own query: accepted (the `+02:00` survives)
    accepted = await client.post(url, params=query, json=body)
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["accepted"] == 1

    # the same push with the query as ThingPark writes it in the URL, `+` unencoded
    raw = "&".join(f"{k}={v}" for k, v in query.items())
    assert (await client.post(f"{url}?{raw}", json=body)).status_code == 202

    # a wrong token, a changed body, or a different time: refused
    assert (
        await client.post(url, params={**query, "Token": "0" * 64}, json=body)
    ).status_code == 401
    changed = json.loads(json.dumps(body))
    changed["DevEUI_uplink"]["payload_hex"] = "00"
    assert (await client.post(url, params=query, json=changed)).status_code == 401
    assert (await client.post(url, json=body)).status_code == 401

    # the bearer token still works without any query
    bearer = {"Authorization": f"Bearer {source['webhook_token']}"}
    assert (await client.post(url, json=body, headers=bearer)).status_code == 202

    # a source without the AS key cannot verify and falls back to the bearer only
    no_key = await _kpn_source(client, admin.headers, {})
    assert (
        await client.post(f"/api/v1/ingest/http/{no_key['id']}", params=query, json=body)
    ).status_code == 401
