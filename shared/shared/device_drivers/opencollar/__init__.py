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

import json
import re
import struct
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar

from shared.control.actions import ControlAction
from shared.device_drivers.base import (
    DEFAULT_DECODABLE_EVENT_TYPES,
    DecodedContact,
    DecodedEvent,
    DecodedMeasurement,
    DecodedPosition,
    DecodedRecords,
    DecodedState,
    HealthField,
    SourceEventData,
    TimestampSemantics,
)
from shared.device_drivers.opencollar.control import CONTROL_ACTIONS
from shared.enums import AcquisitionChannel, ErrorCode, Severity
from shared.trace import ApplicationError

DECODER_VERSION = "fw7.3.0"
CATALOG_PATH = Path(__file__).with_name("catalog.json")


@lru_cache
def _catalog() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(CATALOG_PATH.read_text())
    return data


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
NOT_CANONICAL_PORTS = {1, 5, 6, 9, 10, 15, 27, 28}
PORT_BLE_SCAN_AGGREGATED = 7  # msg 0xF9, the buffer the device summarised (research 3.7)
#: How many octets of an address a scan reports, and so how much of a MAC can ever be matched.
#: The devices a scan saw, one sample per scan window, zero when it looked and saw none.
BLE_CONTACTS_METRIC = "ble_contacts"

SCAN_ADDRESS_OCTETS = 3


def format_ble_mac(value: bytes) -> str:
    """The device's own six octet Bluetooth address, written the way addresses are written.

    `msg_mac_id` carries `bt_addr.val[0..5]` and Zephyr stores an address little endian, so the
    printed form runs the other way: `val[5]` first. Getting this backwards is not cosmetic. A
    scan reports `val[0..2]`, which is the *last* three octets as printed, so only an address
    written this way ends with what a neighbour's scan will say about it, and a contact could
    never be matched to the device that made it."""
    return ":".join(f"{b:02x}" for b in reversed(value))


def scan_suffix(mac: str) -> str:
    """The part of a device's address a neighbour's scan can report: its last three octets."""
    return ":".join(mac.lower().split(":")[-SCAN_ADDRESS_OCTETS:])


PORT_BLE_SCAN = 11  # msg 0xFA, one scan as it happened (research 3.9)
PORT_RF_SCAN = 8  # firmware 4.x to 6.16, removed in 7.1.0 (research 3.23)
PORT_OPEN_SKY = 17  # firmware 6.x, removed in 7.1.0; the message has no id byte
PORT_AIR_QUALITY = 21  # firmware 7.2.0 and later


@dataclass(frozen=True, slots=True)
class Layout:
    """What one firmware range sends (decision D100): its ports with message id and fixed
    length, whether status feature bit 2 means the RF scanner, and the CMDQ record length.
    Named after the reference decoder of the range (research section 5.1)."""

    key: str
    since: tuple[int, int]
    ports: dict[int, tuple[int | None, int | None]]
    rf_scan_bit: bool
    cmdq_record_length: int | None


def _ports(
    *, legacy: bool, switches: bool, air_quality: bool, cmdq: bool
) -> dict[int, tuple[int | None, int | None]]:
    ports: dict[int, tuple[int | None, int | None]] = {
        k: v for k, v in KNOWN_PORTS.items() if k not in (PORT_AIR_QUALITY, 15, 18, 19, 20)
    }
    if legacy:
        ports[PORT_RF_SCAN] = (0xFB, None)
        ports[PORT_OPEN_SKY] = (None, None)
    if switches:
        ports[PORT_TIMESTAMP] = KNOWN_PORTS[PORT_TIMESTAMP]
        ports[PORT_SWITCH_CHANGE] = KNOWN_PORTS[PORT_SWITCH_CHANGE]
        ports[PORT_SWITCH_STATUS] = KNOWN_PORTS[PORT_SWITCH_STATUS]
    if air_quality:
        ports[PORT_AIR_QUALITY] = KNOWN_PORTS[PORT_AIR_QUALITY]
    if cmdq:
        ports[15] = KNOWN_PORTS[15]
    return ports


