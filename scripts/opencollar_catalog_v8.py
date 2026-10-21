#!/usr/bin/env python3
"""Build the OpenCollar driver's firmware 8 catalogue (`catalog-v8.json`) from the firmware's
own settings table and the firmware 7.3.0 catalogue beside it (decision D346).

    uv run scripts/opencollar_catalog_v8.py <path to settings.json>

The input is `scripts/settings/settings.json` of the firmware repository (the public
ble-settings-app bundles the same file per release as `settings/settings-v<version>.json`).
Firmware 7.4 and later address every setting by a family byte and an id inside the family,
and a settings record on the wire is `[family][id][len][value]`. The catalogue keeps the
address as one number, `id` = family << 8 | wire id, so every lookup by id in Protect works
as it does for the older catalogue, and `family` and `wire_id` beside it for the encoders.
Commands keep their one-byte id. Group, unit, since_firmware and the descriptions of settings
that exist in 7.3.0 are carried over by name; the settings and commands firmware 8 added get
`since_firmware` from the release they appeared in and the descriptions written below.
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "shared" / "shared" / "device_drivers" / "opencollar"
OLD = DRIVER / "catalog.json"
OUT = DRIVER / "catalog-v8.json"

FIRMWARE = "8.1.0"
#: The oldest firmware this catalogue applies to: the family format arrived in development
#: build 7.4 and shipped in 8.0.0 (the settings app's note "Open Collar 8.0.0 settings
#: migration").
APPLIES_FROM = "7.4.0"
SOURCE = (
    "scripts/settings/settings.json of the firmware branch fix/existing-lp0-implementation at "
    "7bae042 (2026-10-20), as the public ble-settings-app bundles it (settings-v8.1.0.json); "
    "group, unit, since_firmware and descriptions carried over from catalog.json (firmware "
    "7.3.0) by name; the additions of 8.0.0 and 8.1.0 described from the firmware's LP0 "
    "documentation and the settings app's release note"
)
#: What came after the settings app's 7.2.0 file, and when: one setting of 7.3.0 the older
#: catalogue carries without a version (its table lists it, the app's 7.2.0 file lacks it), and
#: the LP0 cluster settings and commands of 8.1.0 (8.0.3 holds nothing 7.3.0 lacks).
SINCE: dict[str, str] = {
    "ublox_min_satellites_timer": "7.3.0",
    "lp0_master_key": "8.1.0",
    "lp0_signal_checks": "8.1.0",
    "lp0_focus_offloading": "8.1.0",
    "lp0_statistics_interval": "8.1.0",
    "cmd_flash_clear_confirmed": "8.1.0",
    "cmd_offload_start": "8.1.0",
    "cmd_offload_cancel": "8.1.0",
}
DESCRIPTIONS: dict[str, str] = {
    "lp0_master_key": (
        "The 16-byte key every tracker and offload station of one LP0 cluster share; devices "
        "with different master keys cannot discover each other. All zeros is the firmware's "
        "default. Firmware 8.1."
    ),
    "lp0_signal_checks": (
        "Six bytes: the checks on (1), CAD veto (1), minimum RSSI check (1), minimum RSSI "
        "magnitude in dBm (100 means -100 dBm), background margin check (1), minimum margin "
        "in dB. Firmware 8.1."
    ),
    "lp0_focus_offloading": (
        "When on, routine fixes, scans and scheduled sends wait while an offload is prepared "
        "and running. Firmware 8.1."
    ),
    "lp0_statistics_interval": (
        "Seconds between an offload station's reports of itself on port 23; 0 disables them. "
        "Firmware 8.1."
    ),
    "cmd_flash_clear_confirmed": (
        "Erase whole flash sectors from the oldest records on, as long as every record in "
        "them was confirmed delivered over the given medium (or any). Firmware 8.1."
    ),
    "cmd_offload_start": (
        "Start an offload of saved records: medium (0 LP0, 1 LoRaWAN, 2 satellite, "
        "3 Bluetooth), selection (0 all, 1 confirmed, 2 unconfirmed), port (0 all, or 1 to "
        "32). Firmware 8.1."
    ),
    "cmd_offload_cancel": (
        "Cancel the running offload: the job id as uint32, or 0 for whatever runs. Firmware 8.1."
    ),
}
LP0_GROUP = "LP0 companion"


def _byte(value: Any) -> int:
    if isinstance(value, str):
        return int(value, 16)
    return int(value)


def _default(conversion: str, value: Any) -> Any:
    """A default as the older catalogue writes it: hex for a byte array, else as given."""
    if conversion == "byte_array" and isinstance(value, str):
        return "".join(re.findall(r"[0-9a-fA-F]{2}", value.replace("0x", " "))).lower()
    return value


def build(source: dict[str, Any], old: dict[str, Any]) -> dict[str, Any]:
    old_settings = {s["name"]: s for s in old["settings"]}
    old_commands = {c["name"]: c for c in old["commands"]}
    old_values = {v["name"]: v for v in old["values"]}
    settings = []
    for name, item in source["settings"].items():
        family, wire_id = _byte(item["family"]), _byte(item["id"])
        before = old_settings.get(name, {})
        conversion = str(item["conversion"])
        entry: dict[str, Any] = {
            "id": (family << 8) | wire_id,
            "family": family,
            "wire_id": wire_id,
            "name": name,
            "length": int(item["length"]),
            "type": conversion,
            "default": _default(conversion, item.get("default")),
            "min": None if conversion in ("byte_array", "string") else item.get("min"),
            "max": None if conversion in ("byte_array", "string") else item.get("max"),
            "group": before.get("group") or (LP0_GROUP if name.startswith("lp0_") else None),
            "unit": before.get("unit"),
            "since_firmware": before.get("since_firmware") or SINCE.get(name),
        }
        if entry["since_firmware"] is None:
            raise SystemExit(f"{name}: no since_firmware known; add it to SINCE")
        description = before.get("description") or DESCRIPTIONS.get(name)
        if description:
            entry["description"] = description
        settings.append(entry)
    commands = []
    for name, item in source["commands"].items():
        before = old_commands.get(name)
        description = (before or {}).get("description") or DESCRIPTIONS.get(name)
        if before is None and name not in SINCE:
            raise SystemExit(f"{name}: a command the 7.3.0 catalogue lacks; add it to SINCE")
        entry = {
            "id": _byte(item["id"]),
            "name": name,
            "argument_length": int(item.get("length", 0)),
            "description": description or "",
        }
        if name in SINCE:
            entry["since_firmware"] = SINCE[name]
        commands.append(entry)
    values = []
    for name, item in source["values"].items():
        family, wire_id = _byte(item["family"]), _byte(item["id"])
        before = old_values.get(name, {})
        values.append(
            {
                "id": (family << 8) | wire_id,
                "family": family,
                "wire_id": wire_id,
                "name": name,
                "length": int(item["length"]),
                "type": str(item["conversion"]),
                "description": before.get("description", ""),
            }
        )
    return {
        "firmware": FIRMWARE,
        "applies_from": APPLIES_FROM,
        "families": True,
        "source": SOURCE,
        "settings_family": {k: _byte(v) for k, v in source["settings_family"].items()},
        "settings": settings,
        "commands": commands,
        "values": values,
        "versions": [*old["versions"], "8.0.0", "8.0.1", "8.0.2", "8.0.3", "8.1.0"],
    }


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    source = json.loads(Path(sys.argv[1]).read_text())
    old = json.loads(OLD.read_text())
    document = build(source, old)
    OUT.write_text(json.dumps(document, indent=1) + "\n")
    print(
        f"{OUT.relative_to(ROOT)}: {len(document['settings'])} settings, "
        f"{len(document['commands'])} commands, {len(document['values'])} values"
    )


if __name__ == "__main__":
    main()
