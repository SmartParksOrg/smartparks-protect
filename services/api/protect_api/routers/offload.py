"""Offload stations and the trackers' LP0 credentials (phase 42, decisions D319 to D324).

A tracker's LP0 address and keys live on the device (D320), set here and never returned. A
station's card is uploaded on the station's device page as the files are, one JSONL or a zip of
the card's `LOG_*` folders (D321), each file a raw log file row of the station with channel
`lp0`. The Offload station card reads what the cards brought and whom the station served."""

import uuid
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.auth.users import current_active_user
from protect_api.bus import get_bus
from protect_api.routers.devices import _visible_device
from protect_api.routers.log_files import _publish, _writable_device
from protect_api.schemas.offload import (
    Lp0CredentialsRead,
    Lp0CredentialsResult,
    Lp0CredentialsUpdate,
    Lp0Readback,
    OffloadStationRead,
    OffloadTracker,
    OffloadUpload,
    SkippedMember,
)
from shared.bus import RedisStreamsBus
from shared.config import get_settings
from shared.database import get_session
from shared.domain.device_settings import known_settings
from shared.domain.lp0 import (
    AddressTaken,
    clear_credentials,
    credentials_summary,
    keys_from_readback,
    lp0_source,
    normalise_dev_addr,
    parse_key,
    set_credentials,
    station_eui_from_name,
)
from shared.enums import AcquisitionChannel
from shared.ingest import queue_identity_reprocess, retained_events
from shared.logfiles import (
    DuplicateLogFile,
    looks_like_station_file,
    parse_station_jsonl,
    store_log_file,
    unpack_card_zip,
)
from shared.models import (
    Device,
    DeviceCurrentState,
    DeviceLogFile,
    DeviceLp0Credentials,
    ExternalIdentity,
    GatewayReception,
    User,
)
from shared.timeutil import utc_now
from shared.trace import ApplicationError

router = APIRouter(tags=["offload stations"])

#: The trackers a station served: its receptions over this window, one gateway's segment.
TRACKERS_WINDOW = timedelta(days=30)
MAX_TRACKERS = 200
READBACK_KEYS = ("lp0_dev_addr", "lp0_app_key", "lp0_network_key")


async def _readback(session: AsyncSession, device_id: uuid.UUID) -> Lp0Readback:
    settings = await known_settings(session, device_id)
    rows = {k: settings[k] for k in READBACK_KEYS if k in settings}
    if not rows:
        return Lp0Readback()
    address = None
    if "lp0_dev_addr" in rows:
        try:
            address = normalise_dev_addr(_text(rows["lp0_dev_addr"].value))
        except ValueError:
            address = None
    return Lp0Readback(
        dev_addr=address,
        app_key_known="lp0_app_key" in rows,
        network_key_known="lp0_network_key" in rows,
        observed_at=max(r.observed_at for r in rows.values()),
    )


def _text(value: Any) -> str:
    if isinstance(value, list):
        return bytes(int(v) for v in value).hex()
    return str(value)


async def _frames_waiting(session: AsyncSession, dev_addr: str | None) -> int:
    if dev_addr is None:
        return 0
    source = await lp0_source(session)
    identity = await session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.data_source_id == source.id, ExternalIdentity.external_id == dev_addr
        )
    )
    if identity is None:
        return 0
    return int(
        await session.scalar(select(func.count()).select_from(retained_events(identity).subquery()))
        or 0
    )


async def _credentials_read(session: AsyncSession, device: Device) -> Lp0CredentialsRead:
    row = await session.get(DeviceLp0Credentials, device.id)
    summary = credentials_summary(row)
    return Lp0CredentialsRead(
        dev_addr=summary["dev_addr"],
        keys_set=bool(summary["keys_set"]),
        set_at=summary["set_at"],
        source=summary["source"],
        readback=await _readback(session, device.id),
        frames_waiting=await _frames_waiting(session, row.dev_addr if row else None),
    )


