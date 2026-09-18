"""African Wildlife Tracking (AWT) LoRaWAN tracker driver (decision D241).

The frame is the one AWT's own ChirpStack codec reads (`tests/fixtures/payloads/awt/decoder.js`,
the codec Tim runs on the BPC ChirpStack, 2026-09-17), one message per uplink on any port:

    byte  0      header
    byte  1      message counter
    byte  2      command: 0x91 encrypted, 0xD1 not encrypted
    byte  3      payload length
    byte  4      header CRC: XOR of bytes 0 to 3
    byte  5      sub command: the payload type (minimal, standard, with altitude, with light)
    bytes 6-7    master tag id, little endian
    bytes 8-9    tag id, little endian
    byte  10     alarms: bit0 OTA track mode, bit1 low battery, bit3 tamper foil,
                 bit5 service coverage, bit6 memory full, bit7 self test
    byte  11     acknowledgements: bit0 humidity alarm, bit1 polling on, bit2 BLE command ack,
                 bit3 UHF command ack, bit4 OTA command ack, bits 5-7 upload retries
    byte  12     software version
    byte  13     reporting interval code (`REPORTING_INTERVALS`)
    bytes 14-15  battery voltage, big endian, hundredths of a volt
    bytes 16-19  unix time of the fix, big endian
    bytes 20-23  latitude word: bits 0-26 the digits ddmmmmmm (degrees, then minutes times
                 ten thousand), bits 27-30 the HDOP, bit 31 set for south
    bytes 24-27  longitude word: bits 0-27 the digits dddmmmmmm, bit 28 global ack, bit 29
                 movement, bit 30 alarm, bit 31 set for east
    byte  28     ground speed (unit not documented; kept raw)
    byte  29     message key
    bytes 30-35  accelerometer x, y, z, signed big endian (unit not documented; kept raw)
    byte  36     temperature (degrees Celsius as the codec reads it)
    bytes 37-38  altitude in metres, when the payload type carries it
    bytes 39-40  light level, when the payload type carries it (unit not documented)
    last byte    payload CRC: XOR of byte 5 up to the byte before it

Two things the codec does differently and this driver does not: the codec's hemisphere test
reads the first character of a binary string, which is always "1" for a non-zero number, so it
puts every fix south and east, which happens to be right in southern Africa; the driver reads
the sign bits themselves. The codec reads the HDOP from one byte at bit 27, which a byte does
not have; the driver reads bits 27 to 30 of the latitude word, which the layout leaves for it.
Both stand until a fix outside the south-east quadrant, or AWT's document, says otherwise.

What comes out: a position with the device's fix time, the HDOP as `gnss_hdop`, the battery
as `battery_voltage`, the temperature as `device_temperature`, a `status` state with the
flags, the firmware and the reporting interval, a `settings` state with the fix interval the
device says it keeps (read by the expected-interval rules, decision D242), and a `device_error`
event when a problem flag is on.

What does not come out, and why (reviewed 2026-09-18): the movement line (decision D204) is
derived from `acceleration_x/y/z` in a status message, in metres per second squared. AWT's
accelerometer arrives as three signed counts whose full scale the codec does not state, so the
axes are kept raw under `accelerometer` in the status and no movement is derived; a made-up
scale would give a made-up threshold. With AWT's scale the three values become
`acceleration_x/y/z` and the movement line follows without further work.
"""

from __future__ import annotations

import struct
from datetime import UTC, datetime
from typing import Any, ClassVar

from shared.device_drivers.base import (
    DEFAULT_DECODABLE_EVENT_TYPES,
    DecodedEvent,
    DecodedMeasurement,
    DecodedPosition,
    DecodedRecords,
    DecodedState,
    HealthField,
    SourceEventData,
    TimestampSemantics,
)
from shared.enums import ErrorCode, Severity
from shared.trace import ApplicationError

COMPONENT = "driver.awt"
MIN_LENGTH = 38
#: A fix time before this is the device's clock unset, not a time.
EARLIEST_PLAUSIBLE = datetime(2015, 1, 1, tzinfo=UTC)

PAYLOAD_TYPES: dict[int, str] = {
    0x00: "minimal",
    0x01: "standard",
    0x03: "standard_altitude",
    0x04: "standard_light",
    0x05: "standard_altitude_light",
}

#: The reporting interval code and the seconds it stands for (None: off or custom).
REPORTING_INTERVALS: dict[int, int | None] = {
    0: None,
    1: 600,
    2: 3600,
    3: 21600,
    4: 43200,
    5: 86400,
    7: 10800,
    15: 1800,
    16: 7200,
    17: 14400,
    18: 18000,
    19: 28800,
    20: None,
}

