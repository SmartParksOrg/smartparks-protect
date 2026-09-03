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

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.bus import RedisStreamsBus, Topic
from shared.config import get_settings
from shared.connectivity.base import AdapterCapabilities, DataSourceContext, InboundMessage
from shared.enums import ProcessingStatus, TraceClass
from shared.logger import get_logger
from shared.models import DataSource, ExternalIdentity, SourceEvent
from shared.secrets import decrypt_json
from shared.storage import put_object, sha256
from shared.timeutil import utc_now
from shared.trace import Tracer

log = get_logger("ingest")


def data_source_context(source: DataSource) -> DataSourceContext:
    credentials = decrypt_json(source.credentials_encrypted) if source.credentials_encrypted else {}
    return DataSourceContext(
        id=source.id,
        name=source.name,
        adapter_key=source.adapter_key,
        config=dict(source.config),
        credentials=credentials,
        capabilities=AdapterCapabilities.model_validate(source.capabilities),
    )


@dataclass(slots=True)
class StoredEvent:
    source_event: SourceEvent
    topic: str
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
    identity.last_seen_at = now
    identity.event_count = (identity.event_count or 0) + 1
    await session.flush()
    return identity


async def store_inbound(
    session: AsyncSession, source: DataSource, message: InboundMessage
) -> StoredEvent:
    now = utc_now()
    identity = await resolve_identity(session, source, message, now)
    device_id = identity.device_id if identity is not None else None
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
        else (ProcessingStatus.RECEIVED if device_id else ProcessingStatus.UNASSIGNED),
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

    tracer.trace.root_object_id = str(event.id)
    async with tracer.step(
        "ingest",
        "source event stored",
        output_ref=f"source_event:{event.id}",
        metadata={"inline": event.payload is not None, "bytes": len(raw)},
    ):
        pass
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


async def commit_and_publish(
    session: AsyncSession, bus: RedisStreamsBus, stored: list[StoredEvent]
) -> None:
    await session.commit()
    for item in stored:
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
