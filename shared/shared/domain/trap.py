"""A trap from the external switch of a TrapEdge (phase 32, decision D266).

A switch is a switch: whether "active" means the door is closed depends on how the magnet and
the reed contact were mounted, so the device carries the answer as an attribute. The decoder
turns each `switch_active` measurement of a device on a Trap entity into a `trap_triggered`
measurement, and a change against the newest one into an event: closed is a warning, because
somebody has to go and look; opened is information. Pure: the decoder supplies what it knows.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from shared.device_drivers.base import DecodedEvent, DecodedMeasurement, DecodedRecords
from shared.enums import Severity

#: The device attribute that says which switch state means the trap is closed.
TRAP_ATTRIBUTE = "trap_closed_when_active"
#: The entity type a trap is (shared/catalog/entity_types.py).
TRAP_ENTITY_TYPE = "trap"
TRAP_METRIC = "trap_triggered"
TRAP_CLOSED_EVENT = "TRAP_CLOSED"
TRAP_OPENED_EVENT = "TRAP_OPENED"
TRAP_CLOSED_TITLE = "Trap {entity} closed"
TRAP_OPENED_TITLE = "Trap {entity} opened"


def closed_when_active(attributes: dict[str, Any] | None) -> bool:
    """The device's wiring: True unless somebody said the contact opens when the door shuts."""
    value = (attributes or {}).get(TRAP_ATTRIBUTE)
    return True if value is None else bool(value)


def previous_closed(latest_measurements: dict[str, Any] | None) -> bool | None:
    """Whether the device's newest trap reading said closed, from its current state."""
    entry = (latest_measurements or {}).get(TRAP_METRIC)
    if not isinstance(entry, dict) or not isinstance(entry.get("value"), bool | int | float):
        return None
    return bool(entry["value"])


def derive_trap(
    records: DecodedRecords,
    *,
    entity_name: str,
    wiring_closed_when_active: bool,
    was_closed: bool | None,
) -> None:
    """Add the trap readings and events the switch measurements imply, in time order."""
    switches = sorted(
        (m for m in records.measurements if m.metric_key == "switch_active"),
        key=lambda m: m.time,
    )
    last = was_closed
    for reading in switches:
        if not isinstance(reading.value, bool | int | float):
            continue
        closed = bool(reading.value) == wiring_closed_when_active
        records.measurements.append(
            DecodedMeasurement(
                time=reading.time,
                metric_key=TRAP_METRIC,
                value=closed,
                record_type=reading.record_type,
            )
        )
        if (last is not None and closed != last) or (last is None and closed):
            records.events.append(
                DecodedEvent(
                    time=reading.time,
                    event_type=TRAP_CLOSED_EVENT if closed else TRAP_OPENED_EVENT,
                    title=(TRAP_CLOSED_TITLE if closed else TRAP_OPENED_TITLE).format(
                        entity=entity_name
                    ),
                    severity=Severity.WARNING if closed else Severity.INFO,
                    context={"closed": closed},
                )
            )
        last = closed


def trap_titles() -> Iterable[str]:
    """The fixed texts of the trap events, for the translation catalogue's test."""
    return (TRAP_CLOSED_TITLE, TRAP_OPENED_TITLE)