#: The alarm bits of byte 10 and the acknowledgement bits of byte 11 that mean a problem.
ALARM_BITS: dict[str, int] = {
    "ota_track_mode": 0x01,
    "low_battery": 0x02,
    "tamper_foil": 0x08,
    "service_coverage": 0x20,
    "memory_full": 0x40,
    "self_test": 0x80,
}
ACK_BITS: dict[str, int] = {
    "humidity_alarm": 0x01,
    "polling_on": 0x02,
    "ble_command_ack": 0x04,
    "uhf_command_ack": 0x08,
    "ota_command_ack": 0x10,
}
PROBLEM_FLAGS: tuple[str, ...] = (
    "low_battery",
    "tamper_foil",
    "service_coverage",
    "memory_full",
    "self_test",
    "humidity_alarm",
)

AWT_HEALTH: tuple[HealthField, ...] = (
    HealthField("battery_voltage", "Battery", unit="V"),
    HealthField("device_temperature", "Temperature", unit="°C", warn_above=50, critical_above=60),
    HealthField("errors", "Errors", source="state", kind="flags", flags_are_problems=True),
    HealthField("firmware_version", "Firmware", source="state", kind="text"),
    HealthField("gnss_hdop", "HDOP of the last fix", warn_above=5),
)


def _fail(message: str, **context: Any) -> ApplicationError:
    return ApplicationError(
        code=ErrorCode.PAYLOAD_DECODE_FAILED,
        message=message,
        component=COMPONENT,
        user_actionable=True,
        context=context,
    )


def xor(data: bytes) -> int:
    value = 0
    for byte in data:
        value ^= byte
    return value


def decode_latitude(word: int) -> tuple[float, int]:
    """The latitude in decimal degrees and the HDOP from the 32-bit latitude word."""
    digits = word & 0x07FFFFFF
    hdop = (word >> 27) & 0x0F
    text = f"{digits:08d}"
    degrees = int(text[:2])
    minutes = int(text[2:]) / 10000
    sign = -1 if word & 0x80000000 else 1
    return sign * (degrees + minutes / 60), hdop


def decode_longitude(word: int) -> tuple[float, dict[str, bool]]:
    """The longitude in decimal degrees and the three flags from the 32-bit longitude word."""
    digits = word & 0x0FFFFFFF
    text = f"{digits:09d}"
    degrees = int(text[:3])
    minutes = int(text[3:]) / 10000
    sign = 1 if word & 0x80000000 else -1
    flags = {
        "global_ack": bool(word & 0x10000000),
        "movement": bool(word & 0x20000000),
        "alarm": bool(word & 0x40000000),
    }
    return sign * (degrees + minutes / 60), flags


def parse_frame(frame: bytes) -> dict[str, Any]:
    """Every field of one AWT frame, as the layout above names them; raises for a frame too
    short to hold the fixed part."""
    if len(frame) < MIN_LENGTH:
        raise _fail("AWT frame shorter than its fixed part", length=len(frame), needed=MIN_LENGTH)
    header_crc_ok = xor(frame[0:4]) == frame[4]
    payload_crc_ok = xor(frame[5:-1]) == frame[-1]
    alarms = {name: bool(frame[10] & bit) for name, bit in ALARM_BITS.items()}
    acks = {name: bool(frame[11] & bit) for name, bit in ACK_BITS.items()}
    battery = struct.unpack_from(">H", frame, 14)[0] / 100
    epoch = struct.unpack_from(">I", frame, 16)[0]
    lat_word = struct.unpack_from(">I", frame, 20)[0]
    lon_word = struct.unpack_from(">I", frame, 24)[0]
    latitude, hdop = decode_latitude(lat_word)
    longitude, flags = decode_longitude(lon_word)
    x, y, z = struct.unpack_from(">hhh", frame, 30)
    out: dict[str, Any] = {
        "header": frame[0],
        "message_counter": frame[1],
        "encrypted": frame[2] == 0x91,
        "payload_length": frame[3],
        "header_crc_ok": header_crc_ok,
        "payload_crc_ok": payload_crc_ok,
        "payload_type": PAYLOAD_TYPES.get(frame[5], f"unknown_{frame[5]:#04x}"),
        "master_tag_id": frame[6] | (frame[7] << 8),
        "tag_id": frame[8] | (frame[9] << 8),
        "alarms": alarms,
        "acks": acks,
        "upload_retries": frame[11] >> 5,
        "software_version": frame[12],
        "reporting_interval_code": frame[13],
        "reporting_interval_s": REPORTING_INTERVALS.get(frame[13]),
        "battery_voltage": battery,
        "epoch": epoch,
        "latitude": latitude,
        "longitude": longitude,
        "hdop": hdop,
        "flags": flags,
        "ground_speed_raw": frame[28],
        "message_key": frame[29],
        "accelerometer": {"x": x, "y": y, "z": z},
        "temperature_c": frame[36],
    }
    if len(frame) > 38:
        out["altitude_m"] = struct.unpack_from(">H", frame, 37)[0]
    if len(frame) > 40:
        out["light_raw"] = struct.unpack_from(">H", frame, 39)[0]
    return out


