"""Gateway registry rows from receptions and gateway events; decoded events with a point."""

import pytest
from geoalchemy2.shape import to_shape
from sqlalchemy import select

from protect_decoder.pipeline import process_source_event
from shared.connectivity.base import GatewayReceptionData, GatewayUpdate, InboundMessage
from shared.enums import AcquisitionChannel, IngestionMethod, ProcessingStatus
from shared.ingest import commit_and_publish, store_inbound
from shared.models import Event, Gateway, SourceEvent
from tests.decoder.conftest import inbound
from tests.decoder.test_pipeline import bus  # noqa: F401

pytestmark = pytest.mark.asyncio


async def test_receptions_register_gateways(db, bus, world):  # noqa: F811
    message = inbound(
        world.external_id,
        {"time": "2026-03-10T10:00:00+00:00", "lat": -24.9, "lon": 31.5},
        gateway_receptions=[
            GatewayReceptionData(
                gateway_id="AA555A0000000101",
                rssi=-101,
                snr=7.5,
                attributes={"location": {"latitude": -24.95, "longitude": 31.55, "altitude": 300}},
            ),
            GatewayReceptionData(gateway_id="aa555a0000000102", rssi=-110, snr=2.0),
        ],
    )
    stored = await store_inbound(db, world.source, message)
    await commit_and_publish(db, bus, [stored])
    gateways = {
        g.external_id: g
        for g in (
            await db.scalars(select(Gateway).where(Gateway.data_source_id == world.source.id))
        ).all()
    }
    assert set(gateways) == {"aa555a0000000101", "aa555a0000000102"}
    located = gateways["aa555a0000000101"]
    assert located.status == "online" and located.last_seen_at is not None
    point = to_shape(located.geom)
    assert (round(point.y, 2), round(point.x, 2)) == (-24.95, 31.55) and located.altitude_m == 300
    assert gateways["aa555a0000000102"].geom is None

    # a gateway event: stats and state, stored raw without a device and without a bus message
    stats = InboundMessage(
        external_id=None,
        event_type="gateway_stats",
        payload={"gatewayId": "aa555a0000000102", "rxPacketsReceived": 12},
        acquisition_channel=AcquisitionChannel.LORAWAN,
        ingestion_method=IngestionMethod.MQTT,
        gateway=GatewayUpdate(
            gateway_id="AA555A0000000102",
            name="North ridge",
            stats={"rx_packets": 12, "tx_packets": 3},
            latitude=-24.8,
            longitude=31.4,
        ),
    )
    stored = await store_inbound(db, world.source, stats)
    assert stored.topic is None
    await commit_and_publish(db, bus, [stored])
    row = await db.get(SourceEvent, (stored.source_event.id, stored.source_event.ingested_at))
    assert row is not None and row.processing_status == ProcessingStatus.PROCESSED
    assert row.device_id is None
    updated = gateways["aa555a0000000102"]
    await db.refresh(updated)
    assert updated.name == "North ridge" and updated.stats == {"rx_packets": 12, "tx_packets": 3}
    assert updated.last_stats_at is not None and updated.geom is not None
    offline = InboundMessage(
        external_id=None,
        event_type="gateway_conn",
        payload={"gatewayId": "aa555a0000000102", "state": "OFFLINE"},
        acquisition_channel=AcquisitionChannel.LORAWAN,
        ingestion_method=IngestionMethod.MQTT,
        gateway=GatewayUpdate(gateway_id="aa555a0000000102", status="offline"),
    )
    stored = await store_inbound(db, world.source, offline)
    await commit_and_publish(db, bus, [stored])
    await db.refresh(updated)
    assert updated.status == "offline"


async def test_decoded_event_keeps_its_point(db, bus, world):  # noqa: F811
    payload = {
        "time": "2026-03-10T11:00:00+00:00",
        "events": [
            {
                "type": "SPECIES_DETECTION",
                "title": "Wolf at Waterhole",
                "description": "One wolf, 94 %",
                "lat": -24.88,
                "lon": 31.49,
                "context": {"species": ["wolf"]},
            }
        ],
    }
    stored = await store_inbound(db, world.source, inbound(world.external_id, payload))
    await commit_and_publish(db, bus, [stored])
    event = stored.source_event
    outcome = await process_source_event(db, event.id, event.ingested_at)
    await db.commit()
    assert outcome.created["events"] == 1
    row = await db.scalar(select(Event).where(Event.source_event_id == event.id))
    assert row is not None and row.description == "One wolf, 94 %"
    point = to_shape(row.geom)
    assert (point.y, point.x) == (-24.88, 31.49)
