"""Settings files per device (decisions D426 to D429): the store every file goes through, and
what a file tells Protect about the device's settings."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime
from types import ModuleType
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.domain.device_settings import known_settings, record_setting
from shared.models import DeviceSettingsFile, ExternalIdentity

#: A device's list shows this many files, newest first.
FILES_LISTED = 200
#: A document larger than this is no settings file: the app writes about 5 kB.
MAX_DOCUMENT_BYTES = 64 * 1024
#: A whole read of a device holds at least this many settings; fewer is a read that stopped
#: half way and makes no snapshot (the oldest firmware the app knows, 4.4.2, has over 60).
MIN_SNAPSHOT_SETTINGS = 40


def settings_codec(driver_key: str) -> ModuleType | None:
    """The driver's settings file codec, for a driver that has one."""
    from shared.device_drivers.registry import DRIVERS

    driver = DRIVERS.get(driver_key)
    codec = getattr(driver, "settings_file", None)
    return codec if isinstance(codec, ModuleType) else None


def document_sha256(document: dict[str, Any]) -> str:
    text = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_name(name: str, at: datetime) -> str:
    """The app's own file name: the device's name and the moment, here in UTC."""
    safe = re.sub(r"[^A-Za-z0-9_-]+", "_", name.strip()).strip("_") or "device"
    return f"{safe}_{at.strftime('%Y%m%d_%H%M%S')}.json"


async def device_euis(session: AsyncSession, device_id: uuid.UUID) -> set[str]:
    """The DevEUIs the device is known by, lower-case."""
    rows = await session.scalars(
        select(ExternalIdentity.external_id).where(ExternalIdentity.device_id == device_id)
    )
    return {row.lower() for row in rows if re.fullmatch(r"[0-9A-Fa-f]{16}", row)}


async def newest_file(session: AsyncSession, device_id: uuid.UUID) -> DeviceSettingsFile | None:
    row: DeviceSettingsFile | None = await session.scalar(
        select(DeviceSettingsFile)
        .where(DeviceSettingsFile.device_id == device_id)
        .order_by(DeviceSettingsFile.created_at.desc(), DeviceSettingsFile.id.desc())
        .limit(1)
    )
    return row


async def store_settings_file(
    session: AsyncSession,
    device_id: uuid.UUID,
    *,
    source: str,
    filename: str,
    document: dict[str, Any],
    has_credentials: bool,
    firmware: str | None,
    observed_at: datetime | None,
    user_id: uuid.UUID | None,
) -> tuple[DeviceSettingsFile, bool]:
    """Keep a file; returns the row and whether it is new. A snapshot equal to the device's
    newest file adds nothing (D428), and neither does an upload the device holds already."""
    sha = document_sha256(document)
    if source == "ble":
        newest = await newest_file(session, device_id)
        existing = newest if newest is not None and newest.sha256 == sha else None
    else:
        existing = await session.scalar(
            select(DeviceSettingsFile)
            .where(DeviceSettingsFile.device_id == device_id, DeviceSettingsFile.sha256 == sha)
            .order_by(DeviceSettingsFile.created_at.desc())
            .limit(1)
        )
    if existing is not None:
        return existing, False
    row = DeviceSettingsFile(
        device_id=device_id,
        source=source,
        filename=filename[:255],
        document=document,
        sha256=sha,
        settings_count=len(document),
        has_credentials=has_credentials,
        firmware_version=firmware,
        observed_at=observed_at,
        uploaded_by_user_id=user_id,
    )
    session.add(row)
    await session.flush()
    return row, True


async def file_count(session: AsyncSession, device_id: uuid.UUID) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(DeviceSettingsFile)
            .where(DeviceSettingsFile.device_id == device_id)
        )
        or 0
    )


async def record_file_settings(
    session: AsyncSession,
    device_id: uuid.UUID,
    settings: list[Any],
    *,
    source: str,
    observed_at: datetime | None,
    recorded_at: datetime,
    user_id: uuid.UUID | None,
) -> int:
    """What a file or a read says becomes known. With a time the newest observation wins, as
    for every source. A file without one (the app writes no date into it) only fills in what
    Protect does not know yet, since nothing says it is newer than a frame the device sent.
    Returns how many settings changed."""
    known = await known_settings(session, device_id) if observed_at is None else {}
    changed = 0
    for item in settings:
        if observed_at is None and item.key in known:
            continue
        row = await record_setting(
            session,
            device_id,
            item.key,
            item.value,
            source=source,
            observed_at=observed_at or recorded_at,
            setting_id=item.setting_id,
            raw_hex=item.raw_hex,
            set_by_user_id=user_id,
        )
        if row is not None:
            changed += 1
    return changed
