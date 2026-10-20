"""Offload stations and the trackers' LP0 credentials (phase 42, decisions D319 to D324).

A tracker's LP0 address and keys live on the device (D320), set here and returned to those who
may set them. A station is set up from the Offload page in one call (entity, place, gateway row). A
station's card is uploaded on the station's device page as the files are, one JSONL or a zip of
the card's `LOG_*` folders (D321), each file a raw log file row of the station with channel
`lp0`. The Offload station card reads what the cards brought and whom the station served."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.auth.users import current_active_user
from protect_api.bus import get_bus
from protect_api.crud import flush_or_409, geom_to_geojson, get_or_404
from protect_api.deps import ProjectContext, require_permission
from protect_api.routers.control import _control_permissions
from protect_api.routers.devices import _visible_device
from protect_api.routers.entities import _new_entity, _project_entity
from protect_api.routers.log_files import _publish, _writable_device
from protect_api.schemas.domain import EntityCreate
from protect_api.schemas.log_files import DeviceLogFileRead
from protect_api.schemas.offload import (
    Lp0CredentialsRead,
    Lp0CredentialsResult,
    Lp0CredentialsUpdate,
    Lp0Readback,
    Lp0WalkResult,
    OffloadOverviewRead,
    OffloadOverviewStation,
    OffloadOverviewTracker,
    OffloadStationRead,
    OffloadStationSetup,
    OffloadStationSetupResult,
    OffloadTracker,
    OffloadUnknownAddress,
    OffloadUpload,
    SkippedMember,
)
from shared.bus import RedisStreamsBus
from shared.config import get_settings
from shared.database import get_session
from shared.device_drivers.opencollar import lp0_sd_card_ok
from shared.domain.assignments import resolve_attribution
from shared.domain.device_settings import known_settings
from shared.domain.lp0 import (
    AddressTaken,
    addresses_of,
    card_euis_of,
    claim_address,
    clear_credentials,
    credentials_for,
    credentials_summary,
    device_eui,
    keys_from_readback,
    lp0_source,
    normalise_dev_addr,
    parse_key,
    register_station_gateway,
    set_credentials,
    station_device,
)
from shared.domain.static_place import place_device, place_entity_of, unplace_device
from shared.enums import AcquisitionChannel
from shared.ingest import queue_identity_reprocess, retained_events
from shared.logfiles import DuplicateLogFile, store_log_file
from shared.models import (
    Device,
    DeviceCurrentState,
    DeviceEntityAssignment,
    DeviceLogFile,
    DeviceLp0Credentials,
    DeviceProjectAssignment,
    Entity,
    EntityType,
    ExternalIdentity,
    Gateway,
    GatewayReception,
    SourceEvent,
    User,
)
from shared.permissions import Permission, permissions_for
from shared.station_files import (
    looks_like_station_file,
    parse_station_jsonl,
    station_eui_from_name,
    unpack_card_zip,
)
from shared.timeutil import utc_now
from shared.trace import ApplicationError

router = APIRouter(tags=["offload stations"])

#: The trackers a station served: its receptions over this window, one gateway's segment. The
#: window is the arrival at Protect (`source_event_ingested_at`, the upload of a card), not the
#: station's clock (Tim, 2026-10-19: SP052099 stamps a month behind, so "frames of 1 trackers"
#: counted 46 of 13,671); the first and last reception keep the station's time.
TRACKERS_WINDOW = timedelta(days=30)
MAX_TRACKERS = 200
READBACK_KEYS = ("lp0_dev_addr", "lp0_app_key", "lp0_network_key")
#: The catalogue row a station's entity is made of (migration 0053, under Equipment).
STATION_TYPE_KEY = "offload_station"
#: The ports a frame carries in the clear (decision D341): a station's own status report (D323)
#: and a tracker's stored stream (D262).
STATION_REPORT_PORT = 23
STORED_STREAM_PORT = 29


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


async def _may_set(session: AsyncSession, user: User, device: Device) -> bool:
    """Whether the caller may set the device's keys, and so read them back (Tim, 2026-10-15:
    the credentials are important and must be visible and changeable when needed)."""
    if user.is_superuser:
        return True
    _project, permissions = await _control_permissions(session, user, device)
    return Permission.DEVICES_CONTROL in permissions


async def _credentials_read(
    session: AsyncSession, device: Device, *, reveal: bool
) -> Lp0CredentialsRead:
    row = await session.get(DeviceLp0Credentials, device.id)
    summary = credentials_summary(row)
    # an address claimed without keys (decision D338) is the device's identity alone
    address: str | None = (
        str(summary["dev_addr"])
        if summary["dev_addr"]
        else (await addresses_of(session, [device.id])).get(device.id)
    )
    read = Lp0CredentialsRead(
        dev_addr=address,
        keys_set=bool(summary["keys_set"]),
        set_at=summary["set_at"],
        source=summary["source"],
        readback=await _readback(session, device.id),
        frames_waiting=await _frames_waiting(session, address),
    )
    if reveal and row is not None:
        keys = await credentials_for(session, device.id)
        if keys is not None:
            read.app_s_key = keys.app_s_key.hex().upper()
            read.nwk_s_key = keys.nwk_s_key.hex().upper()
    return read


@router.get("/devices/{device_id}/lp0-credentials", response_model=Lp0CredentialsRead)
async def get_lp0_credentials(
    device_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
) -> Lp0CredentialsRead:
    """The device's LP0 address and keys: the keys for a caller who may set them, a viewer
    sees only that they are set."""
    device = await _visible_device(session, user, device_id)
    return await _credentials_read(session, device, reveal=await _may_set(session, user, device))


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
    on the offload station source; frames stored for it before are handed to the decoder.
    The answer carries the keys, since the caller may set them."""
    device = await _writable_device(session, user, device_id)
    source = "person"
    if not body.from_device and body.dev_addr and not body.app_s_key and not body.nwk_s_key:
        # the address alone (decision D338): the frames a card holds for it become the
        # device's and wait for the keys
        try:
            claimed = await claim_address(session, device, body.dev_addr)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
        except AddressTaken as taken:
            raise HTTPException(
                status.HTTP_409_CONFLICT, f"The address is held by {taken.device.name}"
            ) from None
        await record_audit(
            session,
            user=user,
            action="device.lp0_address_claimed",
            object_type="device",
            object_id=str(device.id),
            details={"dev_addr": claimed.identity.external_id, "frames_waiting": claimed.waiting},
        )
        await session.commit()
        queued = 0
        if claimed.waiting:
            queued = await queue_identity_reprocess(session, bus, claimed.identity)
        read = await _credentials_read(session, device, reveal=True)
        return Lp0CredentialsResult(**read.model_dump(), queued=queued)
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
    # the frames that wait for these keys: stored before the address had a device, or claimed
    # with the address alone and failed for want of keys (decision D338); none, and nothing
    # is published
    queued = await queue_identity_reprocess(session, bus, result.identity)
    read = await _credentials_read(session, device, reveal=True)
    return Lp0CredentialsResult(**read.model_dump(), queued=queued)


