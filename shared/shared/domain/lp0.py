"""What Protect knows of a device's LP0 offload (phase 42, decisions D319 to D324).

The tracker's side: its LP0 address and keys, set per device (`DeviceLp0Credentials`), the
address doubling as the device's identity on the built-in offload station source, so a frame
a station stored finds its device by the address in the clear and the pipeline then unwraps it
with the keys. The station's side: a RangerEdge whose EUI names the card's files and the
`gatewayEui` of every line; it is a gateway of the same source, linked to the device.
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.connectivity.adapters import lp0_station
from shared.connectivity.adapters.lp0_station.lorawan import Credentials
from shared.connectivity.base import GatewayUpdate
from shared.enums import ConnectivityStatus
from shared.ingest import apply_gateway_update, builtin_source
from shared.models import DataSource, Device, DeviceLp0Credentials, ExternalIdentity, Gateway
from shared.secrets import decrypt_json, encrypt_json
from shared.timeutil import utc_now

DEV_ADDR_DIGITS = 8
KEY_DIGITS = 32
#: `STATIONEUI_timestamp[_NNN].jsonl`, the station's EUI in sixteen hex digits.


class AddressTaken(Exception):
    def __init__(self, device: Device) -> None:
        super().__init__(f"the address is held by {device.name}")
        self.device = device


def normalise_dev_addr(text: str) -> str:
    """Eight hex digits as printed (big-endian), upper case; separators and spaces dropped.
    Raises `ValueError` for anything else."""
    digits = re.sub(r"[\s:_-]", "", text or "").upper()
    if len(digits) != DEV_ADDR_DIGITS or not re.fullmatch(r"[0-9A-F]+", digits):
        raise ValueError("a DevAddr is 8 hex digits")
    return digits


def parse_key(text: str) -> bytes:
    digits = re.sub(r"[\s:_-]", "", text or "")
    if len(digits) != KEY_DIGITS or not re.fullmatch(r"[0-9A-Fa-f]+", digits):
        raise ValueError("a session key is 32 hex digits")
    return bytes.fromhex(digits)


async def lp0_source(session: AsyncSession) -> DataSource:
    return await builtin_source(session, lp0_station.Lp0StationAdapter.key)


@dataclass(slots=True)
class CredentialsSet:
    row: DeviceLp0Credentials
    identity: ExternalIdentity
    #: The identity existed unlinked before (a card arrived first): its retained frames wait
    #: for the decoder's walk (decision D121).
    linked_waiting: bool
    previous_dev_addr: str | None


async def set_credentials(
    session: AsyncSession,
    device: Device,
    *,
    dev_addr: str,
    app_s_key: bytes,
    nwk_s_key: bytes,
    user_id: uuid.UUID | None,
    source: str = "person",
) -> CredentialsSet:
    """Write the device's address and keys and make the address its identity on the offload
    station source. An address another device holds is refused (`AddressTaken`); an identity
    of that address that was unknown so far is linked to the device."""
    address = normalise_dev_addr(dev_addr)
    other = await session.scalar(
        select(DeviceLp0Credentials).where(
            DeviceLp0Credentials.dev_addr == address, DeviceLp0Credentials.device_id != device.id
        )
    )
    if other is not None:
        holder = await session.get(Device, other.device_id)
        assert holder is not None
        raise AddressTaken(holder)
    row = await session.get(DeviceLp0Credentials, device.id)
    previous = row.dev_addr if row is not None else None
    now = utc_now()
    if row is None:
        row = DeviceLp0Credentials(device_id=device.id, dev_addr=address, set_at=now)
        session.add(row)
    row.dev_addr = address
    row.keys_encrypted = encrypt_json({"app_s_key": app_s_key.hex(), "nwk_s_key": nwk_s_key.hex()})
    row.source = source
    row.set_by_user_id = user_id
    row.set_at = now
    await session.flush()
    source_row = await lp0_source(session)
    if previous is not None and previous != address:
        await _unlink_identity(session, source_row, previous, device.id)
    identity = await session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.data_source_id == source_row.id,
            ExternalIdentity.external_id == address,
        )
    )
    linked_waiting = False
    if identity is None:
        identity = ExternalIdentity(
            data_source_id=source_row.id,
            device_id=device.id,
            external_id=address,
            identity_type=lp0_station.IDENTITY_TYPE,
            first_seen_at=now,
        )
        session.add(identity)
    else:
        linked_waiting = identity.device_id is None and (identity.event_count or 0) > 0
        identity.device_id = device.id
        identity.ignored = False
    await session.flush()
    return CredentialsSet(
        row=row, identity=identity, linked_waiting=linked_waiting, previous_dev_addr=previous
    )


@dataclass
class AddressClaimed:
    identity: ExternalIdentity
    waiting: int


async def claim_address(session: AsyncSession, device: Device, dev_addr: str) -> AddressClaimed:
    """Make an LP0 address the device's identity on the offload station source without its
    keys (decision D338): a tracker a card named before anyone set it up in Protect. The frames
    stored for the address are then the device's, failing with `CREDENTIALS_MISSING` until the
    keys arrive, and the address leaves "Addresses no device has". An address another device
    holds, by credentials or by identity, is refused (`AddressTaken`). Returns the identity and
    how many frames wait for the keys."""
    address = normalise_dev_addr(dev_addr)
    other = await session.scalar(
        select(DeviceLp0Credentials).where(
            DeviceLp0Credentials.dev_addr == address, DeviceLp0Credentials.device_id != device.id
        )
    )
    if other is not None:
        holder = await session.get(Device, other.device_id)
        assert holder is not None
        raise AddressTaken(holder)
    source_row = await lp0_source(session)
    identity = await session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.data_source_id == source_row.id,
            ExternalIdentity.external_id == address,
        )
    )
    now = utc_now()
    if identity is None:
        identity = ExternalIdentity(
            data_source_id=source_row.id,
            device_id=device.id,
            external_id=address,
            identity_type=lp0_station.IDENTITY_TYPE,
            first_seen_at=now,
        )
        session.add(identity)
    elif identity.device_id is not None and identity.device_id != device.id:
        holder = await session.get(Device, identity.device_id)
        assert holder is not None
        raise AddressTaken(holder)
    else:
        identity.device_id = device.id
        identity.ignored = False
    await session.flush()
    from shared.ingest import retained_events

    waiting = int(
        await session.scalar(select(func.count()).select_from(retained_events(identity).subquery()))
        or 0
    )
    return AddressClaimed(identity=identity, waiting=waiting)


async def addresses_of(session: AsyncSession, device_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """The LP0 address each device holds as an identity on the offload station source, keys
    or no keys: a device that claimed its address (D338) is a tracker with an address."""
    if not device_ids:
        return {}
    source_row = await lp0_source(session)
    rows = (
        await session.execute(
            select(ExternalIdentity.device_id, ExternalIdentity.external_id).where(
                ExternalIdentity.data_source_id == source_row.id,
                ExternalIdentity.identity_type == lp0_station.IDENTITY_TYPE,
                ExternalIdentity.device_id.in_(device_ids),
            )
        )
    ).all()
    return {device_id: external_id.upper() for device_id, external_id in rows}


async def card_euis_of(session: AsyncSession, device_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    """The tracker EUI a v5 card wrote beside each device's LP0 address, as the identity keeps
    it (`dev_eui` in its attributes): what the station says the hardware is."""
    if not device_ids:
        return {}
    source_row = await lp0_source(session)
    rows = (
        await session.execute(
            select(ExternalIdentity.device_id, ExternalIdentity.attributes).where(
                ExternalIdentity.data_source_id == source_row.id,
                ExternalIdentity.identity_type == lp0_station.IDENTITY_TYPE,
                ExternalIdentity.device_id.in_(device_ids),
            )
        )
    ).all()
    out: dict[uuid.UUID, str] = {}
    for device_id, attributes in rows:
        eui = (attributes or {}).get("dev_eui")
        if eui:
            out[device_id] = str(eui).upper()
    return out


async def _unlink_identity(
    session: AsyncSession, source: DataSource, dev_addr: str, device_id: uuid.UUID
) -> None:
    identity = await session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.data_source_id == source.id,
            ExternalIdentity.external_id == dev_addr,
            ExternalIdentity.device_id == device_id,
        )
    )
    if identity is not None:
        identity.device_id = None


async def clear_credentials(session: AsyncSession, device: Device) -> str | None:
    """Remove the device's address and keys; the identity of the address stays, unlinked, so
    the frames it carries are not lost but wait on Needs attention. Returns the address."""
    row = await session.get(DeviceLp0Credentials, device.id)
    if row is None:
        return None
    address = row.dev_addr
    await session.delete(row)
    await _unlink_identity(session, await lp0_source(session), address, device.id)
    await session.flush()
    return address


async def remember_counter(
    session: AsyncSession, device_id: uuid.UUID, f_cnt: int, received_at: datetime | None
) -> None:
    """Keep the newest verified 32-bit counter on the device's credentials, so the next
    frame's 16 bits are read in the right half (a LoRaWAN receiver's rollover rule)."""
    row = await session.get(DeviceLp0Credentials, device_id)
    if row is None:
        return
    if row.last_f_cnt is None or f_cnt > row.last_f_cnt:
        row.last_f_cnt = f_cnt
        row.last_frame_at = received_at


async def last_counter(session: AsyncSession, device_id: uuid.UUID) -> int | None:
    row = await session.get(DeviceLp0Credentials, device_id)
    return row.last_f_cnt if row is not None else None


async def credentials_for(session: AsyncSession, device_id: uuid.UUID) -> Credentials | None:
    row = await session.get(DeviceLp0Credentials, device_id)
    if row is None:
        return None
    keys = decrypt_json(row.keys_encrypted)
    return Credentials(
        dev_addr=row.dev_addr,
        app_s_key=bytes.fromhex(str(keys["app_s_key"])),
        nwk_s_key=bytes.fromhex(str(keys["nwk_s_key"])),
    )


def keys_from_readback(settings: dict[str, object]) -> tuple[str, bytes, bytes] | None:
    """The address and keys from a device's own settings readback (`lp0_dev_addr`,
    `lp0_app_key`, `lp0_network_key` as the settings table holds them: a hex string or a list
    of bytes), or None when any of the three is missing."""
    try:
        address = normalise_dev_addr(_hex(settings.get("lp0_dev_addr")))
        app = parse_key(_hex(settings.get("lp0_app_key")))
        nwk = parse_key(_hex(settings.get("lp0_network_key")))
    except (ValueError, TypeError):
        return None
    return address, app, nwk


def _hex(value: object) -> str:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, list):
        return bytes(int(v) for v in value).hex()
    if isinstance(value, dict) and "hex" in value:
        return str(value["hex"])
    return str(value) if value is not None else ""


async def ensure_station_gateway(
    session: AsyncSession,
    source: DataSource,
    station_eui: str,
    device: Device | None,
    now: datetime,
) -> Gateway:
    """The station as a gateway of the offload source (decision D319), named after and linked
    to its device when the EUI is a device of ours."""
    gateway = await apply_gateway_update(
        session,
        source.id,
        GatewayUpdate(
            gateway_id=station_eui.lower(),
            name=device.name if device is not None else None,
            seen_at=now,
            attributes={"kind": "offload_station"},
        ),
        now,
    )
    if device is not None and gateway.device_id != device.id:
        gateway.device_id = device.id
    return gateway


async def register_station_gateway(
    session: AsyncSession, source: DataSource, station_eui: str, device: Device, now: datetime
) -> tuple[Gateway, bool]:
    """The station's gateway row made by hand before any card (the Offload page's setup, Tim,
    2026-10-16), so the station is listed, on the Gateways page and in the coverage layer from
    the moment it is set up and not from its first card. Nothing has been seen, so the row says
    so: `first_seen_at` and `last_seen_at` stay empty until a card's first file stamps them
    through `ensure_station_gateway`. A row that exists is linked to the device and named after
    it when it has no name of its own. Returns the row and whether it was made here."""
    external_id = station_eui.lower()
    gateway = await session.scalar(
        select(Gateway).where(
            Gateway.data_source_id == source.id, Gateway.external_id == external_id
        )
    )
    created = gateway is None
    if gateway is None:
        gateway = Gateway(
            data_source_id=source.id,
            external_id=external_id,
            status=ConnectivityStatus.UNKNOWN,
            stats={},
            attributes={},
        )
        session.add(gateway)
    gateway.device_id = device.id
    if not gateway.name or gateway.name.lower() == external_id:
        gateway.name = device.name
    gateway.attributes = {**(gateway.attributes or {}), "kind": "offload_station"}
    await session.flush()
    return gateway, created


async def device_eui(session: AsyncSession, device: Device) -> str | None:
    """The DevEUI a device is known by: its serial when that is sixteen hex digits (an
    OpenCollar's serial is its DevEUI, decision D101), else a `dev_eui` identity of the device
    on any source. None when neither is known."""
    serial = (device.serial_number or "").strip().upper()
    if re.fullmatch(r"[0-9A-F]{16}", serial):
        return serial
    identity = await session.scalar(
        select(ExternalIdentity.external_id).where(
            ExternalIdentity.device_id == device.id, ExternalIdentity.identity_type == "dev_eui"
        )
    )
    return identity.upper() if identity else None


async def station_device(session: AsyncSession, station_eui: str) -> Device | None:
    """The device a station EUI names: by serial number (an OpenCollar's serial is its DevEUI,
    decision D101) or by a `dev_eui` identity on any source."""
    eui = station_eui.upper()
    device = await session.scalar(select(Device).where(Device.serial_number == eui))
    if device is not None:
        return device
    identity = await session.scalar(
        select(ExternalIdentity).where(
            ExternalIdentity.identity_type == "dev_eui",
            ExternalIdentity.external_id.ilike(eui),
            ExternalIdentity.device_id.is_not(None),
        )
    )
    return await session.get(Device, identity.device_id) if identity is not None else None


def credentials_summary(row: DeviceLp0Credentials | None) -> dict[str, object]:
    """What the API tells everyone about a device's credentials: the address and that keys
    are set; the keys themselves go to those who may set them (the router decides)."""
    if row is None:
        return {"dev_addr": None, "keys_set": False, "set_at": None, "source": None}
    return {
        "dev_addr": row.dev_addr,
        "keys_set": True,
        "set_at": row.set_at,
        "source": row.source,
    }


__all__ = [
    "AddressTaken",
    "Credentials",
    "CredentialsSet",
    "clear_credentials",
    "credentials_for",
    "credentials_summary",
    "device_eui",
    "ensure_station_gateway",
    "keys_from_readback",
    "last_counter",
    "lp0_source",
    "normalise_dev_addr",
    "parse_key",
    "register_station_gateway",
    "remember_counter",
    "set_credentials",
    "station_device",
]
