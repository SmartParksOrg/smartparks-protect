"""A device made inside a project (decision D326, Tim, 2026-10-16): project admins onboard
their own hardware, stations and trackers alike, without a server admin. The device is a server
level row as every device is (architecture 6), assigned to the project from the moment it is
made; a RangerEdge or a tracker read over Bluetooth in the browser brings its DevEUI as serial
and its LP0 credentials with it, saved in the same call."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.dialects.postgresql import Range
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.bus import get_bus
from protect_api.crud import flush_or_409, get_or_404
from protect_api.deps import ProjectContext, require_permission
from protect_api.device_reads import with_state
from protect_api.schemas.domain import DeviceRead, ProjectDeviceCreate
from protect_api.serial import SERIAL_FROM_IDENTITY
from shared.bus import RedisStreamsBus
from shared.database import get_session
from shared.domain.lp0 import AddressTaken, claim_address, parse_key, set_credentials
from shared.ingest import queue_identity_reprocess
from shared.models import Device, DeviceProjectAssignment, DeviceType
from shared.permissions import Permission
from shared.timeutil import utc_now

router = APIRouter(prefix="/projects/{project_id}/devices", tags=["devices"])


@router.post("", response_model=DeviceRead, status_code=status.HTTP_201_CREATED)
async def create_project_device(
    body: ProjectDeviceCreate,
    context: ProjectContext = Depends(require_permission(Permission.DEVICES_WRITE)),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> DeviceRead:
    """Create a device and assign it to this project from now, in one call (decision D326):
    the Offload page's "Add a device", by hand or from a Bluetooth read of the hardware. For a
    driver whose serial is the DevEUI the serial is kept upper case (decision D101). With `lp0`
    the device's LP0 address and keys are set at once, as the LP0 offload card would; an address
    another device holds is refused with that device's name. No attribution job: a device made
    now has no records yet."""
    device_type = await get_or_404(session, DeviceType, body.device_type_id, "Device type")
    values = body.model_dump(exclude={"lp0"})
    serial = (values.get("serial_number") or "").strip() or None
    if serial and device_type.driver_key in SERIAL_FROM_IDENTITY:
        serial = serial.upper()
    values["serial_number"] = serial
    device = Device(**values)
    session.add(device)
    await flush_or_409(session, "Device")
    now = utc_now()
    assignment = DeviceProjectAssignment(
        device_id=device.id,
        project_id=context.project.id,
        validity=Range(now, None, bounds="[)"),
        reason="created in the project",
        created_by_user_id=context.user.id,
    )
    session.add(assignment)
    await flush_or_409(session, "Project assignment")
    await record_audit(
        session,
        user=context.user,
        action="device.created",
        object_type="device",
        object_id=str(device.id),
        project_id=context.project.id,
        details={"name": device.name, "serial_number": serial, "in_project": True},
    )
    await record_audit(
        session,
        user=context.user,
        action="project_assignment.created",
        object_type="device_project_assignment",
        object_id=str(assignment.id),
        project_id=context.project.id,
        details={"device_id": str(device.id), "valid_from": now.isoformat()},
    )
    claimed = None
    if body.lp0 is not None:
        try:
            if body.lp0.app_s_key is not None and body.lp0.nwk_s_key is not None:
                await set_credentials(
                    session,
                    device,
                    dev_addr=body.lp0.dev_addr,
                    app_s_key=parse_key(body.lp0.app_s_key),
                    nwk_s_key=parse_key(body.lp0.nwk_s_key),
                    user_id=context.user.id,
                    source=body.lp0.source,
                )
            else:
                # the address alone (decision D338): a tracker a card named before anyone set
                # it up; its frames become the device's and wait for the keys
                claimed = await claim_address(session, device, body.lp0.dev_addr)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
        except AddressTaken as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"The LP0 address is held by {exc.device.name} already",
            ) from exc
        await record_audit(
            session,
            user=context.user,
            action="device.lp0_credentials_set"
            if claimed is None
            else "device.lp0_address_claimed",
            object_type="device",
            object_id=str(device.id),
            project_id=context.project.id,
            details={
                "dev_addr": body.lp0.dev_addr.upper(),
                "source": body.lp0.source,
                **({"frames_waiting": claimed.waiting} if claimed is not None else {}),
            },
        )
    await session.commit()
    if claimed is not None and claimed.waiting:
        # the frames a station stored for the address are the device's now: the walk gives
        # them to it, each failing plainly until the keys are set (CREDENTIALS_MISSING)
        await queue_identity_reprocess(session, bus, claimed.identity)
    await session.refresh(device)
    return (await with_state(session, [device]))[0]
