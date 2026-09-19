"""Turning a sighting into a contact (decisions D252 to D254).

A device reports three octets of a neighbour's Bluetooth address. That is not an identity: it is
a fragment, and a fragment can belong to nobody we know or to more than one device we know. This
module decides which, once, on the way in, so that no later reader has to guess and every reader
sees the same answer.

The three octets are the *last* three of an address as it is printed, so a device whose address
is known resolves when its address ends with them (`shared.device_drivers.opencollar.scan_suffix`
says the same thing from the other side).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.enums import ContactResolution
from shared.models import Device, DeviceProjectAssignment

#: How many octets of an address a scan carries, and so the most that can ever be matched.
ADDRESS_OCTETS = 3


def normalise(address: str) -> str:
    """A sighting's address as it is stored and compared: lowercase, zero padded, colon joined."""
    parts = [part.strip().rjust(2, "0").lower() for part in address.split(":") if part.strip()]
    return ":".join(parts[-ADDRESS_OCTETS:])


def suffix_of(mac: str | None) -> str | None:
    """What a neighbour's scan of the device with this address would report."""
    if not mac:
        return None
    parts = mac.lower().split(":")
    return ":".join(parts[-ADDRESS_OCTETS:]) if len(parts) >= ADDRESS_OCTETS else None


@dataclass(slots=True)
class Resolution:
    """What a sighting's address was found to mean."""

    resolution: str
    device_id: uuid.UUID | None = None
    candidates: list[uuid.UUID] = field(default_factory=list)


@dataclass(slots=True)
class Resolver:
    """The addresses of the devices a project's contacts may resolve to, read once per delivery.

    Scoped to the project, not the server: three octets are unique enough among a few hundred
    collars and not among tens of thousands, and a contact between two projects' animals is not a
    thing this platform claims to know about. A project with no devices resolves nothing, which
    is the honest answer rather than reaching wider to find one.
    """

    by_suffix: dict[str, list[uuid.UUID]]

    def resolve(self, address: str, observer: uuid.UUID) -> Resolution:
        # a device never reports itself, but a stale address on another row could collide with
        # the observer's own; leaving it out keeps a device from meeting itself
        candidates = [d for d in self.by_suffix.get(normalise(address), []) if d != observer]
        if not candidates:
            return Resolution(ContactResolution.UNKNOWN)
        if len(candidates) > 1:
            return Resolution(ContactResolution.AMBIGUOUS, candidates=sorted(candidates, key=str))
        return Resolution(ContactResolution.RESOLVED, device_id=candidates[0])


async def resolver_for(session: AsyncSession, project_id: uuid.UUID | None) -> Resolver:
    """The resolver for one project: every device assigned to it at some point whose address is
    known. Devices come and go from a project, so the assignment is not narrowed to today: a
    contact is read against the fleet the project has had, and its own time decides attribution."""
    if project_id is None:
        return Resolver(by_suffix={})
    rows = await session.execute(
        select(Device.id, Device.ble_mac)
        .join(DeviceProjectAssignment, DeviceProjectAssignment.device_id == Device.id)
        .where(DeviceProjectAssignment.project_id == project_id, Device.ble_mac.isnot(None))
        .distinct()
    )
    by_suffix: dict[str, list[uuid.UUID]] = {}
    for device_id, mac in rows:
        key = suffix_of(mac)
        if key:
            by_suffix.setdefault(key, []).append(device_id)
    return Resolver(by_suffix=by_suffix)


async def resolve_waiting(
    session: AsyncSession, device: Device, *, previous: str | None = None
) -> int:
    """Give the contacts that were waiting for this device's address the device they meant.

    A collar is often seen before anyone asks it its own address, and those sightings are stored
    as unknown neighbours (decision D253). When the address arrives they are no longer unknown,
    and nothing would otherwise revisit them: an analysis run months later would read "never
    met" from rows that hold the answer. So setting an address repairs its own past, in the
    projects the device has belonged to, and only for the exact octets a scan of it would show.

    A second device sharing those octets makes both readings ambiguous rather than resolved
    (decision D254), including any that had already resolved to the other one. `previous` is
    the address the device had before, when it was changed or cleared: the rows that named it
    are read again too, so a corrected address takes its wrong contacts with it instead of
    leaving them resolved to a device that never had that address. Returns how many rows
    changed."""
    from shared.models import DeviceContact

    suffixes = {s for s in (suffix_of(device.ble_mac), suffix_of(previous)) if s is not None}
    if not suffixes:
        return 0
    projects = list(
        await session.scalars(
            select(DeviceProjectAssignment.project_id)
            .where(DeviceProjectAssignment.device_id == device.id)
            .distinct()
        )
    )
    if not projects:
        return 0
    changed = 0
    for project_id in projects:
        resolver = await resolver_for(session, project_id)
        rows = (
            await session.scalars(
                select(DeviceContact).where(
                    DeviceContact.project_id == project_id,
                    DeviceContact.address.in_(suffixes),
                )
            )
        ).all()
        for row in rows:
            found = resolver.resolve(row.address, row.device_id)
            entity_id = await _worn_by(session, found.device_id, row.time)
            unchanged = (
                row.resolution == found.resolution
                and row.contact_device_id == found.device_id
                and row.contact_entity_id == entity_id
            )
            if unchanged:
                continue
            row.resolution = found.resolution
            row.contact_device_id = found.device_id
            # and what that device was carrying then, which is what a pair of animals is made of
            row.contact_entity_id = entity_id
            row.candidates = [str(c) for c in found.candidates] or None
            changed += 1
    return changed


