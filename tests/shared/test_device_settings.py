"""The settings catalogue and the values Protect keeps per device (decisions D228 to D231):
typed decoding and encoding by the catalogue, the catalogue's facts, and the driver's generic
setting and request-settings commands."""

import json
from pathlib import Path

import pytest

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
    catalog = driver_catalog("opencollar")
    assert len(catalog) >= 120
    by_name = {s["name"]: s for s in catalog}
    interval = by_name["ublox_send_interval"]
    assert interval["id"] == 2 and interval["type"] == "uint32" and interval["unit"] == "s"
    assert interval["group"] == "u-blox GNSS" and interval["since_firmware"] == "4.4.2"
    assert "disables" in interval["description"]
    assert by_name["lp0_app_key"]["since_firmware"] == "7.0.0"
    document = driver_catalog_document("opencollar")
    assert document["firmware"] == "7.3.0" and "7.2.0" in document["versions"]
    assert driver_catalog("generic_json") == [] and driver_catalog_document("no_such_driver") == {}
    # the file is what the WebBLE editor reads too
    raw = json.loads(
        (
            Path(__file__).resolve().parents[2]
            / "shared/shared/device_drivers/opencollar/catalog.json"
        ).read_text()
    )
    assert {s["name"] for s in raw["settings"]} == set(by_name)


def test_values_decode_and_encode_by_the_catalogue_type_and_range():
    catalog = driver_catalog("opencollar")
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
    encoded = CONTROL_ACTIONS["SET_SETTING"].encode(
        SettingParameters(setting="status_send_interval", value=1800)
    )
    assert encoded.f_port == 3 and encoded.payload.hex() == "03040807 0000".replace(" ", "")
    assert encoded.metadata == {"setting": "status_send_interval", "setting_id": 3, "value": 1800}
    with pytest.raises(ValueError):
        CONTROL_ACTIONS["SET_SETTING"].encode(SettingParameters(setting="no_such", value=1))
    request = CONTROL_ACTIONS["REQUEST_SETTINGS"].encode(SettingParameters.model_construct())
    assert request.f_port == 32 and request.payload.hex() == "a700"
    one = CONTROL_ACTIONS["REQUEST_SETTING"].encode(
        SettingNameParameters(setting="ublox_send_interval")
    )
    assert one.f_port == 32 and one.payload.hex() == "a80102"
    assert one.metadata == {"requested_setting": "ublox_send_interval", "setting_id": 2}
    legacy = CONTROL_ACTIONS["SET_GNSS_INTERVAL"]
    assert legacy.encode(legacy.parameters(interval_seconds=3600)).metadata["setting_id"] == 2