@router.get("/devices/{device_id}/lp0-credentials", response_model=Lp0CredentialsRead)
async def get_lp0_credentials(
    device_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Lp0CredentialsRead:
    """The device's LP0 address and whether its keys are set; the keys themselves never."""
    device = await _visible_device(session, user, device_id)
    return await _credentials_read(session, device)


@router.put("/devices/{device_id}/lp0-credentials", response_model=Lp0CredentialsResult)
async def set_lp0_credentials(
    device_id: uuid.UUID,
    body: Lp0CredentialsUpdate,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> Lp0CredentialsResult:
    """Set the tracker's LP0 address and keys (decision D320): typed in, or taken from what
    the device reported in its settings readback. The address becomes the device's identity
    on the offload station source; frames stored for it before are handed to the decoder."""
    device = await _writable_device(session, user, device_id)
    source = "person"
    if body.from_device:
        settings = await known_settings(session, device.id)
        values = keys_from_readback({k: v.value for k, v in settings.items()})
        if values is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "The device has not reported its LP0 address and both keys",
            )
        address, app_key, nwk_key = values
        source = "device"
    else:
        try:
            address = normalise_dev_addr(body.dev_addr or "")
            app_key = parse_key(body.app_s_key or "")
            nwk_key = parse_key(body.nwk_s_key or "")
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    try:
        result = await set_credentials(
            session,
            device,
            dev_addr=address,
            app_s_key=app_key,
            nwk_s_key=nwk_key,
            user_id=user.id,
            source=source,
        )
    except AddressTaken as taken:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"The address is held by {taken.device.name}"
        ) from None
    await record_audit(
        session,
        user=user,
        action="device.lp0_credentials_set",
        object_type="device",
        object_id=str(device.id),
        details={
            "dev_addr": address,
            "source": source,
            "previous_dev_addr": result.previous_dev_addr,
        },
    )
    await session.commit()
    queued = 0
    if result.linked_waiting:
        queued = await queue_identity_reprocess(session, bus, result.identity)
    read = await _credentials_read(session, device)
    return Lp0CredentialsResult(**read.model_dump(), queued=queued)


@router.delete("/devices/{device_id}/lp0-credentials", status_code=status.HTTP_204_NO_CONTENT)
async def delete_lp0_credentials(
    device_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> None:
    device = await _writable_device(session, user, device_id)
    address = await clear_credentials(session, device)
    await record_audit(
        session,
        user=user,
        action="device.lp0_credentials_cleared",
        object_type="device",
        object_id=str(device.id),
        details={"dev_addr": address},
    )
    await session.commit()


@router.post(
    "/devices/{device_id}/offload-files",
    response_model=OffloadUpload,
    status_code=status.HTTP_201_CREATED,
)
async def upload_offload_files(
    device_id: uuid.UUID,
    file: UploadFile,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> OffloadUpload:
    """The files of an offload station's SD card (decision D321): one `.jsonl`, or a zip of
    the card's `LOG_*` folders, uploaded on the station's device page. Every file becomes a
    raw log file row of the station with channel `lp0`; a file seen before is skipped with
    its reason, as is a member that is not a station file."""
    device = await _writable_device(session, user, device_id)
    settings = get_settings()
    data = await file.read(settings.lp0_zip_max_bytes + 1)
    if len(data) > settings.lp0_zip_max_bytes:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            f"The upload exceeds {settings.lp0_zip_max_bytes} bytes",
        )
    if not data.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "The file is empty")
    name = file.filename or "card.jsonl"
    members: list[tuple[str, str, bytes]] = []
    skipped: list[SkippedMember] = []
    if name.lower().endswith(".zip") or data[:2] == b"PK":
        try:
            card = unpack_card_zip(data, member_max_bytes=settings.log_file_max_bytes)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
        members = [(m.name, m.folder, m.data) for m in card.members]
        skipped = [SkippedMember(name=n, reason="not a station file") for n in card.skipped]
        if not members:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "The zip holds no station file (LOG_N/STATIONEUI_timestamp.jsonl)",
            )
    else:
        if len(data) > settings.log_file_max_bytes:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                f"The file exceeds {settings.log_file_max_bytes} bytes",
            )
        if not looks_like_station_file(name, data):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "Not a station file: one JSON document per line expected, or a zip of the "
                "card's LOG folders",
            )
        members = [(name.rsplit("/", 1)[-1], "", data)]
    serial = (device.serial_number or "").upper()
    rows: list[DeviceLogFile] = []
    other_station: list[str] = []
    for member_name, folder, content in members:
        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError:
            skipped.append(SkippedMember(name=member_name, reason="not a text file"))
            continue
        parsed = parse_station_jsonl(text)
        if not parsed.frames:
            first = f" (line {parsed.errors[0][0]}: {parsed.errors[0][1]})" if parsed.errors else ""
            skipped.append(SkippedMember(name=member_name, reason=f"no frame found{first}"))
            continue
        eui = station_eui_from_name(member_name) or parsed.frames[0].station_eui
        if serial and eui != serial:
            other_station.append(member_name)
        try:
            row = await store_log_file(
                session,
                device=device,
                data=content,
                filename=member_name,
                channel=AcquisitionChannel.LP0,
                user_id=user.id,
                attributes={
                    "content_type": file.content_type or "",
                    "folder": folder,
                    "station_eui": eui,
                    "frames_in_file": len(parsed.frames),
                },
            )
        except DuplicateLogFile:
            skipped.append(SkippedMember(name=member_name, reason="uploaded before"))
            continue
        except ApplicationError as error:
            skipped.append(SkippedMember(name=member_name, reason=str(error)))
            continue
        rows.append(row)
    if not rows and skipped:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "; ".join(f"{s.name}: {s.reason}" for s in skipped[:5]),
        )
    await record_audit(
        session,
        user=user,
        action="offload_files.uploaded",
        object_type="device",
        object_id=str(device.id),
        project_id=rows[0].project_id if rows else None,
        details={
            "upload": name,
            "files": [r.original_filename for r in rows],
            "skipped": [s.name for s in skipped],
        },
    )
    await session.commit()
    for row in rows:
        await _publish(bus, row)
    return OffloadUpload(files=rows, skipped=skipped, other_station=other_station)


