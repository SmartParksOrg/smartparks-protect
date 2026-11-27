"""The settings file of the ble-settings-app, read and written (decision D426). No export of a
real device is at hand yet; the files here follow the app's `exportSettingValue` and
`normalizeDevicePinStorageValue` at b94d3be (2026-11-26) value by value, and its
`settings/settings-v8.2.0.json` for the names and defaults."""

import pytest

from shared.device_drivers.opencollar import OpenCollarDriver
from shared.device_drivers.opencollar.settings_file import (
    CREDENTIAL_KEYS,
    file_identity,
    read_settings_file,
    without_credentials,
    write_settings_file,
)

#: A cut of an export with credentials, as the app writes it for firmware 8.
APP_FILE = {
    "status_send_interval": 3600,
    "device_name": "SP051463",
    "device_pin": "1234",
    "led_enabled": False,
    "ublox_send_interval": 900,
    "ublox_multiple_intervals": True,
    "lr_send_flag": 4162715375,
    "app_key": "8BCD49421167DD03BAD3AEEA98EFE409",
    "device_eui": "0016C001F016D24A",
}


def _catalog(firmware: str) -> list[dict]:
    return OpenCollarDriver.catalog(firmware)["settings"]


def test_a_file_of_the_app_reads_into_the_values_protect_keeps():
    parsed = read_settings_file(APP_FILE, _catalog("8.0.3"))
    assert not parsed.unknown and not parsed.invalid
    values = parsed.values
    assert values["status_send_interval"] == 3600 and values["led_enabled"] is False
    assert values["ublox_multiple_intervals"] is True and values["device_name"] == "SP051463"
    # a byte array is lower-case hex in Protect, the PIN one byte per digit
    assert values["app_key"] == "8bcd49421167dd03bad3aeea98efe409"
    assert values["device_pin"] == "01020304"
    by_key = {item.key: item for item in parsed.settings}
    assert by_key["ublox_send_interval"].raw_hex == "84030000"
    assert by_key["ublox_send_interval"].setting_id == 0x0600  # family 6, id 0
    assert file_identity(APP_FILE) == "0016c001f016d24a"


def test_the_file_written_back_is_the_file_read():
    for firmware in ("7.2", "8.0.3"):
        catalog = _catalog(firmware)
        written = write_settings_file(read_settings_file(APP_FILE, catalog).values, catalog)
        assert written == APP_FILE
    without = write_settings_file(
        read_settings_file(APP_FILE, catalog).values, catalog, include_credentials=False
    )
    assert without == without_credentials(APP_FILE)
    assert not CREDENTIAL_KEYS & without.keys() and "ublox_send_interval" in without


def test_a_file_of_one_generation_reads_against_the_other():
    # keyed by name, so the ids of firmware 7 and 8 do not matter
    old = {
        item.key: item.setting_id for item in read_settings_file(APP_FILE, _catalog("7.2")).settings
    }
    new = {
        item.key: item.setting_id for item in read_settings_file(APP_FILE, _catalog("8.2")).settings
    }
    assert old.keys() == new.keys() and old["ublox_send_interval"] != new["ublox_send_interval"]


def test_what_the_app_reads_on_import_is_read_too():
    catalog = _catalog("8.0.3")
    loose = {
        "led_enabled": "true",
        "ublox_multiple_intervals": 0,
        "ublox_send_interval": "600",
        "app_key": "{0x8B, 0xCD, 0x49, 0x42, 0x11, 0x67, 0xDD, 0x03, "
        "0xBA, 0xD3, 0xAE, 0xEA, 0x98, 0xEF, 0xE4, 0x09}",
        "device_pin": "0A0B0C0D",
        "tracker_type": 5,  # never imported by the app
    }
    values = read_settings_file(loose, catalog).values
    assert values == {
        "led_enabled": True,
        "ublox_multiple_intervals": False,
        "ublox_send_interval": 600,
        "app_key": "8bcd49421167dd03bad3aeea98efe409",
        "device_pin": "0a0b0c0d",
    }
    # a PIN that is no four digits goes back as its hex
    assert write_settings_file(values, catalog)["device_pin"] == "0A0B0C0D"
    assert "tracker_type" not in write_settings_file({"tracker_type": 5}, catalog)


def test_unknown_names_and_values_that_do_not_fit_are_named():
    parsed = read_settings_file(
        {
            "ublox_send_interval": 900,
            "lr_enabled": True,  # firmware 8.2 has it, 7.2 has not
            "no_such_setting": 1,
            "status_send_interval": 0,  # below the minimum of 1
            "app_key": "8BCD",
            "led_enabled": "maybe",
            "gps_resend_interval": 1.5,
        },
        _catalog("7.2"),
    )
    assert parsed.values == {"ublox_send_interval": 900}
    assert parsed.unknown == ["lr_enabled", "no_such_setting"]
    assert set(parsed.invalid) == {
        "status_send_interval",
        "app_key",
        "led_enabled",
        "gps_resend_interval",
    }
    assert read_settings_file({"lr_enabled": True}, _catalog("8.2")).values == {"lr_enabled": True}


@pytest.mark.parametrize("document", [[], {}, "text", {"name": "x", "version": 2}])
def test_what_is_no_settings_file_is_refused(document):
    with pytest.raises(ValueError):
        read_settings_file(document, _catalog("8.0.3"))
