"""Settings files per device (decisions D426 to D429, Tim, 2026-11-27): the files the
ble-settings-app exports and imports, kept per device, and the snapshot Protect makes of a whole
read over Web Bluetooth. Reading follows the device; uploading, a snapshot, deleting and a
download with the credentials need the control permission in the device's project."""

import json
import uuid
from types import ModuleType
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.auth.users import current_active_user
from protect_api.routers.control import _control_permissions
from protect_api.routers.devices import _visible_device
from protect_api.schemas.settings_files import (
    SettingsFileList,
    SettingsFileRead,
    SettingsFileStored,
    SettingsFileUpload,
    SettingsSnapshotRequest,
    SettingsSnapshotStored,
)
from shared.database import get_session
from shared.domain.device_settings import known_settings
from shared.domain.reporting import driver_catalog
from shared.domain.reporting_rules import decode_setting_value
from shared.domain.settings_files import (
    FILES_LISTED,
    MAX_DOCUMENT_BYTES,
    MIN_SNAPSHOT_SETTINGS,
    device_euis,
    file_count,
    file_name,
    record_file_settings,
    settings_codec,
    store_settings_file,
)
from shared.models import Device, DeviceSettingsFile, DeviceType, User
from shared.permissions import Permission
from shared.timeutil import utc_now

router = APIRouter(tags=["settings files"])


async def _device(
    session: AsyncSession, user: User, device_id: uuid.UUID
) -> tuple[Device, str, ModuleType]:
    device = await _visible_device(session, user, device_id)
    device_type = await session.get(DeviceType, device.device_type_id)
    driver_key = device_type.driver_key if device_type else ""
    codec = settings_codec(driver_key)
    if codec is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "This device type's driver has no settings files",
        )
    return device, driver_key, codec


async def _may_control(session: AsyncSession, user: User, device: Device) -> uuid.UUID | None:
    project_id, permissions = await _control_permissions(session, user, device)
    if Permission.DEVICES_CONTROL not in permissions:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"Permission {Permission.DEVICES_CONTROL} required"
        )
    return project_id


