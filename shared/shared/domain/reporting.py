"""What a device is expected to report and how often (decisions D225 to D227): the declared
interval from the most trustworthy source Protect has, and the interval the data shows,
resolved into one expectation with its source named. Shared by the device performance module
and the device page's Reporting card, so both say the same thing."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.curation.effective import device_fix, effective_time, visible
from shared.domain.reporting_rules import (
    Expected,
    decode_tlv_settings,
    expected_intervals,
    merged_settings,
    resolve_expected,
)
from shared.enums import CommandStatus
from shared.models import (
    Command,
    CommandExecution,
    Device,
    DeviceStateHistory,
    DeviceType,
    Position,
)

#: The device attribute a person's override lives under: `{seconds, set_by, set_at}`.
OVERRIDE_ATTRIBUTE = "expected_fix_interval"
#: The command that sets the fix interval and the parameter it carries.
INTERVAL_COMMAND = "SET_GNSS_INTERVAL"
INTERVAL_PARAMETER = "interval_seconds"
ACKNOWLEDGED = (CommandStatus.ACKNOWLEDGED, CommandStatus.CONFIRMED_BY_DEVICE)
FRAMES_TO_READ = 20
#: The device page learns from this many days of fixes.
LEARN_DAYS = 30


def driver_catalog(driver_key: str) -> list[dict[str, Any]]:
    """The driver's settings catalogue, when it ships one (OpenCollar's `catalog.json`)."""
    path = Path(__file__).resolve().parents[1] / "device_drivers" / driver_key / "catalog.json"
    if not path.exists():
        return []
    try:
        document = json.loads(path.read_text())
    except ValueError:
        return []
    settings = document.get("settings") if isinstance(document, dict) else None
    return [s for s in settings or [] if isinstance(s, dict)]


@dataclass(slots=True)
class Declared:
    """The declared intervals and where each comes from."""

    fix: tuple[float, str] | None
    status: tuple[float, str] | None
    override: dict[str, Any] | None


def override_of(device: Device) -> dict[str, Any] | None:
    value = (device.attributes or {}).get(OVERRIDE_ATTRIBUTE)
    if isinstance(value, dict) and isinstance(value.get("seconds"), int | float):
        return value
    return None


async def declared_intervals(
    session: AsyncSession, device: Device, device_type: DeviceType | None, until: datetime
) -> Declared:
    """The declared fix and status intervals as of `until`, most trustworthy source first: a
    person's override, the newest settings frame the device sent, an acknowledged interval
    command, the type's and the device's declared settings."""
    catalog = driver_catalog(device_type.driver_key) if device_type else []
    base = merged_settings(
        {str(s.get("name")): s.get("default") for s in catalog},
        dict(device_type.default_settings or {}) if device_type else None,
        (device.attributes or {}).get("settings")
        if isinstance((device.attributes or {}).get("settings"), dict)
        else None,
    )
    frames: dict[str, Any] = {}
    if catalog:
        rows = (
            await session.execute(
                select(DeviceStateHistory.state)
                .where(DeviceStateHistory.device_id == device.id, DeviceStateHistory.time < until)
                .order_by(DeviceStateHistory.time.desc())
                .limit(FRAMES_TO_READ * 10)
            )
        ).scalars()
        seen = 0
        for state in rows:
            tlvs = {
                k: v
                for k, v in (state or {}).items()
                if k.startswith("port_") and k.endswith("_tlv") and isinstance(v, dict)
            }
            if not tlvs:
                continue
            seen += 1
            for tlv in tlvs.values():
                # the newest frame wins: it is read first and only fills what is still empty
                for key, value in decode_tlv_settings(tlv, catalog).items():
                    frames.setdefault(key, value)
            if seen >= FRAMES_TO_READ:
                break
    command = await session.scalar(
        select(Command.parameters[INTERVAL_PARAMETER].as_integer())
        .join(CommandExecution, CommandExecution.command_id == Command.id)
        .where(
            Command.device_id == device.id,
            Command.action_key == INTERVAL_COMMAND,
            CommandExecution.status.in_([s.value for s in ACKNOWLEDGED]),
            CommandExecution.time < until,
        )
        .order_by(CommandExecution.time.desc())
        .limit(1)
    )
    override = override_of(device)
    fix: tuple[float, str] | None = None
    if override is not None:
        fix = (float(override["seconds"]), "override")
    elif expected_intervals(frames)["fix"]:
        fix = (float(expected_intervals(frames)["fix"] or 0), "settings_frame")
    elif isinstance(command, int) and command > 0:
        fix = (float(command), "command")
    elif expected_intervals(base)["fix"]:
        fix = (float(expected_intervals(base)["fix"] or 0), "type_default")
    status: tuple[float, str] | None = None
    if expected_intervals(frames)["status"]:
        status = (float(expected_intervals(frames)["status"] or 0), "settings_frame")
    elif expected_intervals(base)["status"]:
        status = (float(expected_intervals(base)["status"] or 0), "type_default")
    return Declared(fix=fix, status=status, override=override)


async def fix_times(
    session: AsyncSession, device_id: uuid.UUID, time_from: datetime, time_to: datetime
) -> np.ndarray:
    """The effective times of the device's valid own fixes in the window, in seconds."""
    rows = (
        await session.execute(
            select(effective_time(Position))
            .where(
                Position.device_id == device_id,
                effective_time(Position) >= time_from,
                effective_time(Position) < time_to,
                visible(Position),
                device_fix(),
            )
            .order_by(effective_time(Position))
        )
    ).scalars()
    return np.asarray([r.timestamp() for r in rows], dtype=np.float64)


async def expected_fix_interval(
    session: AsyncSession, device: Device, device_type: DeviceType | None, now: datetime
) -> tuple[Expected, Declared, int]:
    """The device page's view: the declared intervals, the expectation resolved against the
    `LEARN_DAYS` days up to the device's last valid fix (capped at now, as the device page
    anchors its positions, decision D207: a collar silent for a year still shows its
    schedule), and how many fixes were learned from."""
    newest = await session.scalar(
        select(func.max(effective_time(Position))).where(
            Position.device_id == device.id, visible(Position), device_fix()
        )
    )
    until = min(newest + timedelta(minutes=1), now) if newest is not None else now
    declared = await declared_intervals(session, device, device_type, until)
    times = await fix_times(session, device.id, until - timedelta(days=LEARN_DAYS), until)
    return resolve_expected(declared.fix, times), declared, int(times.size)