# Newest first. The status message carries major.minor only, and a minor of 16 and above
# appears modulo 16 (research section 3.4), so a reported 6.0 is read as 6.16.
LAYOUTS: tuple[Layout, ...] = (
    Layout(
        "fw7.2.0",
        (7, 1),
        _ports(legacy=False, switches=True, air_quality=True, cmdq=True),
        False,
        15,
    ),
    Layout(
        "fw6.15.1",
        (6, 15),
        _ports(legacy=True, switches=True, air_quality=False, cmdq=True),
        True,
        15,
    ),
    Layout(
        "fw6.11.2",
        (6, 9),
        _ports(legacy=True, switches=False, air_quality=False, cmdq=True),
        True,
        15,
    ),
    Layout(
        "fw6.5.0",
        (6, 1),
        _ports(legacy=True, switches=False, air_quality=False, cmdq=True),
        True,
        13,
    ),
    Layout(
        "fw4.4.3",
        (0, 0),
        _ports(legacy=True, switches=False, air_quality=False, cmdq=False),
        True,
        None,
    ),
)
# Where a port a layout lacks comes from, for the trace note.
PORT_HISTORY: dict[int, str] = {
    PORT_RF_SCAN: "the legacy RF scanner message of firmware 4.x to 6.16, removed in 7.1.0",
    PORT_OPEN_SKY: "the legacy open sky detection message of firmware 6.x, removed in 7.1.0",
    PORT_AIR_QUALITY: "the air quality message of firmware 7.2.0 and later",
    PORT_TIMESTAMP: "the timestamp message of firmware 6.15.0 and later",
    PORT_SWITCH_CHANGE: "the external switch message of firmware 6.15.0 and later",
    PORT_SWITCH_STATUS: "the external switch status of firmware 6.15.0 and later",
    15: "the Bluetooth CMDQ message of firmware 6.1.0 and later",
    199: "the legacy Modem-E info message, disabled by default since 6.2.0",
}


def parse_firmware(version: str | None) -> tuple[int, int] | None:
    if not version:
        return None
    match = re.match(r"^v?(\d+)\.(\d+)", str(version).strip())
    if match is None:
        return None
    major, minor = int(match.group(1)), int(match.group(2))
    if major == 6 and minor == 0:
        minor = 16  # 6.16 does not fit the nibble and reports as 6.0
    return major, minor


UPTIME_IN_DAYS_SINCE = (4, 0)
UPTIME_WRAP = 255


def uptime_unit_seconds(version: str | None) -> int:
    """Seconds per unit of the status message's uptime byte: hours before firmware 4.0.1,
    days since (the byte carries major.minor only, so 4.0 is read as days)."""
    parsed = parse_firmware(version)
    return 86400 if parsed is None or parsed >= UPTIME_IN_DAYS_SINCE else 3600


def uptime_wrap_seconds(version: str | None) -> float:
    """Where the uptime byte wraps to zero without a reboot: 255 units."""
    return float(UPTIME_WRAP * uptime_unit_seconds(version))


def layout_for(version: str | None) -> Layout:
    """The layout for a firmware version; unknown means the newest."""
    parsed = parse_firmware(version)
    if parsed is None:
        return LAYOUTS[0]
    for layout in LAYOUTS:
        if parsed >= layout.since:
            return layout
    return LAYOUTS[-1]


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


# The device's health (decision D104): the port 4 status message every device sends on its
# interval, plus the last fix. The battery thresholds here are the fallback for a device with no
# battery type: they assume a primary lithium cell, which is why the driver declares that type
# (decision D248). A device with a rechargeable cell is given its own type on the device page,
# and then the chemistry's thresholds and its share of charge take over. GNSS accuracy above
# 30 m is a poor fix.
OPENCOLLAR_HEALTH: tuple[HealthField, ...] = (
    HealthField("battery_voltage", "Battery", unit="V", warn_below=3.6, critical_below=3.45),
    HealthField("charging_voltage", "Charging", unit="V"),
    HealthField("device_temperature", "Temperature", unit="°C", warn_above=50, critical_above=60),
    HealthField("uptime", "Uptime", kind="duration"),
    HealthField("errors", "Errors", source="state", kind="flags", flags_are_problems=True),
    HealthField("reset_reason", "Last reset", source="state", kind="flags"),
    HealthField("firmware_version", "Firmware", source="state", kind="text"),
    HealthField("hardware_version", "Hardware", source="state", kind="text"),
    HealthField("gnss_satellites", "Satellites of the last fix"),
    HealthField("gnss_accuracy", "Accuracy of the last fix", unit="m", warn_above=30),
    HealthField("gnss_time_to_fix", "Time to the last fix", unit="s", warn_above=120),
    HealthField("lr_satellites", "LoRa satellites"),
    HealthField("flash_used_percent", "Flash used", unit="%", warn_above=80, critical_above=95),
)


