"""OpenCollar Edge driver (RangerEdge, RhinoEdge, CollarEdge, ElephantEdge, WisentEdge, FreeEdge,
Fence Monitor). Protocol from the public firmware (7.3.0) and its decoder, see
`docs/devices/opencollar-protocol-research.md` and `docs/devices/opencollar.md`.

Every uplink is `[msg_id][len][data]` on an FPort that selects the message type, little-endian
integers. Two exceptions: FPort 29 (flash log) is a plain concatenation of stored records
`[port][msg_id][len][data][store timestamp]`, and FPorts 3 and 30 are TLV lists without a
message id.

Timestamp semantics: GNSS records carry the fix time from the u-blox receiver and that is their
canonical time, also when they arrive days later inside a flash log or as a port 16 resend. That
is what makes the same fix delivered three times one position (ADR 0008). Status, fence, switch
and flash status messages carry no clock of their own: on the air their time is the network
receive time; inside a flash log it is the store timestamp of the record.
"""

import struct
from datetime import UTC, datetime
from typing import Any, ClassVar

from shared.control.actions import ControlAction
from shared.device_drivers.base import (
    DEFAULT_DECODABLE_EVENT_TYPES,
    DecodedEvent,
    DecodedMeasurement,
    DecodedPosition,
    DecodedRecords,
    DecodedState,
    SourceEventData,
    TimestampSemantics,
)
from shared.device_drivers.opencollar.control import CONTROL_ACTIONS
from shared.enums import ErrorCode, Severity
from shared.trace import ApplicationError

DECODER_VERSION = "fw7.3.0"
COMPONENT = "driver.opencollar"
MIN_VALID_UNIX = 1_000_000_000  # 2001; the firmware's init_time default is 2020

PORT_POSITION = 2
PORT_SETTINGS = 3
PORT_STATUS = 4
PORT_FENCE = 12
PORT_SHORT_POSITION = 13
PORT_FLASH_STATUS = 14
PORT_RESEND_POSITION = 16
PORT_TIMESTAMP = 18
PORT_SWITCH_CHANGE = 19
PORT_SWITCH_STATUS = 20
PORT_FLASH_LOG = 29
PORT_VALUES = 30
PORT_MESSAGES = 31

# msg_id and fixed data length per port; None means variable length.
KNOWN_PORTS: dict[int, tuple[int, int | None]] = {
    1: (0xF1, None),
    PORT_POSITION: (0xF2, 30),
    PORT_STATUS: (0xF4, 14),
    5: (0xF5, None),
    6: (0xF7, None),
    7: (0xF9, None),
    9: (0xF6, None),
    10: (0xF8, None),
    11: (0xFA, None),
    PORT_FENCE: (0x92, 6),
    PORT_SHORT_POSITION: (0x93, 14),
    PORT_FLASH_STATUS: (0x94, 5),
    15: (0xFC, None),
    PORT_RESEND_POSITION: (0x95, 14),
    PORT_TIMESTAMP: (0x97, 4),
    PORT_SWITCH_CHANGE: (0x98, 5),
    PORT_SWITCH_STATUS: (0x99, 5),
    21: (0x9A, None),
    27: (0x91, None),
    28: (0x90, None),
}
NOT_CANONICAL_PORTS = {1, 5, 6, 7, 9, 10, 11, 15, 21, 27, 28}

HARDWARE_TYPES = {
    1: "rhinoedge",
    2: "elephantedge",
    3: "wisentedge",
    4: "cattracker",
    5: "rangeredge",
    6: "rhinopuck",
    7: "rhinopuck35",
    8: "collaredge",
    9: "freeedge",
}
FIRMWARE_TYPES = {
    0: "default",
    1: "rhinoedge",
    2: "elephantedge",
    3: "wisentedge",
    4: "cattracker",
    5: "rangeredge",
    6: "rhinopuck",
    7: "scanneredge",
    8: "collaredge",
    9: "freeedge",
    10: "fenceedge",
    11: "horseedge",
    12: "collaredgepico",
    13: "collaredgenano",
    14: "baboonedge",
    15: "pangolinedge",
}
FENCE_RESULTS = {
    0: "ok",
    1: "power_up_failed",
    2: "no_pulse_free_interval",
    3: "adc_error",
    4: "other",
}


