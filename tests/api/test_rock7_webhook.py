"""Rock7 posts its delivery as a form (decision D156): the ingest route reads form bodies and
the adapter turns the fields into an Iridium source event."""

import pytest

from tests.api.conftest import actor, unique_name

pytestmark = pytest.mark.asyncio


async def test_a_form_encoded_delivery_is_accepted(client, db):
    admin = await actor(client, db, superuser=True)
    source = (
        await client.post(
            "/api/v1/data-sources",
            json={"name": unique_name("Rock7"), "adapter_key": "rock7"},
            headers=admin.headers,
        )
    ).json()
    url = f"/api/v1/ingest/http/{source['id']}"
    query = {"token": source["webhook_token"]}
    fields = {
        "imei": "300234010753370",
        "serial": "12345",
        "momsn": "12345",
        "transmit_time": "21-10-31 10:41:50",
        "iridium_latitude": "52.3867",
        "iridium_longitude": "0.2938",
        "iridium_cep": "8",
        "data": "48656c6c6f20576f726c6420526f636b424c4f434b",
    }
    accepted = await client.post(url, params=query, data=fields)
    assert accepted.status_code == 202, accepted.text
    # the JSON delivery format of the same message is accepted as well
    assert (await client.post(url, params=query, json=fields)).status_code == 202
    # without the token in the URL nothing is accepted
    assert (await client.post(url, data=fields)).status_code == 401
    # a form without an IMEI is a decode failure, not a server error
    assert (await client.post(url, params=query, data={"momsn": "1"})).status_code in (400, 422)
