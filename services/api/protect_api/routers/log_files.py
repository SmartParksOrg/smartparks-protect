"""Raw device log files as managed assets (architecture 25.6, decision D77) and browser syncs
(architecture 25.4): upload or sync, list, inspect, download the original, decode again."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.auth.users import current_active_user
from protect_api.bus import get_bus
from protect_api.crud import get_or_404
from protect_api.routers.control import _control_permissions
from protect_api.routers.devices import _visible_device
from protect_api.schemas.log_files import BleSyncRequest, DeviceLogFileRead, DriverCatalog
from shared.bus import RedisStreamsBus
from shared.config import get_settings
from shared.control.commands import driver_for
from shared.database import get_session
from shared.enums import AcquisitionChannel, LogFileStatus
from shared.logfiles import (
    DuplicateLogFile,
    frames_to_text,
    log_file_message,
    parse_log_text,
    store_log_file,
)
from shared.models import Device, DeviceLogFile, User
from shared.permissions import Permission
from shared.storage import stream_object
from shared.timeutil import utc_now
from shared.trace import ApplicationError

router = APIRouter(tags=["log files"])

TEXT_TYPES = ("text/", "application/octet-stream", "application/x-", "")


async def _writable_device(session: AsyncSession, user: User, device_id: uuid.UUID) -> Device:
    """Uploading or syncing device data needs the control permission in the device's project
    (a viewer reads, an admin acts), or server admin."""
    device = await _visible_device(session, user, device_id)
    _, permissions = await _control_permissions(session, user, device)
    if Permission.DEVICES_CONTROL not in permissions:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"Permission {Permission.DEVICES_CONTROL} required"
        )
    return device


async def _publish(bus: RedisStreamsBus, row: DeviceLogFile, *, reprocess: bool = False) -> None:
    topic, payload = log_file_message(row, reprocess=reprocess)
    await bus.publish(topic, payload, trace_id=str(row.trace_id) if row.trace_id else None)


@router.post(
    "/devices/{device_id}/log-files",
    response_model=DeviceLogFileRead,
    status_code=status.HTTP_201_CREATED,
)
async def upload_log_file(
    device_id: uuid.UUID,
    file: UploadFile,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> DeviceLogFile:
    """Upload a raw log file retrieved from the device (one base64 or hex frame per line, the
    format the public BLE app exports). The same file for the same device is refused with 409
    and the existing row."""
    device = await _writable_device(session, user, device_id)
    settings = get_settings()
    data = await file.read(settings.log_file_max_bytes + 1)
    if len(data) > settings.log_file_max_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"The file exceeds {settings.log_file_max_bytes} bytes",
        )
    if not data.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file is empty")
    try:
        preview = parse_log_text(data.decode("utf-8"))
    except UnicodeDecodeError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "The file is not a text file of frames"
        ) from None
    if not preview.frames:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "No frame found: expected one base64 or hex frame per line"
            + (f" (line {preview.errors[0][0]}: {preview.errors[0][1]})" if preview.errors else ""),
        )
    try:
        row = await store_log_file(
            session,
            device=device,
            data=data,
            filename=file.filename or "log.txt",
            channel=AcquisitionChannel.LOG_FILE,
            user_id=user.id,
            attributes={"content_type": file.content_type or ""},
        )
    except DuplicateLogFile as duplicate:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "message": "This file was uploaded before for this device",
                "log_file_id": str(duplicate.existing.id),
            },
        ) from None
    except ApplicationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    await record_audit(
        session,
        user=user,
        action="log_file.uploaded",
        object_type="log_file",
        object_id=str(row.id),
        project_id=row.project_id,
        details={
            "device_id": str(device.id),
            "filename": row.original_filename,
            "bytes": row.size_bytes,
            "frames": len(preview.frames),
        },
    )
    await session.commit()
    await _publish(bus, row)
    return row


@router.post(
    "/devices/{device_id}/log-files/ble-sync",
    response_model=DeviceLogFileRead,
    status_code=status.HTTP_201_CREATED,
)
async def ble_sync(
    device_id: uuid.UUID,
    body: BleSyncRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> DeviceLogFile:
    """Frames the browser read over Web Bluetooth become a log file of channel `webble` and
    are decoded like an upload; the sync time is kept as provenance (architecture 25.3)."""
    device = await _writable_device(session, user, device_id)
    frames: list[bytes] = []
    for index, item in enumerate(body.frames):
        try:
            frame = bytes.fromhex(item)
        except ValueError:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"frame {index} is not hex"
            ) from None
        if len(frame) < 2:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"frame {index} is shorter than 2 bytes"
            )
        frames.append(frame)
    synced_at = body.ble_synced_at or utc_now()
    label = body.label.strip() or "webble-sync"
    filename = f"{label}-{synced_at:%Y%m%dT%H%M%SZ}.txt"
    try:
        row = await store_log_file(
            session,
            device=device,
            data=frames_to_text(frames).encode(),
            filename=filename,
            channel=AcquisitionChannel.WEBBLE,
            user_id=user.id,
            ble_synced_at=synced_at,
            attributes=dict(body.attributes),
        )
    except DuplicateLogFile as duplicate:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "message": "These frames were synced before for this device",
                "log_file_id": str(duplicate.existing.id),
            },
        ) from None
    except ApplicationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    await record_audit(
        session,
        user=user,
        action="log_file.ble_synced",
        object_type="log_file",
        object_id=str(row.id),
        project_id=row.project_id,
        details={"device_id": str(device.id), "frames": len(frames)},
    )
    await session.commit()
    await _publish(bus, row)
    return row


@router.get("/devices/{device_id}/log-files", response_model=list[DeviceLogFileRead])
async def list_log_files(
    device_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=500),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> list[DeviceLogFile]:
    device = await _visible_device(session, user, device_id)
    rows = await session.scalars(
        select(DeviceLogFile)
        .where(DeviceLogFile.device_id == device.id)
        .order_by(DeviceLogFile.uploaded_at.desc())
        .limit(limit)
    )
    return list(rows)


@router.get("/devices/{device_id}/driver-catalog", response_model=DriverCatalog)
async def driver_catalog(
    device_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> DriverCatalog:
    """The driver's protocol catalogue (settings, commands, values) for the WebBLE settings
    editor; empty for drivers without one."""
    device = await _visible_device(session, user, device_id)
    driver_key, driver = await driver_for(session, device)
    catalog = getattr(driver, "catalog", None)
    data: dict[str, Any] = catalog() if callable(catalog) else {}
    return DriverCatalog(driver_key=driver_key, catalog=data)


@router.get("/log-files/{log_file_id}", response_model=DeviceLogFileRead)
async def get_log_file(
    log_file_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> DeviceLogFile:
    row = await get_or_404(session, DeviceLogFile, log_file_id, "Log file")
    await _visible_device(session, user, row.device_id)
    return row


@router.get("/log-files/{log_file_id}/download")
async def download_log_file(
    log_file_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """The original file, byte for byte."""
    row = await get_or_404(session, DeviceLogFile, log_file_id, "Log file")
    await _visible_device(session, user, row.device_id)
    safe_name = row.original_filename.replace('"', "")
    return StreamingResponse(
        stream_object(get_settings().minio_bucket_log_files, row.object_key),
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


@router.post("/log-files/{log_file_id}/redecode", response_model=DeviceLogFileRead)
async def redecode_log_file(
    log_file_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> DeviceLogFile:
    """Decode the stored frames again, for example after a decoder update. Records known
    already are recognised by their canonical keys, so nothing is duplicated."""
    row = await get_or_404(session, DeviceLogFile, log_file_id, "Log file")
    await _writable_device(session, user, row.device_id)
    if row.status == LogFileStatus.PROCESSING:
        raise HTTPException(status.HTTP_409_CONFLICT, "The file is being decoded now")
    failed_before_frames = row.status == LogFileStatus.FAILED and row.frames_total == 0
    row.status = LogFileStatus.QUEUED
    row.error_code = None
    row.error_message = None
    await record_audit(
        session,
        user=user,
        action="log_file.redecode",
        object_type="log_file",
        object_id=str(row.id),
        project_id=row.project_id,
        details={"device_id": str(row.device_id)},
    )
    await session.commit()
    # A file that never produced frames is read again from the bucket; otherwise the stored
    # frames are reprocessed.
    await _publish(bus, row, reprocess=not failed_before_frames)
    return row
