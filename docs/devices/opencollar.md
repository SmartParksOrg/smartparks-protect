# OpenCollar Edge

The first comprehensive device driver (`shared/device_drivers/opencollar/`). It decodes the LoRaWAN uplinks of every OpenCollar Edge device (RangerEdge, RhinoEdge, CollarEdge, ElephantEdge, WisentEdge, FreeEdge, Fence Monitor) built from the public firmware. The complete protocol study, with byte layouts, the settings and command tables and the public decoder copied verbatim, is in [the protocol research](opencollar-protocol-research.md). This page is the reference example for driver documentation (architecture 28.12).

## Frame

Every uplink is `[msg_id][len][data]` on an FPort that selects the message type; integers are little-endian. FPort 29 has no header: it is a concatenation of stored records `[port][msg_id][len][data][store timestamp u32]`. FPorts 3 and 30 are `id, len, value` lists.

## What the driver produces

| FPort | Message | Canonical records | Canonical time |
| --- | --- | --- | --- |
| 2 | GNSS position (u-blox) | Position with altitude, accuracy, satellites, fix type and PDOP; measurements `gnss_fix`, `gnss_time_to_fix`, `gnss_satellites`, `gnss_accuracy`, `gnss_pdop`; speed and heading when active tracking is on | Fix timestamp from the receiver |
| 13, 16 | Short position, and its periodic resend | Position with accuracy. A port 16 resend of the same fix has the same canonical key and becomes a second delivery, not a second position | Fix timestamp |
| 4 | Status | Measurements `battery_voltage` (V), `charging_voltage` (V, when charging), `device_temperature` (°C), `acceleration_x/y/z` (m/s²), `uptime` (s), `lr_satellites`; a device state with reset reason, error flags, firmware and hardware version and type; a `device_error` event when an error flag is set | Network receive time (the message has no clock); the store timestamp when it comes from a flash log |
| 12 | Electric fence measurement | `fence_voltage` (V), `fence_pulse_count`, `fence_energy`; a `fence_measurement_failed` event when the measurement did not succeed | Network receive time |
| 14 | Flash status | `flash_used_percent`, `flash_messages` | Network receive time |
| 18 | Device timestamp | State `device_time`; `clock_offset` (device clock minus network time, s) | Network receive time |
| 19, 20 | External switch change and status | `switch_active`, `switch_count`; `switch_activated` and `switch_deactivated` events | Network receive time |
| 29 | Flash log | Each stored record is decoded as if it had arrived on its own port; positions keep their fix time, clockless messages take the store timestamp | Per record |
| 31 | Command confirmation, BLE MAC, requested last position | State `last_command`, state `ble_mac`, Position (firmware byte order: longitude first) | Fix timestamp for the position |
| 3, 30 | Settings and values readback | State with the raw `id: hex` list | Network receive time |
| 1, 5, 6, 7, 9, 10, 11, 15, 21, 27, 28 | LR11xx NAV, satellite lists, Wi-Fi and BLE scans, cardiac monitor, air quality, Memfault, messaging | Accepted, no canonical rows yet (later phases; the LR11xx NAV needs an external solver) | |

Unknown ports, wrong message ids and length mismatches raise `PAYLOAD_DECODE_FAILED` and land in Needs Attention.

## Deduplication

The canonical key of a position is device, fix time and record type. The same fix arrives up to three times (port 2 or 13 on the air, port 16 resend, port 29 flash log, and later WebBLE and raw log files) and is stored once with every delivery linked (ADR 0008). Positions without a valid fix (success bit clear, zero coordinates or a fix time before 2001) produce a `gnss_fix = false` measurement and nothing else.

## Metrics

All metric keys used by the driver are in the registry seeds (`shared/metrics/seeds.py`), with canonical units. Battery is reported in volts, temperature in degrees Celsius, acceleration in m/s², uptime in seconds, fence voltage in volts as the device reports it.

## Versions

The status message carries firmware and hardware version as major.minor nibbles; the patch version never reaches the air and minor versions of 16 and above wrap. The driver's `decoder_version` is `fw7.3.0`, the firmware whose protocol definition it follows. Firmware 6.x and 4.x devices speak the same layouts for the ports above; ports 8 and 17 (RF scan, open sky) of firmware up to 6.16 are not decoded.

## Known discrepancies

Documented in section 8 of the research: the course over ground byte order in port 2 (the driver follows the firmware, little-endian), the longitude and latitude order in port 31 message 0xFE (the driver follows the firmware), and the wiki's big-endian count in flash read examples.

## Control (phase 6)

Downlinks are settings on FPort 3 (`id len value`) and commands on FPort 32; `cmd_reset` is 0xA1, `cmd_send_status` 0xA4, `cmd_send_position` 0xA5. The complete command and settings tables are in the research document. Encoders arrive with the Device Control Framework in phase 6.

## Testing

`tests/shared/test_opencollar_driver.py` runs golden tests over `tests/fixtures/payloads/opencollar/uplinks.jsonl`, the wiki examples with the values the public decoder produces. Recorded uplinks from live collars are added to the same file with their origin noted in the README next to it. The ChirpStack device profile codec for the local setup is the public decoder, `shared/device_drivers/opencollar/codec.js`, passed to `scripts/dev.sh chirpstack-bootstrap --codec`.
