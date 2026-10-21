"""The settings catalogue and the values Protect keeps per device (decisions D228 to D231):
typed decoding and encoding by the catalogue, the catalogue's facts, and the driver's generic
setting and request-settings commands."""

import json
from pathlib import Path

import pytest

from shared.control.actions import EncodeContext
from shared.device_drivers.opencollar import OpenCollarDriver, _parse_tlv, uses_families
from shared.device_drivers.opencollar.control import (
    CONTROL_ACTIONS,
    SettingNameParameters,
    SettingParameters,
)
from shared.domain.reporting import driver_catalog, driver_catalog_document
from shared.domain.reporting_rules import (
    decode_setting_value,
    decode_tlv_values,
    encode_setting_value,
)


def test_the_opencollar_catalogue_names_every_setting_with_its_facts():
    catalog = driver_catalog("opencollar", "7.3")
    assert len(catalog) >= 120
    by_name = {s["name"]: s for s in catalog}
    interval = by_name["ublox_send_interval"]
    assert interval["id"] == 2 and interval["type"] == "uint32" and interval["unit"] == "s"
    assert interval["group"] == "u-blox GNSS" and interval["since_firmware"] == "4.4.2"
    assert "disables" in interval["description"]
    assert by_name["lp0_app_key"]["since_firmware"] == "7.0.0"
    document = driver_catalog_document("opencollar", "7.3")
    assert document["firmware"] == "7.3.0" and "7.2.0" in document["versions"]
    assert "families" not in document
    assert driver_catalog("generic_json") == [] and driver_catalog_document("no_such_driver") == {}
    # the file is what the WebBLE editor reads too
    raw = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "shared/shared/device_drivers/opencollar/catalog.json"
        ).read_text()
    )
    assert {s["name"] for s in raw["settings"]} == set(by_name)


def test_the_firmware_8_catalogue_addresses_every_setting_by_family_and_id():
    """Decision D346: from firmware 7.4 a setting is a family byte and an id inside it; the
    catalogue keeps the address as one id, the two bytes beside it, and the firmware the
    device reports picks the generation (unknown is the newest)."""
    document = driver_catalog_document("opencollar", "8.1")
    assert document["firmware"] == "8.1.0" and document["applies_from"] == "7.4.0"
    assert document["families"] is True and "8.1.0" in document["versions"]
    assert document["settings_family"]["lora"] == 5 and document["settings_family"]["gps"] == 6
    by_name = {s["name"]: s for s in document["settings"]}
    eui = by_name["device_eui"]
    assert (eui["family"], eui["wire_id"], eui["id"]) == (5, 5, 0x0505)
    address = by_name["lp0_dev_addr"]
    assert (address["family"], address["wire_id"], address["id"]) == (5, 0x10, 0x0510)
    assert by_name["lp0_app_key"]["id"] == 0x050E and by_name["lp0_network_key"]["id"] == 0x050F
    assert by_name["device_name"]["id"] == 0x0206 and by_name["ublox_send_interval"]["id"] == 0x0600
    # what 7.3.0 described keeps its words; what 8 added says when it came
    interval = by_name["ublox_send_interval"]
    assert interval["unit"] == "s" and interval["group"] == "u-blox GNSS"
    assert interval["since_firmware"] == "4.4.2" and "disables" in interval["description"]
    assert by_name["lp0_master_key"]["since_firmware"] == "8.1.0"
    assert by_name["lp0_master_key"]["group"] == "LP0 companion"
    assert len({s["id"] for s in document["settings"]}) == len(document["settings"])
    commands = {c["name"]: c for c in document["commands"]}
    assert commands["cmd_send_single_setting"]["argument_length"] == 2  # family and id
    assert commands["cmd_offload_start"]["since_firmware"] == "8.1.0"
    assert all("family" not in c for c in document["commands"])
    # the generations by the firmware a device reports: 7.4 and up are the new one
    assert driver_catalog_document("opencollar", "7.3")["firmware"] == "7.3.0"
    assert driver_catalog_document("opencollar", "6.15")["firmware"] == "7.3.0"
    assert driver_catalog_document("opencollar", "7.4")["firmware"] == "8.1.0"
    assert driver_catalog_document("opencollar", "8.0")["firmware"] == "8.1.0"
    assert driver_catalog_document("opencollar", None)["firmware"] == "8.1.0"
    assert driver_catalog_document("opencollar", "garbage")["firmware"] == "8.1.0"
    assert uses_families("7.3") is False and uses_families("8.1") and uses_families(None)
    assert OpenCollarDriver.catalog("7.2")["firmware"] == "7.3.0"
    assert OpenCollarDriver.catalog()["firmware"] == "8.1.0"
    # the same names on both sides, bar what 8 added
    older = {s["name"] for s in driver_catalog("opencollar", "7.3")}
    assert older <= set(by_name)
    assert set(by_name) - older == {
        "lp0_master_key",
        "lp0_signal_checks",
        "lp0_focus_offloading",
        "lp0_statistics_interval",
    }