def _fail(message: str, **context: Any) -> ApplicationError:
    return ApplicationError(
        code=ErrorCode.PAYLOAD_DECODE_FAILED,
        message=message,
        component=COMPONENT,
        user_actionable=True,
        context=context,
    )


def _mapped(byte: int) -> float:
    """The firmware maps -100..100 onto one byte for temperature and acceleration."""
    return byte * 200 / 255 - 100


def _unix(value: int) -> datetime | None:
    if value < MIN_VALID_UNIX:
        return None
    return datetime.fromtimestamp(value, tz=UTC)


class OpenCollarDriver:
    key: ClassVar[str] = "opencollar"
    label: ClassVar[str] = "OpenCollar Edge"
    capabilities: ClassVar[frozenset[str]] = frozenset(
        {
            "gnss",
            "battery",
            "temperature",
            "accelerometer",
            "flash_logging",
            "remote_settings",
            "fence",
            "external_switch",
            "ble_scanner",
            "wifi_scanner",
            "satellite",
            "drop_off",
        }
    )
    timestamp_semantics: ClassVar[dict[str, TimestampSemantics]] = {
        "gnss": TimestampSemantics.DEVICE_TIME,
        "status": TimestampSemantics.NETWORK_TIME,
        "fence": TimestampSemantics.NETWORK_TIME,
        "switch": TimestampSemantics.NETWORK_TIME,
        "flash_status": TimestampSemantics.NETWORK_TIME,
        "clock": TimestampSemantics.NETWORK_TIME,
    }
    decodable_event_types: ClassVar[frozenset[str]] = DEFAULT_DECODABLE_EVENT_TYPES
    control_actions: ClassVar[dict[str, ControlAction]] = CONTROL_ACTIONS

    def decode(self, event: SourceEventData) -> DecodedRecords:
        if event.frame is None or event.f_port is None:
            raise _fail("uplink carries no LoRaWAN frame or port", event_type=event.event_type)
        records = DecodedRecords(decoder_version=DECODER_VERSION)
        received = event.network_received_at or event.ingested_at
        if event.f_port == PORT_FLASH_LOG:
            self._decode_flash_log(event.frame, records)
        else:
            self._decode_message(event.f_port, event.frame, received, records, via="lorawan")
        return records

    # Framing

    def _decode_flash_log(self, frame: bytes, records: DecodedRecords) -> None:
        """Concatenated stored records: port, msg_id, len, data, store timestamp (u32)."""
        i = 0
        count = 0
        while i + 7 <= len(frame):
            port, length = frame[i], frame[i + 2]
            end = i + 3 + length
            if end + 4 > len(frame):
                raise _fail("flash log record is truncated", offset=i, port=port, length=length)
            message = frame[i + 1 : end]
            stored_at = _unix(struct.unpack_from("<I", frame, end)[0])
            if port == PORT_FLASH_LOG:
                i = end + 4
                continue
            self._decode_message(
                port,
                message,
                stored_at or datetime.fromtimestamp(0, tz=UTC),
                records,
                via="flash_log",
            )
            count += 1
            i = end + 4
        if count == 0 and len(frame) > 0:
            raise _fail("flash log holds no complete record", frame_length=len(frame))

    def _decode_message(
        self, port: int, frame: bytes, time: datetime, records: DecodedRecords, *, via: str
    ) -> None:
        if port in (PORT_SETTINGS, PORT_VALUES):
            records.states.append(
                DecodedState(
                    time=time, state={f"port_{port}_tlv": _parse_tlv(frame)}, record_type="settings"
                )
            )
            return
        if port == PORT_MESSAGES:
            self._decode_messages_port(frame, time, records, via)
            return
        spec = KNOWN_PORTS.get(port)
        if spec is None:
            raise _fail(f"unknown OpenCollar port {port}", port=port)
        expected_id, fixed_length = spec
        if len(frame) < 2:
            raise _fail("frame shorter than the two byte header", port=port)
        msg_id, length = frame[0], frame[1]
        if msg_id != expected_id:
            raise _fail(
                f"message id 0x{msg_id:02X} does not belong on port {port} (expected 0x{expected_id:02X})",
                port=port,
            )
        if fixed_length is not None and length != fixed_length:
            raise _fail(
                f"port {port} message has length {length}, expected {fixed_length}", port=port
            )
        data = frame[2 : 2 + length]
        if len(data) < length:
            raise _fail(
                "frame is shorter than its declared length",
                port=port,
                declared=length,
                actual=len(data),
            )
        if port == PORT_POSITION:
            self._decode_position(data, time, records, via)
        elif port in (PORT_SHORT_POSITION, PORT_RESEND_POSITION):
            self._decode_short_position(data, port, time, records, via)
        elif port == PORT_STATUS:
            self._decode_status(data, time, records, via)
        elif port == PORT_FENCE:
            self._decode_fence(data, time, records)
        elif port == PORT_FLASH_STATUS:
            used, count = struct.unpack_from("<BI", data)
            records.measurements += [
                DecodedMeasurement(
                    time=time,
                    metric_key="flash_used_percent",
                    value=float(used),
                    record_type="flash_status",
                ),
                DecodedMeasurement(
                    time=time,
                    metric_key="flash_messages",
                    value=float(count),
                    record_type="flash_status",
                ),
            ]
        elif port == PORT_TIMESTAMP:
            device_time = struct.unpack_from("<I", data)[0]
            records.states.append(
                DecodedState(time=time, state={"device_time": device_time}, record_type="clock")
            )
            records.measurements.append(
                DecodedMeasurement(
                    time=time,
                    metric_key="clock_offset",
                    value=float(device_time - int(time.timestamp())),
                    record_type="clock",
                )
            )
        elif port == PORT_SWITCH_CHANGE:
            active, duration_ms = struct.unpack_from("<BI", data)
            records.events.append(
                DecodedEvent(
                    time=time,
                    event_type="switch_activated" if active else "switch_deactivated",
                    title="External switch became active"
                    if active
                    else "External switch became inactive",
                    severity=Severity.INFO,
                    context={"previous_period_seconds": duration_ms / 1000},
                )
            )
            records.measurements.append(
                DecodedMeasurement(
                    time=time, metric_key="switch_active", value=bool(active), record_type="switch"
                )
            )
        elif port == PORT_SWITCH_STATUS:
            state, count = struct.unpack_from("<BI", data)
            if state in (0, 1):
                records.measurements.append(
                    DecodedMeasurement(
                        time=time,
                        metric_key="switch_active",
                        value=bool(state),
                        record_type="switch",
                    )
                )
            records.measurements.append(
                DecodedMeasurement(
                    time=time, metric_key="switch_count", value=float(count), record_type="switch"
                )
            )
        # ports in NOT_CANONICAL_PORTS are valid but produce no canonical rows in this phase

    # Messages

    def _decode_position(
        self, data: bytes, received: datetime, records: DecodedRecords, via: str
    ) -> None:
        (
            success,
            hot_retry,
            cold_retry,
            ttf,
            lat,
            lon,
            alt,
            fix_type,
            siv,
            h_acc,
            pdop,
            fix_ts,
            active,
        ) = struct.unpack_from("<BBBHiiiBBHBIB", data)
        fix_time = _unix(fix_ts)
        got_fix = bool(success & 0x01) and fix_time is not None and lat != 0 and lon != 0
        time = fix_time if got_fix and fix_time is not None else received
        records.measurements += [
            DecodedMeasurement(
                time=time, metric_key="gnss_fix", value=got_fix, record_type="gnss_attempt"
            ),
            DecodedMeasurement(
                time=time,
                metric_key="gnss_time_to_fix",
                value=float(ttf),
                record_type="gnss_attempt",
            ),
            DecodedMeasurement(
                time=time,
                metric_key="gnss_satellites",
                value=float(siv),
                record_type="gnss_attempt",
            ),
        ]
        if not got_fix:
            return
        attributes: dict[str, Any] = {
            "fix_type": fix_type,
            "pdop": pdop,
            "hot_retry": hot_retry,
            "cold_retry": cold_retry,
            "via": via,
            "port": PORT_POSITION,
        }
        speed = heading = None
        if active and len(data) >= 30:
            cog_raw, sog = struct.unpack_from("<HB", data, 27)
            heading = (cog_raw - 18000) / 100
            speed = float(sog)
            attributes["active_tracking"] = True
        records.positions.append(
            DecodedPosition(
                time=time,
                latitude=lat / 1e7,
                longitude=lon / 1e7,
                altitude_m=alt / 1000,
                accuracy_m=float(h_acc),
                satellites=siv,
                speed_mps=speed,
                heading_deg=heading,
                attributes=attributes,
            )
        )
        records.measurements += [
            DecodedMeasurement(
                time=time,
                metric_key="gnss_accuracy",
                value=float(h_acc),
                record_type="gnss_attempt",
            ),
            DecodedMeasurement(
                time=time, metric_key="gnss_pdop", value=float(pdop), record_type="gnss_attempt"
            ),
        ]

    def _decode_short_position(
        self, data: bytes, port: int, received: datetime, records: DecodedRecords, via: str
    ) -> None:
        fix_ts, lat, lon, h_acc = struct.unpack_from("<IiiH", data)
        fix_time = _unix(fix_ts)
        if fix_time is None or (lat == 0 and lon == 0):
            records.measurements.append(
                DecodedMeasurement(
                    time=received, metric_key="gnss_fix", value=False, record_type="gnss_attempt"
                )
            )
            return
        records.positions.append(
            DecodedPosition(
                time=fix_time,
                latitude=lat / 1e7,
                longitude=lon / 1e7,
                accuracy_m=float(h_acc),
                attributes={"via": via, "port": port, "resend": port == PORT_RESEND_POSITION},
            )
        )

    def _decode_status(
        self, data: bytes, time: datetime, records: DecodedRecords, via: str
    ) -> None:
        (
            reset,
            err,
            bat,
            operation,
            temp,
            uptime_days,
            acc_x,
            acc_y,
            acc_z,
            hw_ver,
            fw_ver,
            dev_type,
            chg,
            features,
        ) = struct.unpack_from("<14B", data)
        measurements = {
            "battery_voltage": (bat * 10 + 2500) / 1000,
            "device_temperature": round(_mapped(temp), 2),
            "acceleration_x": round(_mapped(acc_x), 2),
            "acceleration_y": round(_mapped(acc_y), 2),
            "acceleration_z": round(_mapped(acc_z), 2),
            "uptime": float(uptime_days * 86400),
            "lr_satellites": float(operation >> 4),
        }
        if chg:
            measurements["charging_voltage"] = (chg * 100 + 5000) / 1000
        records.measurements += [
            DecodedMeasurement(time=time, metric_key=k, value=v, record_type="status")
            for k, v in measurements.items()
        ]
        errors = {
            name: bool(err & bit)
            for name, bit in (
                ("lr_module", 1),
                ("ble", 2),
                ("ublox", 4),
                ("accelerometer", 8),
                ("battery", 16),
                ("ublox_fix", 32),
                ("flash", 64),
                ("ublox_busy", 128),
            )
        }
        errors["lr_join"] = bool(operation & 0x04)
        state = {
            "reset_reason": {
                "pin": bool(reset & 1),
                "watchdog": bool(reset & 2),
                "software": bool(reset & 4),
                "lockup": bool(reset & 8),
            },
            "errors": errors,
            "unread_message": bool(operation & 0x01),
            "locked": bool(operation & 0x02),
            "hardware_version": f"{hw_ver >> 4}.{hw_ver & 0x0F}",
            "firmware_version": f"{fw_ver >> 4}.{fw_ver & 0x0F}",
            "hardware_type": HARDWARE_TYPES.get(dev_type & 0x0F, str(dev_type & 0x0F)),
            "firmware_type": FIRMWARE_TYPES.get(dev_type >> 4, str(dev_type >> 4)),
            "satellite_enabled": bool(features & 1),
            "fence_enabled": bool(features & 4),
            "satellite_retries": features >> 4,
            "via": via,
        }
        records.states.append(DecodedState(time=time, state=state, record_type="status"))
        active_errors = [name for name, on in errors.items() if on]
        if active_errors:
            records.events.append(
                DecodedEvent(
                    time=time,
                    event_type="device_error",
                    title=f"Device reports errors: {', '.join(active_errors)}",
                    severity=Severity.WARNING,
                    context={"errors": active_errors},
                )
            )

    def _decode_fence(self, data: bytes, time: datetime, records: DecodedRecords) -> None:
        result, pulses, voltage, energy = struct.unpack_from("<BBHH", data)
        records.states.append(
            DecodedState(
                time=time,
                state={"fence_measurement": FENCE_RESULTS.get(result, str(result))},
                record_type="fence",
            )
        )
        if result == 0:
            records.measurements += [
                DecodedMeasurement(
                    time=time, metric_key="fence_voltage", value=float(voltage), record_type="fence"
                ),
                DecodedMeasurement(
                    time=time,
                    metric_key="fence_pulse_count",
                    value=float(pulses),
                    record_type="fence",
                ),
                DecodedMeasurement(
                    time=time, metric_key="fence_energy", value=float(energy), record_type="fence"
                ),
            ]
        else:
            records.events.append(
                DecodedEvent(
                    time=time,
                    event_type="fence_measurement_failed",
                    title=f"Fence measurement failed: {FENCE_RESULTS.get(result, result)}",
                    severity=Severity.WARNING,
                    context={"result": result},
                )
            )

    def _decode_messages_port(
        self, frame: bytes, time: datetime, records: DecodedRecords, via: str
    ) -> None:
        if len(frame) < 2:
            raise _fail("port 31 frame shorter than the header", port=PORT_MESSAGES)
        msg_id, length = frame[0], frame[1]
        data = frame[2 : 2 + length]
        if msg_id == 0xF3 and length == 2:
            records.states.append(
                DecodedState(
                    time=time,
                    state={"last_command": {"id": data[0], "executed": bool(data[1])}},
                    record_type="command",
                )
            )
        elif msg_id == 0xFD and length == 6:
            records.states.append(
                DecodedState(
                    time=time,
                    state={"ble_mac": ":".join(f"{b:02x}" for b in data)},
                    record_type="identity",
                )
            )
        elif msg_id == 0xFE and length == 16:
            # firmware order: longitude, latitude, altitude, fix time (the public decoder swaps the first two)
            lon, lat, alt, fix_ts = struct.unpack_from("<iiiI", data)
            fix_time = _unix(fix_ts)
            if fix_time is not None and (lat or lon):
                records.positions.append(
                    DecodedPosition(
                        time=fix_time,
                        latitude=lat / 1e7,
                        longitude=lon / 1e7,
                        altitude_m=alt / 1000,
                        attributes={"via": via, "port": PORT_MESSAGES, "requested": True},
                    )
                )
        else:
            raise _fail(
                f"unknown port 31 message 0x{msg_id:02X} with length {length}", port=PORT_MESSAGES
            )


def _parse_tlv(frame: bytes) -> dict[str, str]:
    result: dict[str, str] = {}
    i = 0
    while i + 2 <= len(frame):
        item_id, length = frame[i], frame[i + 1]
        result[f"0x{item_id:02X}"] = frame[i + 2 : i + 2 + length].hex()
        i += 2 + length
    return result
