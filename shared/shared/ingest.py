"""Inbound path shared by the API (webhooks) and the ingest service (connectors).

`store_inbound` resolves the external identity, stores the immutable source event (payload inline
or in MinIO above the size limit, decision D32), starts the processing trace and prepares the bus
message. The caller commits and then publishes with `commit_and_publish`, so a consumer never
sees a message whose row is not committed yet.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from geoalchemy2.shape import from_shape
from shapely.geometry import Point
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from shared.bus import RedisStreamsBus, Topic
from shared.config import get_settings
from shared.connectivity.base import (
    AdapterCapabilities,
    DataSourceContext,
    GatewayReceptionData,
    GatewayUpdate,
    InboundMessage,
)
from shared.database import session_scope
from shared.enums import ConnectivityStatus, ProcessingStatus, TraceClass
from shared.logger import get_logger
from shared.models import (
    DataSource,
    DataSourceCursor,
    ExternalIdentity,
    Gateway,
    GatewayReception,
    SourceEvent,
)
from shared.secrets import decrypt_json
from shared.storage import put_object, sha256
from shared.timeutil import utc_now
from shared.trace import Tracer

log = get_logger("ingest")


class DatabaseCursorStore:
    """Polling cursor of one data source in `data_source_cursors`, its own short transaction so
    a connector can save between pages without touching the ingest session."""

    def __init__(self, data_source_id: uuid.UUID) -> None:
        self.data_source_id = data_source_id

    async def load(self) -> dict[str, Any]:
        async with session_scope() as session:
            row = await session.get(DataSourceCursor, self.data_source_id)
            return dict(row.state) if row is not None else {}

    async def save(self, state: dict[str, Any]) -> None:
        async with session_scope() as session:
            await session.execute(
                insert(DataSourceCursor)
                .values(data_source_id=self.data_source_id, state=state, updated_at=utc_now())
                .on_conflict_do_update(
                    index_elements=[DataSourceCursor.data_source_id],
                    set_={"state": state, "updated_at": utc_now()},
                )
            )
            await session.commit()


def data_source_context(source: DataSource) -> DataSourceContext:
    credentials = decrypt_json(source.credentials_encrypted) if source.credentials_encrypted else {}
    return DataSourceContext(
        id=source.id,
        name=source.name,
        adapter_key=source.adapter_key,
        config=dict(source.config),
        credentials=credentials,
        capabilities=AdapterCapabilities.model_validate(source.capabilities),
        cursors=DatabaseCursorStore(source.id),
    )


def _status(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).lower()
    if text in ("online", "offline"):
        return text
    return ConnectivityStatus.UNKNOWN


async def upsert_gateways(
    session: AsyncSession,
    data_source_id: uuid.UUID,
    receptions: list[GatewayReceptionData],
    now: datetime,
) -> None:
    """Every gateway that received something exists in the registry (architecture 20, D66).
    A reception's `location` attribute (ChirpStack shape) fills the position once."""
    for reception in receptions:
        if not reception.gateway_id:
            continue
        location = reception.attributes.get("location") if reception.attributes else None
        update = GatewayUpdate(gateway_id=reception.gateway_id, seen_at=now)
        if isinstance(location, dict):
            update.latitude = location.get("latitude")
            update.longitude = location.get("longitude")
            update.altitude_m = location.get("altitude")
        await apply_gateway_update(session, data_source_id, update, now, from_reception=True)


async def apply_gateway_update(
    session: AsyncSession,
    data_source_id: uuid.UUID,
    update: GatewayUpdate,
    now: datetime,
    *,
    from_reception: bool = False,
) -> Gateway:
    gateway_id = update.gateway_id.lower()
    gateway = await session.scalar(
        select(Gateway).where(
            Gateway.data_source_id == data_source_id, Gateway.external_id == gateway_id
        )
    )
    seen = update.seen_at or now
    if gateway is None:
        gateway = Gateway(
            data_source_id=data_source_id,
            external_id=gateway_id,
            first_seen_at=seen,
            status=ConnectivityStatus.UNKNOWN,
        )
        session.add(gateway)
    if gateway.last_seen_at is None or seen > gateway.last_seen_at:
        gateway.last_seen_at = seen
    if from_reception:
        gateway.status = ConnectivityStatus.ONLINE
    elif update.status is not None:
        gateway.status = _status(update.status) or ConnectivityStatus.UNKNOWN
    if (update.name and not gateway.name) or (update.name and not from_reception):
        gateway.name = update.name
    if update.latitude is not None and update.longitude is not None:
        latitude: float | None
        longitude: float | None
        try:
            latitude, longitude = float(update.latitude), float(update.longitude)
        except (TypeError, ValueError):
            latitude = longitude = None
        if (
            latitude is not None
            and longitude is not None
            and -90 <= latitude <= 90
            and -180 <= longitude <= 180
            and (latitude, longitude) != (0.0, 0.0)
        ):
            gateway.geom = from_shape(Point(longitude, latitude), srid=4326)
            if update.altitude_m is not None:
                gateway.altitude_m = float(update.altitude_m)
    if update.stats:
        gateway.stats = {**gateway.stats, **update.stats}
        gateway.last_stats_at = seen
    if update.attributes:
        gateway.attributes = {**gateway.attributes, **update.attributes}
    await session.flush()
    return gateway