@router.post("/devices/{device_id}/lp0-credentials/walk", response_model=Lp0WalkResult)
async def walk_lp0_frames(
    device_id: uuid.UUID,
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> Lp0WalkResult:
    """Hand the frames of the device's LP0 address that wait, failed or unassigned, to the
    decoder's walk (decision D121), after a serial or the keys were corrected (Tim,
    2026-10-19). Nothing waits, and nothing is published."""
    device = await _writable_device(session, user, device_id)
    source_row = await lp0_source(session)
    identity = await session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.data_source_id == source_row.id,
            ExternalIdentity.device_id == device.id,
            ExternalIdentity.identity_type == "dev_addr",
        )
    )
    if identity is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The device has no LP0 address")
    queued = await queue_identity_reprocess(session, bus, identity)
    return Lp0WalkResult(queued=queued)


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


#: One file of an upload: its name, the card folder it came from ("" for a lone file), its bytes.
CardMember = tuple[str, str, bytes]


async def _read_card_upload(file: UploadFile) -> tuple[str, list[CardMember], list[SkippedMember]]:
    """The files in an upload of a station's card: the one `.jsonl`, or every station file of a
    zip of the card's `LOG_*` folders, with the members that are not station files skipped by
    name. Refuses an empty, oversized or unrecognised upload."""
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
    members: list[CardMember] = []
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
    return name, members, skipped


