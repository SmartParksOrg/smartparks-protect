"""The Bluetooth scan messages an OpenCollar sends (phase 30, decision D252): ports 11 and 7,
built to the firmware's own layout (research 3.7 and 3.9) and read back."""

import struct
from datetime import UTC, datetime

import pytest

from shared.device_drivers.base import SourceEventData
from shared.device_drivers.opencollar import OpenCollarDriver
from shared.trace import ApplicationError

RECEIVED = datetime(2026, 9, 18, 12, tzinfo=UTC)
SCAN_AT = datetime(2026, 9, 18, 11, 30, tzinfo=UTC)
driver = OpenCollarDriver()


def decode(port: int, data: bytes, firmware: str = "7.2"):
    frame = bytes([{7: 0xF9, 11: 0xFA}[port], len(data)]) + data
    return driver.decode(
        SourceEventData(
            id=1,
            event_type="uplink",
            payload={"fPort": port},
            provider_metadata={"f_port": port},
            network_received_at=RECEIVED,
            ingested_at=RECEIVED,
            device_attributes={},
            device_type_settings={},
            frame=frame,
            f_port=port,
            firmware_version=firmware,
        )
    )


def single(records: list[tuple[bytes, int]], scan_at: datetime = SCAN_AT) -> bytes:
    """A port 11 body: the scan time, the count, then three address octets and rssi+128."""
    out = struct.pack("<I", int(scan_at.timestamp())) + bytes([len(records)])
    for address, rssi in records:
        out += address + bytes([rssi + 128])
    return out


def aggregated(records: list[tuple[bytes, int, int, datetime]]) -> bytes:
    """A port 7 body: the count, then per device the octets, best rssi, sightings, best time."""
    out = bytes([len(records)])
    for address, rssi, count, best_at in records:
        out += address + bytes([rssi + 128, count]) + struct.pack("<I", int(best_at.timestamp()))
    return out


# the firmware copies bt_addr.val[0..2]; the address reads back highest octet first
ADDRESS = bytes([0x0C, 0x41, 0x0A])  # val[0], val[1], val[2] -> "0a:41:0c"


def test_a_single_scan_gives_a_contact_per_device_seen():
    records = decode(11, single([(ADDRESS, -74), (bytes([0xE1, 0x02, 0x9F]), -91)]))
    assert [c.address for c in records.contacts] == ["0a:41:0c", "9f:02:e1"]
    assert [c.rssi_dbm for c in records.contacts] == [-74, -91]
    # the scan's own time is canonical for every sighting in it, not the delivery
    assert all(c.time == SCAN_AT for c in records.contacts)
    assert all(c.sightings == 1 and c.scan_kind == "single" for c in records.contacts)


def test_the_address_keeps_its_leading_zero():
    """The reference decoder prints with toString(16) and loses it; two spellings of one address
    would otherwise become two neighbours."""
    records = decode(11, single([(bytes([0x0C, 0x41, 0x0A]), -60)]))
    assert records.contacts[0].address == "0a:41:0c"


def test_an_aggregated_scan_carries_the_count_and_the_strongest_sighting():
    best = datetime(2026, 9, 18, 9, 15, tzinfo=UTC)
    records = decode(7, aggregated([(ADDRESS, -55, 6, best)]))
    contact = records.contacts[0]
    assert contact.address == "0a:41:0c" and contact.rssi_dbm == -55
    assert contact.sightings == 6 and contact.scan_kind == "aggregated"
    # the record is about the strongest sighting, so that moment is its time
    assert contact.time == best


def test_an_empty_scan_is_kept_as_having_looked_and_seen_nothing():
    records = decode(11, single([]))
    assert records.contacts == []
    state = next(s for s in records.states if s.record_type == "ble_scan")
    assert state.state["ble_scan"] == {"seen": 0, "reported": 0, "kind": "single"}
    assert any("saw no devices" in note for note in records.notes)
    assert not records.empty, "a scan that saw nothing is still a record of having looked"


def test_a_scan_the_air_truncated_says_so():
    """Only the first message of a scan is transmitted; the rest live in the device's flash."""
    body = single([(ADDRESS, -70)])
    body = body[:4] + bytes([9]) + body[5:]  # the device saw nine, this message carries one
    records = decode(11, body)
    assert len(records.contacts) == 1
    assert any("1 of the 9" in note for note in records.notes)
    state = next(s for s in records.states if s.record_type == "ble_scan")
    assert state.state["ble_scan"]["seen"] == 9 and state.state["ble_scan"]["reported"] == 1


def test_every_device_of_a_full_scan_is_read():
    seen = [(bytes([i, 0x00, 0x10]), -40 - i) for i in range(20)]
    records = decode(11, single(seen))
    assert len(records.contacts) == 20
    assert records.contacts[19].address == "10:00:13"


def test_a_frame_too_short_for_its_header_is_a_clear_failure():
    with pytest.raises(ApplicationError):
        decode(11, b"\x01\x02")


@pytest.mark.parametrize("firmware", ["7.2", "6.15", "6.11", "4.4"])
def test_the_scan_ports_are_read_on_every_firmware_that_has_them(firmware):
    records = decode(11, single([(ADDRESS, -66)]), firmware=firmware)
    assert [c.address for c in records.contacts] == ["0a:41:0c"]


def test_a_device_address_ends_with_what_a_neighbours_scan_reports_of_it():
    """The invariant the whole of contact tracing rests on. `msg_mac_id` carries val[0..5] and a
    scan carries val[0..2]; an address written in storage order would never end with the three
    octets a neighbour reports, and no contact could be matched to the device that made it."""
    from shared.device_drivers.opencollar import format_ble_mac, scan_suffix

    val = bytes([0x0C, 0x41, 0x0A, 0x11, 0x22, 0xD4])  # val[0] .. val[5]
    mac = format_ble_mac(val)
    assert mac == "d4:22:11:0a:41:0c", "printed high octet first"
    # and that is exactly what a scan of this device says
    seen = decode(11, single([(val[:3], -70)])).contacts[0].address
    assert scan_suffix(mac) == seen == "0a:41:0c"


def test_the_device_reports_its_own_address_in_printed_order():
    """Port 31, msg 0xFD, the answer to cmd_get_mac."""
    frame = bytes([0xFD, 0x06, 0x0C, 0x41, 0x0A, 0x11, 0x22, 0xD4])
    records = driver.decode(
        SourceEventData(
            id=1,
            event_type="uplink",
            payload={"fPort": 31},
            provider_metadata={"f_port": 31},
            network_received_at=RECEIVED,
            ingested_at=RECEIVED,
            device_attributes={},
            device_type_settings={},
            frame=frame,
            f_port=31,
            firmware_version="7.2",
        )
    )
    state = next(s for s in records.states if "ble_mac" in s.state)
    assert state.state["ble_mac"] == "d4:22:11:0a:41:0c"
