"""A Bluetooth tag: a device that only advertises and is never heard from directly (D257).

An EdgeTag on a rabbit, a beacon on a gate, a tag in a store. It has no uplink, no network and
no way of telling Protect anything. What is known about it is what other devices report of it:
a reader or a collar scans, hears the address the tag was programmed with, and that sighting is
a contact whose counterpart resolves to this device.

So the driver decodes nothing, on purpose. It exists because the platform's shape is right:
a tag is hardware, the animal wearing it is an entity, and a time-bounded assignment between
them means a tag can move to another animal without the history following it to the wrong one.
That is the same reason a collar is a device, and it costs nothing to reuse.

The device's `ble_mac` is the whole point of the row: it is what a scanner reports, and without
it a tag can be heard by everything and recognised by nothing.
"""

from typing import ClassVar

from shared.device_drivers.base import (
    DecodedRecords,
    HealthField,
    SourceEventData,
    TimestampSemantics,
)
from shared.enums import ErrorCode
from shared.trace import ApplicationError

COMPONENT = "driver.ble_tag"

#: A tag reports nothing of itself, so its health is what others have heard of it. `last_seen_at`
#: on the current state is moved by a contact that resolves to it, which is the only signal there
#: is that a tag is alive and in range of anything.
BLE_TAG_HEALTH: tuple[HealthField, ...] = ()


class BleTagDriver:
    key: ClassVar[str] = "ble_tag"
    label: ClassVar[str] = "Bluetooth tag"
    health: ClassVar[tuple[HealthField, ...]] = BLE_TAG_HEALTH
    capabilities: ClassVar[frozenset[str]] = frozenset({"ble_advertiser"})
    timestamp_semantics: ClassVar[dict[str, TimestampSemantics]] = {}
    #: Nothing: a tag never delivers, so no event type of any channel belongs to it.
    decodable_event_types: ClassVar[frozenset[str]] = frozenset()

    def decode(self, event: SourceEventData) -> DecodedRecords:
        """Never called in the ordinary way, since the driver decodes no event type. Reaching
        here means something delivered a message claiming to be from a tag, which is worth
        failing loudly over rather than quietly returning nothing."""
        raise ApplicationError(
            code=ErrorCode.PAYLOAD_DECODE_FAILED,
            message=(
                "a Bluetooth tag sends nothing of its own; what is known of it comes from the "
                "devices that hear it"
            ),
            component=COMPONENT,
            user_actionable=True,
            context={"event_type": event.event_type},
        )