def _nothing_stored(skipped: list[SkippedMember]) -> HTTPException:
    return HTTPException(
        status.HTTP_422_UNPROCESSABLE_CONTENT,
        "; ".join(f"{s.name}: {s.reason}" for s in skipped[:5]),
    )


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
    name, members, skipped = await _read_card_upload(file)
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
        raise _nothing_stored(skipped)
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
        gateway_row = await session.scalar(
            select(Gateway).where(
                Gateway.data_source_id == source.id, Gateway.external_id == eui.lower()
            )
        )
        if gateway_row is not None:
            # set up from the Offload page: a station before its first card
            read.is_station = True
            read.mobile = (gateway_row.attributes or {}).get("mobility") == "mobile"
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
                    GatewayReception.source_event_ingested_at >= since,
                    GatewayReception.source_event_ingested_at <= until,
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


async def _project_device_ids(session: AsyncSession, context: ProjectContext) -> list[uuid.UUID]:
    """The devices assigned to the project now, the caller's visibility applied."""
    ids = set(
        await session.scalars(
            select(DeviceProjectAssignment.device_id).where(
                DeviceProjectAssignment.project_id == context.project.id,
                DeviceProjectAssignment.validity.op("@>")(utc_now()),
            )
        )
    )
    if context.visibility.limited:
        ids &= set(context.visibility.device_ids or ())
    return list(ids)


async def _current_entities(
    session: AsyncSession, device_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[uuid.UUID, str, str, str]]:
    """The entity each device tracks now: its id, its name, its type's key and icon key."""
    if not device_ids:
        return {}
    rows = (
        await session.execute(
            select(
                DeviceEntityAssignment.device_id,
                Entity.id,
                Entity.name,
                EntityType.key,
                EntityType.icon_key,
            )
            .join(Entity, Entity.id == DeviceEntityAssignment.entity_id)
            .join(EntityType, EntityType.id == Entity.entity_type_id)
            .where(
                DeviceEntityAssignment.device_id.in_(device_ids),
                DeviceEntityAssignment.validity.op("@>")(utc_now()),
            )
        )
    ).all()
    return {
        device_id: (entity_id, name, key, icon) for device_id, entity_id, name, key, icon in rows
    }