@dataclass(slots=True)
class StoredEvent:
    source_event: SourceEvent
    topic: str | None
    payload: dict[str, Any]
    trace_id: uuid.UUID
    identity: ExternalIdentity | None


async def resolve_identity(
    session: AsyncSession, source: DataSource, message: InboundMessage, now: datetime
) -> ExternalIdentity | None:
    if message.external_id is None:
        return None
    identity = await session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.data_source_id == source.id,
            ExternalIdentity.external_id == message.external_id,
        )
    )
    if identity is None:
        identity = ExternalIdentity(
            data_source_id=source.id,
            external_id=message.external_id,
            identity_type=message.identity_type,
            first_seen_at=now,
        )
        session.add(identity)
    if identity.device_id is None and message.device_id is not None:
        identity.device_id = message.device_id  # the caller knows the device (browser, upload)
    identity.last_seen_at = now
    identity.event_count = (identity.event_count or 0) + 1
    if message.identity_attributes:
        merged = {**(identity.attributes or {}), **message.identity_attributes}
        if merged != (identity.attributes or {}):
            identity.attributes = merged
    await session.flush()
    return identity


async def store_inbound(
    session: AsyncSession, source: DataSource, message: InboundMessage
) -> StoredEvent:
    now = utc_now()
    identity = await resolve_identity(session, source, message, now)
    device_id = (identity.device_id if identity is not None else None) or message.device_id
    ignored = identity.ignored if identity is not None else False

    tracer = Tracer(
        session,
        root_object_type="source_event",
        root_object_id="pending",
        trace_class=TraceClass.ROUTINE,
        compact=True,
        device_id=device_id,
        data_source_id=source.id,
    )
    await tracer.start()

    raw = json.dumps(message.payload, default=str).encode()
    event = SourceEvent(
        ingested_at=now,
        data_source_id=source.id,
        external_id=message.external_id,
        external_identity_id=identity.id if identity is not None else None,
        device_id=device_id,
        event_type=message.event_type,
        acquisition_channel=message.acquisition_channel,
        ingestion_method=message.ingestion_method,
        processing_status=ProcessingStatus.IGNORED
        if ignored
        else (
            ProcessingStatus.RECEIVED
            if device_id
            else (
                ProcessingStatus.PROCESSED
                if message.gateway is not None
                else ProcessingStatus.UNASSIGNED
            )
        ),
        provider_metadata=message.provider_metadata,
        network_received_at=message.network_received_at,
        satellite_delivered_at=message.satellite_delivered_at,
        ble_synced_at=message.ble_synced_at,
        file_uploaded_at=message.file_uploaded_at,
        trace_id=tracer.trace_id,
        payload_size=len(raw),
        payload_sha256=sha256(raw),
    )
    settings = get_settings()
    if len(raw) <= settings.payload_inline_max_bytes:
        event.payload = message.payload
    else:
        key = f"source-events/{source.id}/{now:%Y/%m}/{uuid.uuid4()}.json"
        await put_object(settings.minio_bucket_uploads, key, raw, "application/json")
        event.payload_object_key = key
    session.add(event)
    await session.flush()

    for reception in message.gateway_receptions:
        session.add(
            GatewayReception(
                time=message.network_received_at or now,
                data_source_id=source.id,
                device_id=device_id,
                source_event_id=event.id,
                source_event_ingested_at=now,
                gateway_id=reception.gateway_id,
                rssi=reception.rssi,
                snr=reception.snr,
                frequency_hz=reception.frequency_hz,
                channel=reception.channel,
                attributes=reception.attributes,
            )
        )

    if message.gateway_receptions:
        await upsert_gateways(session, source.id, message.gateway_receptions, now)

    tracer.trace.root_object_id = str(event.id)
    async with tracer.step(
        "ingest",
        "source event stored",
        output_ref=f"source_event:{event.id}",
        metadata={"inline": event.payload is not None, "bytes": len(raw)},
    ):
        pass
    if message.gateway is not None:
        async with tracer.step(
            "ingest", "gateway updated", input_ref=f"gateway:{message.gateway.gateway_id}"
        ) as step:
            gateway = await apply_gateway_update(session, source.id, message.gateway, now)
            step.output_ref = f"gateway:{gateway.id}"
        await tracer.finish()
        return StoredEvent(
            source_event=event, topic=None, payload={}, trace_id=tracer.trace_id, identity=None
        )
    async with tracer.step(
        "ingest", "identity resolved", input_ref=f"external_id:{message.external_id}"
    ) as step:
        if identity is None:
            step.skip("message carries no external id")
        elif ignored:
            step.skip("identity is ignored")
        elif device_id is None:
            step.skip("unknown identity, kept for Needs Attention")
        else:
            step.output_ref = f"device:{device_id}"

    if device_id is not None and not ignored:
        topic, payload = (
            Topic.SOURCE_EVENT_RECEIVED,
            {
                "source_event_id": event.id,
                "ingested_at": now.isoformat(),
                "data_source_id": str(source.id),
                "device_id": str(device_id),
            },
        )
    else:
        await tracer.finish()
        topic, payload = (
            Topic.NEEDS_ATTENTION_CREATED,
            {
                "kind": "unknown_identity" if not ignored else "ignored_identity",
                "source_event_id": event.id,
                "ingested_at": now.isoformat(),
                "data_source_id": str(source.id),
                "external_identity_id": str(identity.id) if identity is not None else None,
                "external_id": message.external_id,
            },
        )
    return StoredEvent(
        source_event=event,
        topic=topic,
        payload=payload,
        trace_id=tracer.trace_id,
        identity=identity,
    )