async def _worn_by(
    session: AsyncSession, device_id: uuid.UUID | None, when: datetime
) -> uuid.UUID | None:
    """The entity a device was on at a moment, or none. Attribution at the record's own time
    (decision D103): a collar that changed animals last week met whoever wore it then."""
    if device_id is None:
        return None
    from shared.domain.assignments import resolve_attribution

    return (await resolve_attribution(session, device_id, when)).entity_id


async def unresolved_count(session: AsyncSession, device_id: uuid.UUID) -> int:
    """How many of a device's contacts are waiting for an address to become known. A device whose
    address arrives later leaves older contacts unresolved, and nothing fixes that on its own."""
    from shared.models import DeviceContact

    return int(
        await session.scalar(
            select(func.count())
            .select_from(DeviceContact)
            .where(
                DeviceContact.device_id == device_id,
                DeviceContact.resolution == ContactResolution.UNKNOWN,
            )
        )
        or 0
    )


#: The scan settings that decide whether a device could report a contact at all (D228 to D231).
SCAN_SETTINGS = ("ble_scan_interval", "ble_scan_aggregated_interval", "ble_scan_filter")
#: What `ble_scan_filter` means, from the firmware (research 3.7).
SCAN_FILTERS = {
    0: "every device",
    1: "Smart Parks devices",
    2: "one manufacturer",
    3: "phones",
}


@dataclass(slots=True)
class Scanning:
    """Whether a device was looking, and for what.

    Without this a contact list cannot be read: no rows means "they never met" only if the
    device was scanning, and both intervals default to 0, which is off. The filter matters as
    much, since the default looks only for Smart Parks devices and a count under it means
    something different from a count that included every phone that walked past."""

    enabled: bool
    interval_s: float | None = None
    aggregated_interval_s: float | None = None
    filter_key: int | None = None
    filter_label: str | None = None
    known: bool = False


async def scanning_of(session: AsyncSession, device_id: uuid.UUID) -> Scanning:
    """What the device's settings say about its Bluetooth scanning, as far as Protect knows."""
    from shared.domain.device_settings import known_settings

    rows = await known_settings(session, device_id)
    values: dict[str, float] = {}
    for name in SCAN_SETTINGS:
        row = rows.get(name)
        if row is not None and isinstance(row.value, int | float):
            values[name] = float(row.value)
    if not values:
        return Scanning(enabled=False, known=False)
    single = values.get("ble_scan_interval")
    aggregated = values.get("ble_scan_aggregated_interval")
    chosen = values.get("ble_scan_filter")
    key = int(chosen) if chosen is not None else None
    return Scanning(
        enabled=bool(single) or bool(aggregated),
        interval_s=single,
        aggregated_interval_s=aggregated,
        filter_key=key,
        filter_label=SCAN_FILTERS.get(key) if key is not None else None,
        known=True,
    )


#: The filter value that watches for phones and other human-worn Bluetooth devices.
PHONE_FILTER = 3
#: The event a sighting under that filter raises, and the metric a rule can threshold on.
HUMAN_PRESENCE_EVENT = "human_presence"
HUMAN_PRESENCE_METRIC = "human_presence"
#: The event's title and its two descriptions, fixed texts the translation layer knows (D240).
HUMAN_PRESENCE_TITLE = "Human presence"
HUMAN_PRESENCE_ONE = "{device} heard {n} human-worn Bluetooth device"
HUMAN_PRESENCE_MANY = "{device} heard {n} human-worn Bluetooth devices"
#: Carried in the context of every such event, because it is the whole point of decision D260.
HUMAN_PRESENCE_NOTE = (
    "A phone changes its Bluetooth address every few minutes, so these sightings are presence "
    "in a window and never an identity, and the number of addresses is not a number of people."
)


def human_presence_description(device_name: str, addresses: int) -> str:
    """What the event says: the reader and how many addresses it heard, never who."""
    template = HUMAN_PRESENCE_ONE if addresses == 1 else HUMAN_PRESENCE_MANY
    return template.format(device=device_name, n=addresses)


def watches_for_people(scanning: Scanning) -> bool:
    """Whether what this device reports is people rather than devices Protect could name.

    Only a device Protect knows the filter of: an unknown filter is not assumed to be anything,
    because guessing wrong in either direction is worse than saying nothing. Under the phone
    filter a sighting is never resolved to a device and never moves one (decision D260); it
    could only ever resolve by coincidence, since a phone's advertised address is random.
    """
    return scanning.known and scanning.filter_key == PHONE_FILTER