def _download(document: dict[str, Any], filename: str) -> Response:
    """The file as the app writes it: two spaces of indent, the keys in their order."""
    safe = filename.replace('"', "").replace("\\", "")
    return Response(
        content=json.dumps(document, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{safe}"'},
    )


@router.get("/devices/{device_id}/settings-files", response_model=SettingsFileList)
async def list_settings_files(
    device_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> SettingsFileList:
    """The device's settings files, newest first, at most 200."""
    device, _, _ = await _device(session, user, device_id)
    rows = await session.scalars(
        select(DeviceSettingsFile)
        .where(DeviceSettingsFile.device_id == device.id)
        .order_by(DeviceSettingsFile.created_at.desc(), DeviceSettingsFile.id.desc())
        .limit(FILES_LISTED)
    )
    _, permissions = await _control_permissions(session, user, device)
    return SettingsFileList(
        items=[SettingsFileRead.model_validate(row) for row in rows],
        total=await file_count(session, device.id),
        can_download_credentials=Permission.DEVICES_CONTROL in permissions,
    )


@router.post("/devices/{device_id}/settings-files", response_model=SettingsFileStored)
async def upload_settings_file(
    device_id: uuid.UUID,
    body: SettingsFileUpload,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> SettingsFileStored:
    """Keep a file the ble-settings-app exported. A file that names another device's DevEUI is
    refused. What it says becomes known where it is newer than what Protect has; without an
    export time it only fills in what Protect does not know."""
    device, driver_key, codec = await _device(session, user, device_id)
    project_id = await _may_control(session, user, device)
    if len(json.dumps(body.document)) > MAX_DOCUMENT_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "A settings file is at most 64 kB")
    try:
        parsed = codec.read_settings_file(
            body.document, driver_catalog(driver_key, device.firmware_version)
        )
    except ValueError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    eui = codec.file_identity(body.document)
    known_euis = await device_euis(session, device.id)
    if eui is not None and known_euis and eui not in known_euis:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"This file was exported from another device (DevEUI {eui.upper()})",
        )
    now = utc_now()
    exported_at = body.exported_at if body.exported_at and body.exported_at <= now else None
    row, created = await store_settings_file(
        session,
        device.id,
        source="upload",
        filename=body.filename,
        document=body.document,
        has_credentials=bool(codec.CREDENTIAL_KEYS & body.document.keys()),
        firmware=device.firmware_version,
        observed_at=exported_at,
        user_id=user.id,
    )
    recorded = 0
    if created:
        recorded = await record_file_settings(
            session,
            device.id,
            parsed.settings,
            source="file",
            observed_at=exported_at,
            recorded_at=now,
            user_id=user.id,
        )
        await record_audit(
            session,
            user=user,
            action="device.settings_file_uploaded",
            object_type="device",
            object_id=str(device.id),
            project_id=project_id,
            details={"file_id": str(row.id), "filename": row.filename, "recorded": recorded},
        )
    await session.commit()
    return SettingsFileStored(
        file=SettingsFileRead.model_validate(row),
        created=created,
        recorded=recorded,
        unknown=parsed.unknown,
        invalid=parsed.invalid,
    )


@router.post("/devices/{device_id}/settings-files/snapshot", response_model=SettingsSnapshotStored)
async def snapshot_settings(
    device_id: uuid.UUID,
    body: SettingsSnapshotRequest,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> SettingsSnapshotStored:
    """What the browser read from the device over Web Bluetooth (decision D427): every value
    becomes known at once, and a whole read that differs from the device's newest file is kept
    as a snapshot in the app's format (D428)."""
    device, driver_key, codec = await _device(session, user, device_id)
    await _may_control(session, user, device)
    firmware = body.firmware or device.firmware_version
    catalog = driver_catalog(driver_key, firmware)
    by_id = {int(item["id"]): item for item in catalog if "id" in item}
    now = utc_now()
    read_at = min(body.read_at, now)
    settings = []
    for entry in body.values:
        item = by_id.get(entry.id)
        if item is None:
            continue
        raw = bytes.fromhex(entry.hex)
        value = decode_setting_value(item, raw)
        if value is None:
            continue
        settings.append(
            codec.FileSetting(
                key=str(item["name"]), setting_id=entry.id, value=value, raw_hex=raw.hex()
            )
        )
    recorded = await record_file_settings(
        session,
        device.id,
        settings,
        source="ble",
        observed_at=read_at,
        recorded_at=now,
        user_id=user.id,
    )
    row, created = None, False
    if body.complete and len(settings) >= MIN_SNAPSHOT_SETTINGS:
        values = {item.key: item.value for item in settings}
        document = codec.write_settings_file(values, catalog)
        row, created = await store_settings_file(
            session,
            device.id,
            source="ble",
            filename=file_name(str(values.get("device_name") or device.name), read_at),
            document=document,
            has_credentials=bool(codec.CREDENTIAL_KEYS & document.keys()),
            firmware=firmware,
            observed_at=read_at,
            user_id=user.id,
        )
    await session.commit()
    return SettingsSnapshotStored(
        recorded=recorded,
        file=SettingsFileRead.model_validate(row) if row is not None else None,
        created=created,
    )


@router.get("/devices/{device_id}/settings-files/current/download")
async def download_current_settings(
    device_id: uuid.UUID,
    credentials: bool = Query(default=False, description="With the device credentials"),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """What Protect knows of the device's settings now, as a file the ble-settings-app
    imports. Settings Protect does not know are left out, as the app leaves out what the
    device did not report."""
    device, driver_key, codec = await _device(session, user, device_id)
    project_id = await _may_control(session, user, device) if credentials else None
    known = await known_settings(session, device.id)
    values = {key: row.value for key, row in known.items()}
    document = codec.write_settings_file(
        values,
        driver_catalog(driver_key, device.firmware_version),
        include_credentials=credentials,
    )
    if not document:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Protect knows no setting of this device yet"
        )
    if credentials:
        await record_audit(
            session,
            user=user,
            action="device.settings_file_downloaded",
            object_type="device",
            object_id=str(device.id),
            project_id=project_id,
            details={"file": "current", "credentials": True},
        )
        await session.commit()
    return _download(document, file_name(str(values.get("device_name") or device.name), utc_now()))


async def _file(session: AsyncSession, device: Device, file_id: uuid.UUID) -> DeviceSettingsFile:
    row = await session.get(DeviceSettingsFile, file_id)
    if row is None or row.device_id != device.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Settings file not found")
    return row


@router.get("/devices/{device_id}/settings-files/{file_id}/download")
async def download_settings_file(
    device_id: uuid.UUID,
    file_id: uuid.UUID,
    credentials: bool = Query(default=False, description="With the device credentials"),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Response:
    """A stored file as it was kept; without `credentials`, or for a person who may not
    control the device, without the credential keys (decision D429)."""
    device, _, codec = await _device(session, user, device_id)
    row = await _file(session, device, file_id)
    if not credentials:
        return _download(codec.without_credentials(row.document), row.filename)
    project_id = await _may_control(session, user, device)
    if row.has_credentials:
        await record_audit(
            session,
            user=user,
            action="device.settings_file_downloaded",
            object_type="device",
            object_id=str(device.id),
            project_id=project_id,
            details={"file_id": str(row.id), "filename": row.filename, "credentials": True},
        )
        await session.commit()
    return _download(row.document, row.filename)


@router.delete(
    "/devices/{device_id}/settings-files/{file_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_settings_file(
    device_id: uuid.UUID,
    file_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Remove a stored file. The settings Protect knows stay as they are."""
    device, _, _ = await _device(session, user, device_id)
    project_id = await _may_control(session, user, device)
    row = await _file(session, device, file_id)
    await record_audit(
        session,
        user=user,
        action="device.settings_file_deleted",
        object_type="device",
        object_id=str(device.id),
        project_id=project_id,
        details={"file_id": str(row.id), "filename": row.filename},
    )
    await session.delete(row)
    await session.commit()