async def builtin_source(session: AsyncSession, adapter_key: str) -> DataSource:
    """The built-in data source of a channel (`webble`, `log_file`), created by migration 0011
    and recreated here if an installation lost it."""
    from shared.connectivity.adapters import log_file, webble

    known = {webble.WebBleAdapter.key: webble, log_file.LogFileAdapter.key: log_file}
    module = known[adapter_key]
    source = await session.get(DataSource, module.SOURCE_ID)
    if source is None:
        source = await session.scalar(
            select(DataSource).where(DataSource.adapter_key == adapter_key)
        )
    if source is None:
        source = DataSource(
            id=module.SOURCE_ID,
            name=module.SOURCE_NAME,
            adapter_key=adapter_key,
            enabled=True,
            capabilities={"uplink": True, "downlink": adapter_key == webble.WebBleAdapter.key},
        )
        session.add(source)
        await session.flush()
    return source


async def ensure_channel_identity(
    session: AsyncSession, source: DataSource, device_id: uuid.UUID
) -> ExternalIdentity:
    """The device's identity on a built-in channel source: its own id, so a browser sync or a
    file upload is a delivery like any other and the route selection sees the channel."""
    identity = await session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.data_source_id == source.id,
            ExternalIdentity.external_id == str(device_id),
        )
    )
    if identity is None:
        identity = ExternalIdentity(
            data_source_id=source.id,
            device_id=device_id,
            external_id=str(device_id),
            identity_type="device_id",
            first_seen_at=utc_now(),
        )
        session.add(identity)
        await session.flush()
    elif identity.device_id is None:
        identity.device_id = device_id
    return identity


async def commit_and_publish(
    session: AsyncSession, bus: RedisStreamsBus, stored: list[StoredEvent]
) -> None:
    await session.commit()
    for item in stored:
        if item.topic is not None:
            await bus.publish(item.topic, item.payload, trace_id=str(item.trace_id))


async def republish_source_event(bus: RedisStreamsBus, event: SourceEvent) -> str:
    """Put a stored source event back on the bus, for reprocessing after a device was linked."""
    return await bus.publish(
        Topic.SOURCE_EVENT_RECEIVED,
        {
            "source_event_id": event.id,
            "ingested_at": event.ingested_at.isoformat(),
            "data_source_id": str(event.data_source_id),
            "device_id": str(event.device_id),
            "reprocess": True,
        },
        trace_id=str(event.trace_id) if event.trace_id else None,
    )