class OpenCollarDriver:
    key: ClassVar[str] = "opencollar"
    label: ClassVar[str] = "OpenCollar Edge"
    health: ClassVar[tuple[HealthField, ...]] = OPENCOLLAR_HEALTH
    default_battery_type: ClassVar[str] = "primary_lithium"
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
        """One delivery on any acquisition channel (architecture 25.1):

        * LoRaWAN: the application payload on its FPort.
        * WebBLE and raw log files: a notification frame `[port][msg_id][len][data]`; on port
          29 the rest of the frame is the stored record stream.
        * Iridium: the RockBLOCK send buffer, a record stream in the flash storage format
          (`[port][msg_id][len][data][store timestamp]` repeated, wiki satellite page).
        """
        layout = layout_for(event.firmware_version)
        records = DecodedRecords(decoder_version=layout.key)
        received = event.network_received_at or event.ingested_at
        channel = event.acquisition_channel or AcquisitionChannel.LORAWAN
        if event.frame is None:
            raise _fail("delivery carries no frame", event_type=event.event_type, channel=channel)
        if channel in (AcquisitionChannel.WEBBLE, AcquisitionChannel.LOG_FILE):
            if len(event.frame) < 2:
                raise _fail("frame shorter than a port byte and a message", channel=channel)
            port, message = event.frame[0], event.frame[1:]
            if port == PORT_FLASH_LOG:
                self._decode_flash_log(message, records, layout)
            else:
                self._decode_message(
                    port, message, received, records, via=str(channel), layout=layout
                )
            return records
        if channel == AcquisitionChannel.IRIDIUM:
            self._decode_flash_log(event.frame, records, layout)
            return records
        if event.f_port is None:
            raise _fail("uplink carries no LoRaWAN port", event_type=event.event_type)
        if event.f_port == PORT_FLASH_LOG:
            self._decode_flash_log(event.frame, records, layout)
        else:
            self._decode_message(
                event.f_port, event.frame, received, records, via="lorawan", layout=layout
            )
        return records

    def _decode_air_quality(self, data: bytes, time: datetime, records: DecodedRecords) -> None:
        """Port 21 (firmware 7.2.0, decoder 7.2.0 `decodeAirQualityMessage`): BME690 gas sensor
        values, BMV080 particle values, or both, as little-endian floats; the length says which."""
        length = len(data)
        bme: dict[str, float] = {}
        bmv: dict[str, float | bool] = {}
        if length == 0:
            records.notes.append("air quality message without data")
            return
        if 0 < length < 25:
            bme = self._air_bme690(data, 0)
        elif length == 25:
            bmv = self._air_bmv080(data, 0)
        elif 25 < length < 46:
            bmv = self._air_bmv080(data, 0)
            bme = self._air_bme690(data, 25)
        else:
            raise _fail("air quality message has an invalid length", length=length)
        for key, value in {**bme, **bmv}.items():
            records.measurements.append(
                DecodedMeasurement(
                    time=time,
                    metric_key=key,
                    value=value if isinstance(value, bool) else round(float(value), 3),
                    record_type="air_quality",
                )
            )

    @staticmethod
    def _air_bme690(data: bytes, offset: int) -> dict[str, float]:
        if len(data) < offset + 20:
            raise _fail("BME690 block is truncated", have=len(data) - offset)
        iaq, temperature, pressure, humidity, raw_gas = struct.unpack_from("<5f", data, offset)
        return {
            "air_q_iaq": iaq,
            "air_q_temperature": temperature,
            "air_q_pressure": pressure,
            "air_q_humidity": humidity,
            "air_q_raw_gas": raw_gas,
        }

    @staticmethod
    def _air_bmv080(data: bytes, offset: int) -> dict[str, float | bool]:
        if len(data) < offset + 25:
            raise _fail("BMV080 block is truncated", have=len(data) - offset)
        pm25_mass, pm1_mass, pm10_mass, pm25_num, pm1_num, pm10_num = struct.unpack_from(
            "<6f", data, offset
        )
        return {
            "air_q_pm2_5_mass": pm25_mass,
            "air_q_pm1_mass": pm1_mass,
            "air_q_pm10_mass": pm10_mass,
            "air_q_pm2_5_number": pm25_num,
            "air_q_pm1_number": pm1_num,
            "air_q_pm10_number": pm10_num,
            "air_q_obstructed": bool(data[offset + 24]),
        }

    @staticmethod
    @staticmethod
    def _address(data: bytes, offset: int) -> str:
        """The three octets of a neighbour's Bluetooth address as the firmware sends them.

        Zephyr stores an address little endian and the firmware copies `bt_addr.val[0..2]`, so
        the three least significant octets arrive in that order and are read back highest first
        (research 3.7). The reference decoder prints them with `toString(16)`, which drops a
        leading zero; ours pads, so `0a:41:0c` never reads as `a:41:c` and two spellings of one
        address can never become two neighbours."""
        return f"{data[offset + 2]:02x}:{data[offset + 1]:02x}:{data[offset]:02x}"

    def _decode_ble_scan(self, data: bytes, time: datetime, records: DecodedRecords) -> None:
        """Port 11 (`decodeLastScanMessage`): one scan, its finish time, then four bytes per
        device seen. The scan's own time is canonical for every sighting in it.

        Only the first message of a scan goes over the air when the results do not fit one
        payload; the rest are in the device's flash, so a log file upload of the same period
        fills in what the air left out (research 3.9)."""
        if len(data) < 5:
            raise _fail("BLE scan message shorter than its header", port=PORT_BLE_SCAN)
        scan_at = _unix(struct.unpack_from("<I", data, 0)[0]) or time
        seen = data[4]
        length = len(data) + 2  # the declared length the reference decoder guards on
        index, offset = 0, 5
        while index < seen and offset < length - 1 and offset + 4 <= len(data):
            records.contacts.append(
                DecodedContact(
                    time=scan_at,
                    address=self._address(data, offset),
                    rssi_dbm=data[offset + 3] - 128,
                    scan_kind="single",
                )
            )
            index += 1
            offset += 4
        self._note_scan(records, scan_at, seen, len(records.contacts), "single")

    def _decode_ble_scan_aggregated(
        self, data: bytes, time: datetime, records: DecodedRecords
    ) -> None:
        """Port 7 (`decodeScanMessage`): the devices the buffer held, nine bytes each, with the
        best signal, how often it was seen and when the strongest sighting was. That last time
        is the canonical one, since it is the moment the record is actually about.

        At most five of the twenty a buffer holds are sent, and the buffer is cleared when the
        message is composed, so these counts are what the device chose to report and not a
        census (research 3.7)."""
        if not data:
            raise _fail("aggregated BLE scan message is empty", port=PORT_BLE_SCAN_AGGREGATED)
        seen = data[0]
        length = len(data) + 2
        index, offset = 0, 1
        while index < seen and offset < length - 1 and offset + 9 <= len(data):
            best_at = _unix(struct.unpack_from("<I", data, offset + 5)[0])
            records.contacts.append(
                DecodedContact(
                    time=best_at or time,
                    address=self._address(data, offset),
                    rssi_dbm=data[offset + 3] - 128,
                    sightings=data[offset + 4],
                    scan_kind="aggregated",
                    attributes={} if best_at else {"time_from": "delivery"},
                )
            )
            index += 1
            offset += 9
        self._note_scan(records, time, seen, len(records.contacts), "aggregated")

    @staticmethod
    def _note_scan(
        records: DecodedRecords, scan_at: datetime, seen: int, kept: int, kind: str
    ) -> None:
        """Every scan leaves a state, so that a device which looked and saw nothing can be told
        from one that never looked: with `ble_scan_report_zero_connections_found` on, an empty
        scan is a real answer and the only record of it."""
        records.states.append(
            DecodedState(
                time=scan_at,
                state={"ble_scan": {"seen": seen, "reported": kept, "kind": kind}},
                record_type="ble_scan",
            )
        )
        # and a number, so a scanner's activity draws as a line like any other value. A scan
        # that saw nothing is a zero and not a gap: the gaps are the times it was not looking,
        # which is the other thing a reader of this chart needs to tell apart.
        records.measurements.append(
            DecodedMeasurement(
                time=scan_at,
                metric_key=BLE_CONTACTS_METRIC,
                value=float(seen),
                record_type="ble_scan",
            )
        )
        if seen == 0:
            records.notes.append(f"{kind} BLE scan saw no devices")
        elif kept < seen:
            records.notes.append(
                f"{kind} BLE scan reported {kept} of the {seen} devices it saw; "
                "the rest are in the device's flash"
            )

    @staticmethod
    def _decode_rf_scan(data: bytes, time: datetime, records: DecodedRecords) -> None:
        """Port 8 (decoders up to 6.15.x `decodeRfScannerMessage`): a version and alert byte,
        then per band start and stop in MHz times ten, a peak count and a negated RSSI."""
        if len(data) < 2:
            raise _fail("RF scan message shorter than its header")
        bands = []
        for i in range(2, len(data) - 5, 6):
            start, stop = struct.unpack_from("<HH", data, i)
            bands.append(
                {
                    "start_mhz": start / 10,
                    "stop_mhz": stop / 10,
                    "peak_count": data[i + 4],
                    "max_rssi": -data[i + 5],
                }
            )
        records.states.append(
            DecodedState(
                time=time,
                state={
                    "rf_scan": {"version": data[0], "should_alert": bool(data[1]), "bands": bands}
                },
                record_type="rf_scan",
            )
        )

    @staticmethod
    def _decode_open_sky(payload: bytes, time: datetime, records: DecodedRecords) -> None:
        """Port 17 (decoders up to 6.15.x `decodeOpenSkyDetection`): the length byte then
        pairs of negated average and maximum RSSI."""
        if not payload:
            raise _fail("open sky message without a length byte")
        length = payload[0]
        pairs = payload[1 : 1 + length]
        results = [
            {"average_rssi": -pairs[i], "max_rssi": -pairs[i + 1]}
            for i in range(0, len(pairs) - 1, 2)
        ]
        records.states.append(
            DecodedState(time=time, state={"open_sky": results}, record_type="open_sky")
        )

    @staticmethod
    def catalog() -> dict[str, Any]:
        """Settings, commands and values of the protocol (research sections 4.2 to 4.4), for
        the WebBLE settings editor and the documentation. Generated from the research document
        into `catalog.json`; regenerate when a firmware release changes the tables."""
        return dict(_catalog())

    # Framing

    def _decode_flash_log(self, frame: bytes, records: DecodedRecords, layout: Layout) -> None:
        """Concatenated stored records: port, msg_id, len, data, store timestamp (u32). A status
        record inside the stream names the firmware; the records after it use its layout."""
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
            before = len(records.states)
            self._decode_message(
                port,
                message,
                stored_at or datetime.fromtimestamp(0, tz=UTC),
                records,
                via="flash_log",
                layout=layout,
            )
            if port == PORT_STATUS and len(records.states) > before:
                reported = records.states[-1].state.get("firmware_version")
                learned = layout_for(str(reported)) if reported else layout
                if learned.key != layout.key:
                    layout = learned
                    records.decoder_version = layout.key
            count += 1
            i = end + 4
        if count == 0 and len(frame) > 0:
            raise _fail("flash log holds no complete record", frame_length=len(frame))

    def _decode_message(
        self,
        port: int,
        frame: bytes,
        time: datetime,
        records: DecodedRecords,
        *,
        via: str,
        layout: Layout,
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
        spec = layout.ports.get(port)
        if spec is None:
            # A port this firmware's catalogue lacks is data, not a fault of the delivery:
            # note it on the trace and keep the source event (research 3.23, decision D100).
            history = PORT_HISTORY.get(port)
            records.notes.append(
                f"port {port} is not in the {layout.key} catalogue: {history}"
                if history
                else f"port {port} is not in the {layout.key} catalogue"
            )
            return
        expected_id, fixed_length = spec
        if len(frame) < 2:
            raise _fail("frame shorter than the two byte header", port=port)
        msg_id, length = frame[0], frame[1]
        if expected_id is not None and msg_id != expected_id:
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
            self._decode_status(data, time, records, via, layout)
        elif port == PORT_AIR_QUALITY:
            self._decode_air_quality(data, time, records)
        elif port == PORT_BLE_SCAN:
            self._decode_ble_scan(data, time, records)
        elif port == PORT_BLE_SCAN_AGGREGATED:
            self._decode_ble_scan_aggregated(data, time, records)
        elif port == PORT_RF_SCAN:
            self._decode_rf_scan(data, time, records)
        elif port == PORT_OPEN_SKY:
            self._decode_open_sky(frame[1:], time, records)
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

    def uptime_wrap_seconds(self, firmware_version: str | None) -> float:
        """For the decoder's reboot detection: the uptime byte wraps at 255 hours or days."""
        return uptime_wrap_seconds(firmware_version)

    def _decode_status(
        self, data: bytes, time: datetime, records: DecodedRecords, via: str, layout: Layout
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
        # the uptime byte counts days since firmware 4.0.1 and hours before (firmware
        # CHANGELOG 4.0.1: "display uptime in days instead of hours"); it wraps at 255
        reported = f"{fw_ver >> 4}.{fw_ver & 0x0F}"
        measurements = {
            "battery_voltage": (bat * 10 + 2500) / 1000,
            "device_temperature": round(_mapped(temp), 2),
            "acceleration_x": round(_mapped(acc_x), 2),
            "acceleration_y": round(_mapped(acc_y), 2),
            "acceleration_z": round(_mapped(acc_z), 2),
            "uptime": float(uptime_days * uptime_unit_seconds(reported)),
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
            # Feature bit 2 meant the RF scanner up to firmware 6.16 (decision D100).
            **({"rf_scan_enabled": bool(features & 2)} if layout.rf_scan_bit else {}),
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
                    state={"ble_mac": format_ble_mac(data)},
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
