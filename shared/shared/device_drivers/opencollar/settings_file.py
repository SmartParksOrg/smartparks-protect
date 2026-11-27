"""The settings file of the Smart Parks ble-settings-app, read and written as the app does
(decision D426). The file is a flat JSON object of setting name to value, read from the app at
b94d3be (2026-11-26): `exportToJson` and `importFromJson` in `index.html`, `exportSettingValue`,
`normalizeDevicePinStorageValue` and `credentialSettingKeys` in `functions.js`.

- an on/off setting is `true` or `false`, a number is a number;
- a byte array is upper-case hex without separators (the app's import strips `0x`, spaces and
  commas, so those are read too);
- `device_pin` is its four digits where every byte is a digit ("1234" for 01 02 03 04), the
  hex otherwise;
- `tracker_type` and `ble_adv` are never in a file;
- the file names no firmware, no device and no date. It is keyed by name, so a file of
  firmware 7 reads against the catalogue of firmware 8 and the other way round.

Values on Protect's side are the ones `decode_setting_value` gives: a boolean, an integer, a
string, lower-case hex for a byte array.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# The value codec is imported where it is used: it lives beside the reporting rules, which
# need numpy, and the driver package stays importable without it (Protect Go, D331).

#: The settings the app calls device credentials (`credentialSettingKeys`): left out of an
#: export or an import unless its checkbox says otherwise, and out of a download for a person
#: who may not control the device (decision D429).
CREDENTIAL_KEYS: frozenset[str] = frozenset(
    {
        "app_key",
        "device_eui",
        "app_eui",
        "device_name",
        "device_pin",
        "lp0_app_key",
        "lp0_network_key",
        "lp0_dev_addr",
        "lp0_master_key",
        "s_band_app_key",
        "s_band_network_key",
        "s_band_dev_adr",
    }
)
#: Never exported and never imported by the app (`excludeFromImportExport`).
EXCLUDED_KEYS: frozenset[str] = frozenset({"tracker_type", "ble_adv"})
#: The setting that names the device a file with credentials was exported from.
IDENTITY_KEY = "device_eui"
PIN_KEY = "device_pin"

_HEX = re.compile(r"[^0-9A-Fa-f]")


@dataclass(frozen=True, slots=True)
class FileSetting:
    """One setting of a file against the catalogue: Protect's value and the bytes."""

    key: str
    setting_id: int
    value: Any
    raw_hex: str


@dataclass(slots=True)
class ParsedSettingsFile:
    settings: list[FileSetting] = field(default_factory=list)
    #: Names the catalogue of this firmware lacks; the app skips them silently, Protect names
    #: them.
    unknown: list[str] = field(default_factory=list)
    #: Names whose value does not fit the catalogue's type or range, with the reason.
    invalid: dict[str, str] = field(default_factory=dict)

    @property
    def values(self) -> dict[str, Any]:
        return {item.key: item.value for item in self.settings}


def strip_hex(value: Any) -> str:
    """The app's `stripBytes`: `0x` prefixes and everything that is no hex digit removed."""
    return _HEX.sub("", str(value).replace("0x", "").replace("0X", ""))


def _pin_hex(value: Any) -> str:
    """The app's `normalizeDevicePinStorageValue`: one to four digits are the PIN, padded to
    four and stored as one byte per digit; eight hex digits are the bytes themselves."""
    text = str(value).strip()
    if re.fullmatch(r"\d{1,4}", text):
        return "".join(f"0{digit}" for digit in text.rjust(4, "0"))
    stripped = strip_hex(text)
    if len(stripped) != 8:
        raise ValueError("a PIN of four digits, or 4 bytes as hex")
    return stripped


def _from_file(item: dict[str, Any], key: str, value: Any) -> bytes:
    from shared.domain.reporting_rules import encode_setting_value

    kind = str(item.get("type", ""))
    if isinstance(value, dict | list) or value is None:
        raise ValueError("a number, true or false, or text")
    if key == PIN_KEY:
        return encode_setting_value(item, _pin_hex(value))
    if kind == "byte_array":
        return encode_setting_value(item, strip_hex(value))
    if kind == "bool":
        if isinstance(value, str):
            value = value.strip().lower()
        if value not in (True, False, 0, 1, "true", "false", "0", "1"):
            raise ValueError("true or false")
        return encode_setting_value(item, value in (True, 1, "true", "1"))
    if kind == "string":
        return encode_setting_value(item, value)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("a number") from None
    if number != int(number):
        raise ValueError("a whole number")
    return encode_setting_value(item, int(number))


def read_settings_file(document: Any, catalog: list[dict[str, Any]]) -> ParsedSettingsFile:
    """A file's settings against a catalogue. Raises ValueError when the document is not a
    settings file at all: no JSON object, or an object without one setting any OpenCollar
    catalogue could name."""
    from shared.domain.reporting_rules import decode_setting_value

    if not isinstance(document, dict) or not document:
        raise ValueError("A settings file is a JSON object of setting names and values")
    by_name = {str(item.get("name")): item for item in catalog}
    parsed = ParsedSettingsFile()
    for key, value in document.items():
        name = str(key)
        if name in EXCLUDED_KEYS:
            continue
        item = by_name.get(name)
        if item is None:
            parsed.unknown.append(name)
            continue
        try:
            raw = _from_file(item, name, value)
        except ValueError as error:
            parsed.invalid[name] = str(error)
            continue
        parsed.settings.append(
            FileSetting(
                key=name,
                setting_id=int(item["id"]),
                value=decode_setting_value(item, raw),
                raw_hex=raw.hex(),
            )
        )
    if not parsed.settings and not parsed.invalid:
        raise ValueError("The file names no setting of this device type")
    return parsed


def _to_file(item: dict[str, Any], key: str, value: Any) -> Any:
    """The app's `exportSettingValue`."""
    kind = str(item.get("type", ""))
    if key == PIN_KEY:
        pairs = re.findall("..", strip_hex(value))
        if len(pairs) == 4 and all(pair[0] == "0" and pair[1].isdigit() for pair in pairs):
            return "".join(pair[1] for pair in pairs)
        return strip_hex(value).upper()
    if kind == "byte_array":
        return strip_hex(value).upper()
    if kind == "bool":
        return bool(value)
    if kind == "string":
        return "" if value is None else str(value)
    return int(value)


def write_settings_file(
    values: dict[str, Any], catalog: list[dict[str, Any]], *, include_credentials: bool = True
) -> dict[str, Any]:
    """Known values as the app's file, in the catalogue's order, which is the order of the
    firmware's own table as the app writes it."""
    document: dict[str, Any] = {}
    for item in catalog:
        name = str(item.get("name"))
        if name in EXCLUDED_KEYS or name not in values or values[name] is None:
            continue
        if not include_credentials and name in CREDENTIAL_KEYS:
            continue
        document[name] = _to_file(item, name, values[name])
    return document


def without_credentials(document: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in document.items() if key not in CREDENTIAL_KEYS}


def file_identity(document: dict[str, Any]) -> str | None:
    """The DevEUI a file with credentials names, as 16 lower-case hex digits; none without."""
    value = document.get(IDENTITY_KEY)
    if value is None:
        return None
    stripped = strip_hex(value).lower()
    return stripped if len(stripped) == 16 else None