class AwtDriver:
    key: ClassVar[str] = "awt"
    label: ClassVar[str] = "AWT tracker"
    health: ClassVar[tuple[HealthField, ...]] = AWT_HEALTH
    capabilities: ClassVar[frozenset[str]] = frozenset({"gnss", "battery", "temperature"})
    timestamp_semantics: ClassVar[dict[str, TimestampSemantics]] = {
        "gnss": TimestampSemantics.DEVICE_TIME,
        "measurement": TimestampSemantics.DEVICE_TIME,
        "status": TimestampSemantics.DEVICE_TIME,
        "settings": TimestampSemantics.DEVICE_TIME,
        "event": TimestampSemantics.DEVICE_TIME,
    }
    decodable_event_types: ClassVar[frozenset[str]] = DEFAULT_DECODABLE_EVENT_TYPES

    def decode(self, event: SourceEventData) -> DecodedRecords:
        if event.frame is None:
            raise _fail("delivery carries no frame", event_type=event.event_type)
        fields = parse_frame(event.frame)
        records = DecodedRecords(decoder_version="1")
        received = event.network_received_at or event.ingested_at
        time = datetime.fromtimestamp(fields["epoch"], tz=UTC)
        if time < EARLIEST_PLAUSIBLE:
            # the device's clock is not set: the network's time is the best there is
            records.notes.append(f"fix time {fields['epoch']} is before 2015; network time used")
            time = received
        if not fields["header_crc_ok"] or not fields["payload_crc_ok"]:
            records.notes.append("a CRC of the frame does not match; the values are kept as read")
        has_fix = fields["latitude"] != 0 or fields["longitude"] != 0
        if has_fix:
            records.positions.append(
                DecodedPosition(
                    time=time,
                    latitude=fields["latitude"],
                    longitude=fields["longitude"],
                    altitude_m=fields.get("altitude_m"),
                    attributes={
                        "hdop": fields["hdop"],
                        "ground_speed_raw": fields["ground_speed_raw"],
                        "movement": fields["flags"]["movement"],
                        "payload_type": fields["payload_type"],
                    },
                )
            )
            records.measurements.append(
                DecodedMeasurement(time=time, metric_key="gnss_hdop", value=float(fields["hdop"]))
            )
        records.measurements.append(
            DecodedMeasurement(
                time=time, metric_key="battery_voltage", value=fields["battery_voltage"]
            )
        )
        records.measurements.append(
            DecodedMeasurement(
                time=time, metric_key="device_temperature", value=float(fields["temperature_c"])
            )
        )
        errors = {
            name: on
            for name, on in {**fields["alarms"], **fields["acks"]}.items()
            if name in PROBLEM_FLAGS
        }
        state: dict[str, Any] = {
            "errors": errors,
            "firmware_version": str(fields["software_version"]),
            "reporting_interval_s": fields["reporting_interval_s"],
            "reporting_interval_code": fields["reporting_interval_code"],
            "payload_type": fields["payload_type"],
            "encrypted": fields["encrypted"],
            "message_counter": fields["message_counter"],
            "tag_id": fields["tag_id"],
            "master_tag_id": fields["master_tag_id"],
            "upload_retries": fields["upload_retries"],
            "ota_track_mode": fields["alarms"]["ota_track_mode"],
            "polling_on": fields["acks"]["polling_on"],
            "alarm_flag": fields["flags"]["alarm"],
            "movement_flag": fields["flags"]["movement"],
            "global_ack": fields["flags"]["global_ack"],
            "accelerometer": fields["accelerometer"],
            "crc_ok": fields["header_crc_ok"] and fields["payload_crc_ok"],
        }
        if "light_raw" in fields:
            state["light_raw"] = fields["light_raw"]
        records.states.append(DecodedState(time=time, state=state, record_type="status"))
        if fields["reporting_interval_s"]:
            # the interval the device says it keeps, for the expected-interval rules (D242)
            records.states.append(
                DecodedState(
                    time=time,
                    state={"settings": {"fix_interval": fields["reporting_interval_s"]}},
                    record_type="settings",
                )
            )
        active = [name for name, on in errors.items() if on]
        if active:
            records.events.append(
                DecodedEvent(
                    time=time,
                    event_type="device_error",
                    title=f"Device reports errors: {', '.join(active)}",
                    severity=Severity.WARNING,
                    context={"errors": active},
                    latitude=fields["latitude"] if has_fix else None,
                    longitude=fields["longitude"] if has_fix else None,
                )
            )
        return records
