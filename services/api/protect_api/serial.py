"""The manufacturer's serial of a device (decision D101): for OpenCollar it is the DevEUI, so
the first LoRaWAN identity fills an empty serial. Other drivers keep the field as entered."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models import Device, DeviceType, ExternalIdentity

SERIAL_FROM_IDENTITY = {"opencollar": "dev_eui"}


async def fill_serial_from_identity(
    session: AsyncSession, device: Device, identity: ExternalIdentity
) -> bool:
    """Set the device's serial from the identity when the driver says the two are the same
    and the serial is empty; False when nothing changed (also when another device already
    carries that serial, since serials are unique)."""
    if device.serial_number:
        return False
    device_type = await session.get(DeviceType, device.device_type_id)
    wanted = SERIAL_FROM_IDENTITY.get(device_type.driver_key) if device_type else None
    if wanted is None or identity.identity_type != wanted:
        return False
    serial = identity.external_id.upper()
    taken: uuid.UUID | None = await session.scalar(
        select(Device.id).where(Device.serial_number == serial, Device.id != device.id)
    )
    if taken is not None:
        return False
    device.serial_number = serial
    return True