def test_a_firmware_8_settings_frame_is_read_by_family_and_id():
    """The wire record is `[family][id][len][value]`; the key the driver stores is the address
    as four hex digits, which the firmware 8 catalogue's ids match and the 7.3.0 catalogue's
    cannot, so neither generation's frame is misread in the other's catalogue."""
    frame = bytes.fromhex("060004100e0000" + "0505080016c001f0abcdef" + "02030101")
    assert _parse_tlv(frame, families=True) == {
        "0x0600": "100e0000",
        "0x0505": "0016c001f0abcdef",
        "0x0203": "01",
    }
    assert _parse_tlv(bytes.fromhex("0204100e0000"), families=False) == {"0x02": "100e0000"}
    newer = driver_catalog("opencollar", "8.1")
    decoded = decode_tlv_values(_parse_tlv(frame, families=True), newer)
    assert decoded["ublox_send_interval"] == {"id": 0x0600, "value": 3600, "raw_hex": "100e0000"}
    assert decoded["device_eui"]["value"] == "0016c001f0abcdef" and decoded["data_log"]["value"]
    assert (
        decode_tlv_values(_parse_tlv(frame, families=True), driver_catalog("opencollar", "7.3"))
        == {}
    )
    assert decode_tlv_values({"0x02": "100e0000"}, newer) == {}


def test_values_decode_and_encode_by_the_catalogue_type_and_range():
    catalog = driver_catalog("opencollar", "7.3")
    by_name = {s["name"]: s for s in catalog}
    interval = by_name["ublox_send_interval"]
    assert encode_setting_value(interval, 3600).hex() == "100e0000"  # the wiki's example
    assert decode_setting_value(interval, bytes.fromhex("100e0000")) == 3600
    with pytest.raises(ValueError):
        encode_setting_value(interval, 10**9)  # above the range
    flag = by_name["data_log"]
    assert (
        encode_setting_value(flag, True) == b"\x01" and decode_setting_value(flag, b"\x00") is False
    )
    name = by_name["device_name"]
    assert decode_setting_value(name, encode_setting_value(name, "Rhino")) == "Rhino"
    key = by_name["app_key"]
    hexed = "8bcd49421167dd03bad3aeea98efe409"
    assert (
        encode_setting_value(key, hexed).hex() == hexed
        and decode_setting_value(key, bytes.fromhex(hexed)) == hexed
    )
    with pytest.raises(ValueError):
        encode_setting_value(key, "abcd")  # wrong length
    decoded = decode_tlv_values({"0x02": "100e0000", "0x0b": "01", "0xfe": "aa"}, catalog)
    assert decoded["ublox_send_interval"] == {"id": 2, "value": 3600, "raw_hex": "100e0000"}
    assert decoded["data_log"]["value"] is True and len(decoded) == 2  # 0xfe is no setting


def test_the_driver_sets_any_setting_and_requests_them_all():
    older = EncodeContext(firmware_version="7.3")
    encoded = CONTROL_ACTIONS["SET_SETTING"].encode(
        SettingParameters(setting="status_send_interval", value=1800), older
    )
    assert encoded.f_port == 3 and encoded.payload.hex() == "03040807 0000".replace(" ", "")
    assert encoded.metadata == {"setting": "status_send_interval", "setting_id": 3, "value": 1800}
    with pytest.raises(ValueError):
        CONTROL_ACTIONS["SET_SETTING"].encode(SettingParameters(setting="no_such", value=1), older)
    request = CONTROL_ACTIONS["REQUEST_SETTINGS"].encode(SettingParameters.model_construct(), older)
    assert request.f_port == 32 and request.payload.hex() == "a700"
    one = CONTROL_ACTIONS["REQUEST_SETTING"].encode(
        SettingNameParameters(setting="ublox_send_interval"), older
    )
    assert one.f_port == 32 and one.payload.hex() == "a80102"
    assert one.metadata == {"requested_setting": "ublox_send_interval", "setting_id": 2}
    legacy = CONTROL_ACTIONS["SET_GNSS_INTERVAL"]
    assert (
        legacy.encode(legacy.parameters(interval_seconds=3600), older).metadata["setting_id"] == 2
    )


def test_the_driver_addresses_a_firmware_8_setting_by_family_and_id():
    """Decision D346: the same actions on a device that reported firmware 8 (or none, which
    is read as the newest) write the family byte in front of the id."""
    newer = EncodeContext(firmware_version="8.1")
    encoded = CONTROL_ACTIONS["SET_SETTING"].encode(
        SettingParameters(setting="status_send_interval", value=1800), newer
    )
    assert encoded.f_port == 3 and encoded.payload.hex() == "0201 04 08070000".replace(" ", "")
    assert encoded.metadata["setting_id"] == 0x0201
    one = CONTROL_ACTIONS["REQUEST_SETTING"].encode(
        SettingNameParameters(setting="lp0_dev_addr"), newer
    )
    assert one.payload.hex() == "a8020510" and one.metadata["setting_id"] == 0x0510
    legacy = CONTROL_ACTIONS["SET_GNSS_INTERVAL"]
    gnss = legacy.encode(legacy.parameters(interval_seconds=600), EncodeContext())
    assert gnss.payload.hex() == "0600 04 58020000".replace(" ", "")
    assert gnss.metadata == {"setting": "ublox_send_interval", "setting_id": 0x0600, "value": 600}
    new_only = CONTROL_ACTIONS["SET_SETTING"].encode(
        SettingParameters(setting="lp0_statistics_interval", value=3600), newer
    )
    assert new_only.payload.hex() == "0526 04 100e0000".replace(" ", "")
    with pytest.raises(ValueError):  # a setting of firmware 8.1 is not in the 7.3.0 catalogue
        CONTROL_ACTIONS["SET_SETTING"].encode(
            SettingParameters(setting="lp0_statistics_interval", value=3600),
            EncodeContext(firmware_version="7.3"),
        )
