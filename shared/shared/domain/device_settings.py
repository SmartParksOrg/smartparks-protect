"""The settings Protect knows per device (decisions D228 to D231): the upsert every source
goes through, so a newer observation replaces an older one and a frame confirms a command."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.domain.reporting import driver_catalog
from shared.domain.reporting_rules import decode_tlv_values
from shared.models import DeviceSetting


async def record_setting(
    session: AsyncSession,
    device_id: uuid.UUID,
    key: str,
    value: Any,
    *,
    source: str,
    observed_at: datetime,
    setting_id: int | None = None,
    raw_hex: str | None = None,
    status: str = "observed",
    source_event_id: int | None = None,
    command_id: uuid.UUID | None = None,
    set_by_user_id: uuid.UUID | None = None,
) -> DeviceSetting | None:
    """Keep the value when it is newer than the one known, or when it confirms a command that
    was only sent; returns the row when it changed, None when the known value stands."""
    row = await session.get(DeviceSetting, (device_id, key))
    if row is None:
        row = DeviceSetting(
            device_id=device_id, key=key, value=value, source=source, observed_at=observed_at
        )
        session.add(row)
    else:
        confirms = row.status == "sent" and status == "observed"
        if row.observed_at > observed_at and not confirms:
            return None
        row.value = value
        row.source = source
        row.observed_at = observed_at
    row.setting_id = setting_id if setting_id is not None else row.setting_id
    row.raw_hex = raw_hex
    row.status = status
    row.source_event_id = source_event_id
    row.command_id = command_id
    row.set_by_user_id = set_by_user_id
    return row


async def record_settings_frame(
    session: AsyncSession,
    device_id: uuid.UUID,
    driver_key: str,
    state: dict[str, Any],
    *,
    source: str,
    observed_at: datetime,
    source_event_id: int | None,
) -> int:
    """A state record holding settings TLVs (`port_3_tlv`): every setting the catalogue names
    becomes a known value; returns how many changed."""
    catalog = driver_catalog(driver_key)
    if not catalog:
        return 0
    changed = 0
    for key, tlv in state.items():
        if not (key.startswith("port_") and key.endswith("_tlv") and isinstance(tlv, dict)):
            continue
        if key != "port_3_tlv":
            continue  # port 30 carries readable values, not settings
        for name, item in decode_tlv_values(tlv, catalog).items():
            row = await record_setting(
                session,
                device_id,
                name,
                item["value"],
                source=source,
                observed_at=observed_at,
                setting_id=item["id"],
                raw_hex=item["raw_hex"],
                source_event_id=source_event_id,
            )
            if row is not None:
                changed += 1
    return changed


async def known_settings(session: AsyncSession, device_id: uuid.UUID) -> dict[str, DeviceSetting]:
    rows = await session.scalars(select(DeviceSetting).where(DeviceSetting.device_id == device_id))
    return {row.key: row for row in rows}