@router.post(
    "/projects/{project_id}/offload/stations",
    response_model=OffloadStationSetupResult,
    status_code=status.HTTP_201_CREATED,
)
async def set_up_offload_station(
    body: OffloadStationSetup,
    context: ProjectContext = Depends(require_permission(Permission.DEVICES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> OffloadStationSetupResult:
    """A device of the project becomes an offload station in one call (the Offload page's
    "Make an offload station", Tim, 2026-10-16), or a station missing a piece is completed:
    the entity (the one the device tracks today is kept; else the entity named, or a new one
    of the Offload station type, which needs `entities:write` as the device page's "Assign to
    entity" does), the place when given (a station does not move, decision D261), and the
    gateway row on the offload station source, linked to the device, so the station is listed
    before its first card. The station's EUI must be known, as its serial number or a DevEUI
    identity: the card's files are named after it. Calling it again changes nothing that is
    set already."""
    device = await get_or_404(session, Device, body.device_id, "Device")
    now = utc_now()
    attribution = await resolve_attribution(session, device.id, now)
    if attribution.project_id != context.project.id or not context.visibility.device_visible(
        device.id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Device not found in this project")
    eui = await device_eui(session, device)
    if eui is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"The DevEUI of {device.name} is not known: set it as the device's serial number "
            "first, since the station names its files after it",
        )
    entity_created = False
    entity_kept = attribution.entity_id is not None
    if attribution.entity_id is not None:
        entity = await get_or_404(session, Entity, attribution.entity_id, "Entity")
        if body.entity_id is not None and body.entity_id != entity.id:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{device.name} tracks {entity.name} today; release it on its device page first",
            )
    else:
        if body.entity_id is not None:
            entity = await _project_entity(session, context, body.entity_id)
        else:
            allowed = permissions_for(context.role, server_admin=context.user.is_superuser)
            if Permission.ENTITIES_WRITE not in allowed:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, "Creating an entity needs entities:write"
                )
            station_type = await session.scalar(
                select(EntityType).where(EntityType.key == STATION_TYPE_KEY)
            )
            if station_type is None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    "The Offload station entity type is missing from the catalogue",
                )
            entity = await _new_entity(
                session,
                context,
                EntityCreate(entity_type_id=station_type.id, name=body.entity_name or device.name),
            )
            entity_created = True
        session.add(
            DeviceEntityAssignment(
                device_id=device.id,
                entity_id=entity.id,
                validity=Range(now, None, bounds="[)"),
                reason="offload station",
                created_by_user_id=context.user.id,
            )
        )
        await flush_or_409(session, "Entity assignment")
    placed = False
    if body.latitude is not None and body.longitude is not None:
        await place_device(session, device, body.longitude, body.latitude, now)
        placed = True
    elif not entity_kept:
        # a device placed before it had an entity carries its place to it (decision D261)
        await place_entity_of(session, device.id, now)
    source = await lp0_source(session)
    gateway, gateway_created = await register_station_gateway(session, source, eui, device, now)
    # static by default (decision D261); mobile when asked (D336): the station travels and
    # reports its own position, so a place set by hand goes
    mobile = (gateway.attributes or {}).get("mobility") == "mobile"
    if body.mobile is not None and body.mobile != mobile:
        mobile = body.mobile
        gateway.attributes = {
            **(gateway.attributes or {}),
            "mobility": "mobile" if mobile else "static",
        }
        if mobile and device.static_geom is not None:
            await unplace_device(session, device, entity.id)
    await record_audit(
        session,
        user=context.user,
        action="offload_station.set_up",
        object_type="device",
        object_id=str(device.id),
        project_id=context.project.id,
        details={
            "station_eui": eui,
            "entity_id": str(entity.id),
            "entity_created": entity_created,
            "placed": placed,
            "mobile": mobile,
            "gateway_id": str(gateway.id),
            "gateway_created": gateway_created,
        },
    )
    await session.commit()
    return OffloadStationSetupResult(
        device_id=device.id,
        device_name=device.name,
        station_eui=eui,
        entity_id=entity.id,
        entity_name=entity.name,
        entity_created=entity_created,
        entity_kept=entity_kept,
        placed=placed,
        mobile=mobile,
        gateway_id=gateway.id,
        gateway_created=gateway_created,
    )