@router.get("/devices/{device_id}/offload", response_model=OffloadStationRead)
async def offload_station(
    device_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> OffloadStationRead:
    """The Offload station card (decision D322): the files a station's cards brought, their
    frames and records, the trackers the station served in the last 30 days from its
    receptions, and the station's own last report."""
    device = await _visible_device(session, user, device_id)
    rows = (
        await session.scalars(
            select(DeviceLogFile)
            .where(
                DeviceLogFile.device_id == device.id,
                DeviceLogFile.acquisition_channel == AcquisitionChannel.LP0,
            )
            .order_by(DeviceLogFile.uploaded_at.desc())
            .limit(1000)
        )
    ).all()
    eui = (device.serial_number or "").upper() or next(
        (str(r.attributes.get("station_eui")) for r in rows if r.attributes.get("station_eui")),
        None,
    )
    read = OffloadStationRead(
        device_id=device.id,
        station_eui=eui or None,
        is_station=bool(rows),
        files=len(rows),
        frames=sum(r.frames_total for r in rows),
        frames_retained=sum(int(r.attributes.get("frames_retained") or 0) for r in rows),
        frames_repeated=sum(int(r.attributes.get("frames_repeated") or 0) for r in rows),
        records_new=sum(r.records_new for r in rows),
        records_known=sum(r.records_duplicate for r in rows),
        last_upload_at=max((r.uploaded_at for r in rows), default=None),
    )
    if eui:
        source = await lp0_source(session)
        until = utc_now()
        since = until - TRACKERS_WINDOW
        stats = (
            await session.execute(
                select(
                    GatewayReception.device_id,
                    func.count().label("frames"),
                    func.max(GatewayReception.time).label("last"),
                    func.avg(GatewayReception.rssi).label("rssi"),
                )
                .where(
                    GatewayReception.data_source_id == source.id,
                    GatewayReception.gateway_id == eui.lower(),
                    GatewayReception.time >= since,
                    GatewayReception.time <= until,
                )
                .group_by(GatewayReception.device_id)
                .order_by(func.max(GatewayReception.time).desc())
                .limit(MAX_TRACKERS)
            )
        ).all()
        ids = [s.device_id for s in stats if s.device_id is not None]
        devices = {
            d.id: d for d in (await session.scalars(select(Device).where(Device.id.in_(ids)))).all()
        }
        addresses = {
            c.device_id: c.dev_addr
            for c in (
                await session.scalars(
                    select(DeviceLp0Credentials).where(DeviceLp0Credentials.device_id.in_(ids))
                )
            ).all()
        }
        read.is_station = read.is_station or bool(stats)
        read.last_reception_at = max((s.last for s in stats), default=None)
        read.trackers = [
            OffloadTracker(
                dev_addr=addresses.get(s.device_id) if s.device_id else None,
                device_id=s.device_id,
                device_name=devices[s.device_id].name if s.device_id in devices else None,
                frames=int(s.frames),
                last_reception_at=s.last,
                mean_rssi=round(float(s.rssi), 1) if s.rssi is not None else None,
            )
            for s in stats
        ]
    current = await session.get(DeviceCurrentState, device.id)
    report = (current.latest_state or {}).get("lp0_station") if current else None
    if isinstance(report, dict):
        read.state = report
        read.state_time = current.latest_state_time if current else None
        read.is_station = True
    return read
