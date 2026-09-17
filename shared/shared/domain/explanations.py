"""What an event means, in plain words (Tim, 2026-09-15): one short explanation per event
type, and one per error flag of an OpenCollar status message, so a ranger reading the feed
knows what "ublox_fix" or "lr_join" is about. Pure; the API adds the text to every event it
serves."""

from __future__ import annotations

from typing import Any

from shared.i18n import translate

#: The error bits of the OpenCollar status message (research section 3.4) and the operation
#: byte's join error, in words.
ERROR_FLAGS: dict[str, str] = {
    "lr_module": (
        "The LoRa radio module (LR11xx) reported an error, so the device could not use its "
        "radio as it should. One occurrence usually clears by itself; a flag that stays on "
        "points at the radio hardware or its firmware."
    ),
    "ble": "The Bluetooth module reported an error. Positions and status are not affected.",
    "ublox": (
        "The GPS receiver (u-blox) did not answer as expected. The device keeps sending its "
        "status, but positions can be missing until the receiver recovers."
    ),
    "accelerometer": (
        "The accelerometer did not answer, so movement cannot be measured until it recovers."
    ),
    "battery": (
        "The battery is below the firmware's critical level. The device may reduce its work "
        "or stop sending; plan a battery change or check the charging."
    ),
    "ublox_fix": (
        "The GPS did not get a fix within the time allowed, so that attempt gave no position. "
        "Common under dense canopy, indoors, or when the device lies with its antenna down; "
        "when it persists, the sky view or the antenna is the problem."
    ),
    "flash": (
        "The flash memory reported an error. Records stored on the device may be delayed or "
        "lost until it recovers."
    ),
    "ublox_busy": "The GPS receiver was still busy with the previous attempt.",
    "lr_join": (
        "The device could not join the LoRaWAN network: no gateway answered its join request. "
        "It keeps trying and stores its records meanwhile; they arrive once it joins. Check "
        "the gateways near the device."
    ),
}

RESET_REASONS: dict[str, str] = {
    "watchdog": "the firmware stopped responding and the watchdog restarted it",
    "software": "the firmware restarted itself, as after a settings change or an update",
    "pin": "the reset pin or the power was cycled",
    "lockup": "the processor locked up and was reset",
}

EVENTS: dict[str, str] = {
    "device_error": (
        "The device's status message carries one or more error flags. Each flag is explained "
        "below; a flag that clears on the next status was a passing fault."
    ),
    "device_reset": (
        "The device started again: its uptime dropped back to zero. A single restart is "
        "harmless; repeated restarts point at a firmware or a power problem."
    ),
    "switch_activated": "The external switch on the device became active.",
    "switch_deactivated": "The external switch on the device became inactive.",
    "fence_measurement_failed": (
        "The fence monitor could not measure the fence voltage. Check the fence connection."
    ),
    "NO_DATA": (
        "Nothing has been received from this entity for the time the rule sets. The device may "
        "be out of network range, out of battery, or stored records are waiting for a "
        "connection; the delivery from the network may also have stopped."
    ),
    "BATTERY_LOW": (
        "The battery voltage fell below the rule's threshold. Plan a battery change or check "
        "the charging before the device stops sending."
    ),
    "POSSIBLE_IMMOBILITY": (
        "The device's accelerometer has not changed between status messages for the time the "
        "rule sets. The device may have dropped off, or the animal is not moving; check the "
        "last position and the movement line on the entity page."
    ),
    "GEOFENCE_EXIT": "The entity's position left the geofence named in the title.",
    "GEOFENCE_ENTER": "The entity's position entered the geofence named in the title.",
    "PROXIMITY": "The entity came within the distance the rule sets of the place or entity named.",
    "SPEED_LIMIT_VIOLATION": (
        "The speed between two positions was above the rule's limit. Speed is the average "
        "over the interval between the two fixes, not an instantaneous reading."
    ),
    "SYSTEM_WORKER_STALE": (
        "A background worker of the server has not reported for longer than allowed; the "
        "work it does (decoding, rules, exports, analyses) waits until it is back."
    ),
    "SYSTEM_DEAD_LETTERS": (
        "Messages on the server's bus failed repeatedly and were set aside. Nothing is lost, "
        "but a server admin should look at them under System health."
    ),
    "SYSTEM_STREAM_LAG": (
        "The server's workers are behind on their queues; data arrives later than usual "
        "until they catch up."
    ),
    "SYSTEM_BACKUP": (
        "The last backup or restore test did not succeed; a server admin should check it."
    ),
}


def explain_event(
    event_type: str, context: dict[str, Any] | None, language: str = "en"
) -> str | None:
    """The explanation of an event, with the flags or the reset reason it carries spelled
    out, in `language` (decision D240); None for a type without one (a custom rule's own
    type)."""
    base = EVENTS.get(event_type)
    if base is None:
        return None
    context = context or {}
    parts = [translate(base, language) or base]
    if event_type == "device_error":
        errors = context.get("errors")
        if isinstance(errors, list):
            for flag in errors:
                text = ERROR_FLAGS.get(str(flag))
                parts.append(
                    f"{flag}: {translate(text, language)}"
                    if text
                    else str(translate("{flag}: no explanation yet.", language)).format(flag=flag)
                )
    if event_type == "device_reset":
        reason = context.get("reset_reason")
        if isinstance(reason, str):
            words = [translate(RESET_REASONS.get(r.strip()), language) for r in reason.split(",")]
            known = [w for w in words if w]
            if known:
                lead = translate("The reason the device gives: ", language) or ""
                parts.append(lead + "; ".join(known) + ".")
    return " ".join(parts)