@router.post(
    "/projects/{project_id}/offload-files",
    response_model=OffloadUpload,
    status_code=status.HTTP_201_CREATED,
)
async def upload_project_offload_files(
    file: UploadFile,
    context: ProjectContext = Depends(require_permission(Permission.DEVICES_CONTROL)),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> OffloadUpload:
    """The files of one or more offload stations' SD cards, uploaded on the Offload page
    (Tim, 2026-10-18: the person who collected the cards should not have to find each
    station's page): one `.jsonl`, or a zip of `LOG_*` folders, every file put with the station
    its name carries, the EUI matched to a device of the project by serial number or DevEUI
    identity, as `GET /projects/{id}/offload` names the stations. A file of an EUI no device of
    the project has is skipped with that EUI, so the person sees which station is missing,
    and nothing is guessed; a file seen before is skipped as on the device page."""
    name, members, skipped = await _read_card_upload(file)
    visible = set(await _project_device_ids(session, context))
    stations: dict[str, Device | None] = {}
    rows: list[tuple[DeviceLogFile, Device]] = []
    unknown_stations: list[str] = []
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
        eui = (station_eui_from_name(member_name) or parsed.frames[0].station_eui).upper()
        if eui not in stations:
            device = await station_device(session, eui)
            stations[eui] = device if device is not None and device.id in visible else None
        station = stations[eui]
        if station is None:
            skipped.append(
                SkippedMember(
                    name=member_name, reason=f"no offload station of this project has EUI {eui}"
                )
            )
            if eui not in unknown_stations:
                unknown_stations.append(eui)
            continue
        try:
            row = await store_log_file(
                session,
                device=station,
                data=content,
                filename=member_name,
                channel=AcquisitionChannel.LP0,
                user_id=context.user.id,
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
        rows.append((row, station))
    if not rows and skipped and not unknown_stations:
        raise _nothing_stored(skipped)
    per_station: dict[str, list[str]] = {}
    for row, station in rows:
        per_station.setdefault(str(station.id), []).append(row.original_filename)
    await record_audit(
        session,
        user=context.user,
        action="offload_files.uploaded",
        object_type="project",
        object_id=str(context.project.id),
        project_id=context.project.id,
        details={
            "upload": name,
            "files": per_station,
            "skipped": [s.name for s in skipped],
        },
    )
    await session.commit()
    out: list[DeviceLogFileRead] = []
    for row, station in rows:
        await _publish(bus, row)
        read = DeviceLogFileRead.model_validate(row)
        read.device_name = station.name
        out.append(read)
    return OffloadUpload(files=out, skipped=skipped, unknown_stations=sorted(unknown_stations))


@router.get("/projects/{project_id}/offload", response_model=OffloadOverviewRead)
async def project_offload(
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> OffloadOverviewRead:
    """The Offload page (phase 42): the project's offload stations with what their cards
    brought and their own last report, the trackers with an LP0 address or frames (never the
    keys), the addresses the stations received that no device has, and how many devices of
    the project have no address yet. Every figure of the window covers the last 30 days."""
    device_ids = await _project_device_ids(session, context)
    if not device_ids:
        return OffloadOverviewRead(window_days=TRACKERS_WINDOW.days)
    devices = {
        d.id: d
        for d in (await session.scalars(select(Device).where(Device.id.in_(device_ids)))).all()
    }
    entities = await _current_entities(session, device_ids)
    source = await lp0_source(session)
    until = utc_now()
    since = until - TRACKERS_WINDOW

    # the stations: a device with card files, a gateway row of the source, a report of itself,
    # or an Offload station entity
    files = (
        await session.scalars(
            select(DeviceLogFile).where(
                DeviceLogFile.device_id.in_(device_ids),
                DeviceLogFile.acquisition_channel == AcquisitionChannel.LP0,
            )
        )
    ).all()
    gateways = (
        await session.scalars(
            select(Gateway).where(
                Gateway.data_source_id == source.id, Gateway.device_id.in_(device_ids)
            )
        )
    ).all()
    current_states = {
        c.device_id: c
        for c in (
            await session.scalars(
                select(DeviceCurrentState).where(DeviceCurrentState.device_id.in_(device_ids))
            )
        ).all()
    }
    # a device's own station report makes it a station only while it says it listens: every
    # RangerEdge with the LP0 firmware reports its card and radio, a tracker among them (Tim,
    # 2026-10-19: SP051830, a tracker whose flash log carried the report, was listed as a
    # station); a station that is quiet keeps its place through its gateway row or its entity
    states = {
        device_id: c
        for device_id, c in current_states.items()
        if isinstance((c.latest_state or {}).get("lp0_station"), dict)
        and ((c.latest_state or {})["lp0_station"].get("status") or {}).get("lp0_listening") is True
    }
    station_ids = {f.device_id for f in files} | {g.device_id for g in gateways if g.device_id}
    station_ids |= set(states)
    # a station set up and waiting for its first card: its entity says what it is
    station_ids |= {d for d, (_, _, key, _) in entities.items() if key == STATION_TYPE_KEY}
    station_ids &= set(devices)
    gateway_of = {g.device_id: g for g in gateways if g.device_id}
    eui_of: dict[uuid.UUID, str] = {}
    for device_id in station_ids:
        device = devices[device_id]
        eui = (device.serial_number or "").upper()
        if not eui and device_id in gateway_of:
            eui = gateway_of[device_id].external_id.upper()
        if not eui:
            eui = next(
                (
                    str(f.attributes.get("station_eui")).upper()
                    for f in files
                    if f.device_id == device_id and f.attributes.get("station_eui")
                ),
                "",
            )
        if eui:
            eui_of[device_id] = eui
    station_by_eui = {eui.lower(): device_id for device_id, eui in eui_of.items()}

    # what each station received in the window, and what each tracker was received by
    per_station = (
        {
            row.gateway_id: row
            for row in (
                await session.execute(
                    select(
                        GatewayReception.gateway_id,
                        func.count().label("receptions"),
                        func.count(func.distinct(GatewayReception.device_id)).label("trackers"),
                        func.max(GatewayReception.time).label("last"),
                    )
                    .where(
                        GatewayReception.data_source_id == source.id,
                        GatewayReception.gateway_id.in_(list(station_by_eui)),
                        GatewayReception.source_event_ingested_at >= since,
                        GatewayReception.source_event_ingested_at <= until,
                    )
                    .group_by(GatewayReception.gateway_id)
                )
            ).all()
        }
        if station_by_eui
        else {}
    )
    unknown_per_station: dict[str, int] = (
        {
            row.gateway_id: int(row.addresses)
            for row in (
                await session.execute(
                    select(
                        GatewayReception.gateway_id,
                        func.count(func.distinct(SourceEvent.external_id)).label("addresses"),
                    )
                    .join(
                        SourceEvent,
                        (SourceEvent.id == GatewayReception.source_event_id)
                        & (SourceEvent.ingested_at == GatewayReception.source_event_ingested_at),
                    )
                    .where(
                        GatewayReception.data_source_id == source.id,
                        GatewayReception.device_id.is_(None),
                        GatewayReception.gateway_id.in_(list(station_by_eui)),
                        GatewayReception.source_event_ingested_at >= since,
                        GatewayReception.source_event_ingested_at <= until,
                    )
                    .group_by(GatewayReception.gateway_id)
                )
            ).all()
        }
        if station_by_eui
        else {}
    )
    per_tracker = {
        row.device_id: row
        for row in (
            await session.execute(
                select(
                    GatewayReception.device_id,
                    func.count().label("receptions"),
                    func.count(func.distinct(GatewayReception.gateway_id)).label("stations"),
                    func.max(GatewayReception.time).label("last"),
                )
                .where(
                    GatewayReception.data_source_id == source.id,
                    GatewayReception.device_id.in_(device_ids),
                    GatewayReception.source_event_ingested_at >= since,
                    GatewayReception.source_event_ingested_at <= until,
                )
                .group_by(GatewayReception.device_id)
            )
        ).all()
    }
    last_station: dict[uuid.UUID, str] = {}
    if per_tracker:
        newest = (
            select(GatewayReception.device_id, GatewayReception.gateway_id)
            .where(
                GatewayReception.data_source_id == source.id,
                GatewayReception.device_id.in_(list(per_tracker)),
                GatewayReception.source_event_ingested_at >= since,
                GatewayReception.source_event_ingested_at <= until,
            )
            .distinct(GatewayReception.device_id)
            .order_by(GatewayReception.device_id, GatewayReception.time.desc())
        )
        last_station = {
            device_id: gateway_id for device_id, gateway_id in (await session.execute(newest)).all()
        }
    station_names = (
        {
            g.external_id: (g.device_id, g.name or g.external_id)
            for g in (
                await session.scalars(
                    select(Gateway).where(
                        Gateway.data_source_id == source.id,
                        Gateway.external_id.in_(list(set(last_station.values()))),
                    )
                )
            ).all()
        }
        if last_station
        else {}
    )

    stations: list[OffloadOverviewStation] = []
    for device_id in station_ids:
        device = devices[device_id]
        own = [f for f in files if f.device_id == device_id]
        station_eui: str | None = eui_of.get(device_id)
        received = per_station.get(station_eui.lower()) if station_eui else None
        report = states[device_id].latest_state["lp0_station"] if device_id in states else None
        status_bits = (report or {}).get("status") or {}
        counters = (report or {}).get("counters") or {}
        card_ok = lp0_sd_card_ok(status_bits)  # the decoder's reading, decision D345
        entity = entities.get(device_id)
        gateway_row = gateway_of.get(device_id)
        files_eui = next(
            (
                str(f.attributes.get("station_eui")).upper()
                for f in own
                if f.attributes.get("station_eui")
            ),
            gateway_row.external_id.upper() if gateway_row else None,
        )
        mobile = bool(gateway_row and (gateway_row.attributes or {}).get("mobility") == "mobile")
        current = current_states.get(device_id)
        location_at: datetime | None = None
        if mobile:
            # a mobile station is where it last reported itself (D336)
            location = geom_to_geojson(current.latest_position) if current else None
            location_at = current.latest_position_time if current and location else None
        else:
            location = geom_to_geojson(device.static_geom)
        stations.append(
            OffloadOverviewStation(
                device_id=device_id,
                device_name=device.name,
                station_eui=station_eui,
                files_eui=files_eui,
                entity_id=entity[0] if entity else None,
                entity_name=entity[1] if entity else None,
                gateway_id=gateway_row.id if gateway_row else None,
                mobile=mobile,
                has_location=location is not None,
                location=location,
                location_at=location_at,
                files=len(own),
                frames=sum(f.frames_total for f in own),
                frames_retained=sum(int(f.attributes.get("frames_retained") or 0) for f in own),
                last_upload_at=max((f.uploaded_at for f in own), default=None),
                trackers=int(received.trackers) if received else 0,
                unknown_addresses=unknown_per_station.get(station_eui.lower(), 0)
                if station_eui
                else 0,
                receptions=int(received.receptions) if received else 0,
                last_reception_at=received.last if received else None,
                card_ok=card_ok,
                sd_free_percent=(report or {}).get("sd_free_percent"),
                listening=status_bits.get("lp0_listening"),
                storage_pending=(report or {}).get("storage_pending"),
                visits_complete=counters.get("visits_complete"),
                state_time=states[device_id].latest_state_time if device_id in states else None,
            )
        )
    floor = datetime.min.replace(tzinfo=UTC)
    stations.sort(key=lambda s: s.last_reception_at or s.last_upload_at or floor, reverse=True)

    # the trackers: an address set, or frames received, stations apart
    credentials = {
        c.device_id: c
        for c in (
            await session.scalars(
                select(DeviceLp0Credentials).where(DeviceLp0Credentials.device_id.in_(device_ids))
            )
        ).all()
    }
    claimed_addresses = await addresses_of(session, device_ids)
    card_euis = await card_euis_of(session, device_ids)
    tracker_ids = (set(credentials) | set(per_tracker) | set(claimed_addresses)) - station_ids
    reported: dict[uuid.UUID, str] = {}
    for device_id in tracker_ids:
        readback = await _readback(session, device_id)
        if readback.dev_addr:
            reported[device_id] = readback.dev_addr
    trackers: list[OffloadOverviewTracker] = []
    for device_id in tracker_ids:
        tracker = devices.get(device_id)
        if tracker is None:
            continue
        row = credentials.get(device_id)
        got = per_tracker.get(device_id)
        station = station_names.get(last_station.get(device_id, ""), (None, None))
        entity = entities.get(device_id)
        current = current_states.get(device_id)
        trackers.append(
            OffloadOverviewTracker(
                device_id=device_id,
                device_name=tracker.name,
                entity_id=entity[0] if entity else None,
                entity_name=entity[1] if entity else None,
                entity_icon=entity[3] if entity else None,
                card_dev_eui=card_euis.get(device_id),
                serial_number=tracker.serial_number,
                last_position=geom_to_geojson(current.latest_position) if current else None,
                last_position_at=current.latest_position_time if current else None,
                dev_addr=row.dev_addr if row else claimed_addresses.get(device_id),
                keys_set=row is not None,
                source=row.source if row else None,
                set_at=row.set_at if row else None,
                reported_dev_addr=reported.get(device_id),
                last_f_cnt=row.last_f_cnt if row else None,
                last_frame_at=row.last_frame_at if row else None,
                receptions=int(got.receptions) if got else 0,
                stations=int(got.stations) if got else 0,
                last_reception_at=got.last if got else None,
                last_station_device_id=station[0],
                last_station_name=station[1],
            )
        )
    trackers.sort(key=lambda t: t.last_reception_at or t.set_at or floor, reverse=True)

    # the addresses the project's stations received that no device has
    unknown: list[OffloadUnknownAddress] = []
    if station_by_eui:
        seen = (
            await session.execute(
                select(
                    SourceEvent.external_id,
                    func.count().label("receptions"),
                    func.min(GatewayReception.time).label("first"),
                    func.max(GatewayReception.time).label("last"),
                    func.array_agg(func.distinct(GatewayReception.gateway_id)).label("gateways"),
                )
                .join(
                    SourceEvent,
                    (SourceEvent.id == GatewayReception.source_event_id)
                    & (SourceEvent.ingested_at == GatewayReception.source_event_ingested_at),
                )
                .where(
                    GatewayReception.data_source_id == source.id,
                    GatewayReception.device_id.is_(None),
                    GatewayReception.gateway_id.in_(list(station_by_eui)),
                )
                .group_by(SourceEvent.external_id)
                .order_by(func.max(GatewayReception.time).desc())
                .limit(MAX_TRACKERS)
            )
        ).all()
        identities = (
            {
                i.external_id: i
                for i in (
                    await session.scalars(
                        select(ExternalIdentity).where(
                            ExternalIdentity.data_source_id == source.id,
                            ExternalIdentity.external_id.in_([s.external_id for s in seen]),
                        )
                    )
                ).all()
            }
            if seen
            else {}
        )
        # the ports the frames carry in the clear (decision D341): a station's own status
        # report travels on port 23, a tracker's stored stream on port 29, so the page says what
        # an unknown device most likely is before anyone has its keys
        port_expr = SourceEvent.provider_metadata["f_port"].astext
        port_rows = (
            (
                await session.execute(
                    select(SourceEvent.external_id, port_expr, func.count())
                    .where(
                        SourceEvent.data_source_id == source.id,
                        SourceEvent.external_id.in_([s.external_id for s in seen]),
                    )
                    .group_by(SourceEvent.external_id, port_expr)
                )
            ).all()
            if seen
            else []
        )
        ports_of: dict[str, set[int]] = {}
        for external_id, port, _frames in port_rows:
            if port is not None and str(port).isdigit():
                ports_of.setdefault(external_id, set()).add(int(port))
        for s in seen:
            identity = identities.get(s.external_id)
            if identity is not None and identity.device_id is not None:
                continue  # linked since: the walk takes its receptions along
            ports = sorted(ports_of.get(s.external_id, set()))
            kind_hint = (
                "station"
                if ports == [STATION_REPORT_PORT]
                else "tracker"
                if STORED_STREAM_PORT in ports
                else None
            )
            name = (identity.attributes or {}).get("name") if identity is not None else None
            heard_by = sorted(
                {
                    devices[station_by_eui[g]].name
                    for g in (s.gateways or [])
                    if g in station_by_eui and station_by_eui[g] in devices
                }
            )
            unknown.append(
                OffloadUnknownAddress(
                    dev_addr=s.external_id,
                    dev_eui=_text(name) if name else None,
                    stations=heard_by,
                    ports=ports,
                    kind_hint=kind_hint,
                    receptions=int(s.receptions),
                    first_seen_at=s.first,
                    last_seen_at=s.last,
                )
            )

    without = len(set(devices) - set(credentials) - station_ids)
    return OffloadOverviewRead(
        window_days=TRACKERS_WINDOW.days,
        stations=stations,
        trackers=trackers,
        unknown=unknown,
        devices_without_address=without,
    )
