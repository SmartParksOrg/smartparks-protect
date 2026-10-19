"""Delete a device with all its data (Tim, 2026-10-19: a device added twice should go, data and
all, after a typed confirmation). The time series live in compressed hypertables, and a DELETE
over one must name the segment and a time window and never join, with 100,000 decompressed
tuples the most one transaction may touch (TimescaleDB, seen on dev 2026-09-24). So the rows go
per segment and per week, one transaction each; the device row goes last and cascades the small
tables. The log files' objects leave the bucket too."""

import contextlib
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from shared.config import get_settings
from shared.models import (
    Device,
    DeviceContact,
    DeviceLogFile,
    DeviceStateHistory,
    GatewayReception,
    Measurement,
    Position,
    SourceEvent,
)
from shared.storage import remove_object

WINDOW = timedelta(days=7)


async def _span(
    session: AsyncSession, table: Any, column: Any, *conditions: Any
) -> tuple[datetime, datetime] | None:
    row = (
        await session.execute(select(func.min(column), func.max(column)).where(*conditions))
    ).one()
    if row[0] is None or row[1] is None:
        return None
    return row[0], row[1]


def _windows(span: tuple[datetime, datetime]) -> list[tuple[datetime, datetime]]:
    start, end = span
    out: list[tuple[datetime, datetime]] = []
    cursor = start
    while cursor <= end:
        out.append((cursor, cursor + WINDOW))
        cursor += WINDOW
    return out


async def _delete_in_windows(
    session: AsyncSession, table: Any, column: Any, *conditions: Any
) -> int:
    """DELETE the rows the conditions name, a window of `column` at a time, each committed."""
    span = await _span(session, table, column, *conditions)
    if span is None:
        return 0
    deleted = 0
    for lower, upper in _windows(span):
        result = await session.execute(
            delete(table).where(*conditions, column >= lower, column < upper)
        )
        deleted += int(getattr(result, "rowcount", 0) or 0)
        await session.commit()
    return deleted


async def purge_device_data(session: AsyncSession, device: Device) -> dict[str, int]:
    """Every row of the device in the time series and the raw messages, then the device
    itself. Returns what went, by table."""
    counts: dict[str, int] = {}
    device_id = device.id

    counts["positions"] = await _delete_in_windows(
        session, Position, Position.time, Position.device_id == device_id
    )
    counts["measurements"] = await _delete_in_windows(
        session, Measurement, Measurement.time, Measurement.device_id == device_id
    )
    counts["states"] = await _delete_in_windows(
        session,
        DeviceStateHistory,
        DeviceStateHistory.time,
        DeviceStateHistory.device_id == device_id,
    )
    counts["contacts"] = await _delete_in_windows(
        session, DeviceContact, DeviceContact.time, DeviceContact.device_id == device_id
    )
    # the device as the one seen by another reader: the sighting stays, nameless
    span = await _span(
        session, DeviceContact, DeviceContact.time, DeviceContact.contact_device_id == device_id
    )
    if span is not None:
        for lower, upper in _windows(span):
            await session.execute(
                update(DeviceContact)
                .where(
                    DeviceContact.contact_device_id == device_id,
                    DeviceContact.time >= lower,
                    DeviceContact.time < upper,
                )
                .values(contact_device_id=None)
            )
            await session.commit()

    # receptions are segmented by gateway: per gateway, per week
    gateways = (
        await session.scalars(
            select(GatewayReception.gateway_id)
            .where(GatewayReception.device_id == device_id)
            .distinct()
        )
    ).all()
    counts["receptions"] = 0
    for gateway_id in gateways:
        counts["receptions"] += await _delete_in_windows(
            session,
            GatewayReception,
            GatewayReception.time,
            GatewayReception.gateway_id == gateway_id,
            GatewayReception.device_id == device_id,
        )

    # the raw messages are segmented by source: per source, per week, their deliveries first
    sources = (
        await session.scalars(
            select(SourceEvent.data_source_id).where(SourceEvent.device_id == device_id).distinct()
        )
    ).all()
    counts["messages"] = 0
    counts["deliveries"] = 0
    for source_id in sources:
        span = await _span(
            session,
            SourceEvent,
            SourceEvent.ingested_at,
            SourceEvent.data_source_id == source_id,
            SourceEvent.device_id == device_id,
        )
        if span is None:
            continue
        for lower, upper in _windows(span):
            gone = await session.execute(
                text(
                    "DELETE FROM source_deliveries d USING ("
                    "SELECT id, ingested_at FROM source_events WHERE data_source_id = :source "
                    "AND device_id = :device AND ingested_at >= :lower AND ingested_at < :upper"
                    ") e WHERE d.source_event_id = e.id "
                    "AND d.source_event_ingested_at = e.ingested_at"
                ),
                {"source": source_id, "device": device_id, "lower": lower, "upper": upper},
            )
            counts["deliveries"] += int(getattr(gone, "rowcount", 0) or 0)
            result = await session.execute(
                delete(SourceEvent).where(
                    SourceEvent.data_source_id == source_id,
                    SourceEvent.device_id == device_id,
                    SourceEvent.ingested_at >= lower,
                    SourceEvent.ingested_at < upper,
                )
            )
            counts["messages"] += int(getattr(result, "rowcount", 0) or 0)
            await session.commit()

    # the log files: their objects, then the rows (the device's deletion cascades them too)
    files = (
        await session.scalars(select(DeviceLogFile).where(DeviceLogFile.device_id == device_id))
    ).all()
    bucket = get_settings().minio_bucket_log_files
    for row in files:
        # a missing object is no reason to keep the row
        with contextlib.suppress(Exception):
            await remove_object(bucket, row.object_key)
    counts["log_files"] = len(files)
    return counts
