# Smart Parks OpenCollar Edge: LoRaWAN uplink and downlink protocol

Implementation-ready specification compiled on 2026-09-03 from the public Smart Parks repositories, the Smart Parks wiki and the firmware source. Applies to every device that runs the OpenCollar Edge firmware (`smartparks-opencollar-edge-fw`): CollarEdge (38 mm, 50 mm, Free, Pico, Nano), RangerEdge, FenceEdge / Fence Monitor (RangerEdge hardware plus fence board), ElephantEdge and WisentEdge (RangerEdge hardware, selectable firmware type), RhinoEdge Cube, RhinoEdge Puck35 and Puck50, ScannerEdge, HorseEdge, BaboonEdge, PangolinEdge. All of these share one protocol; the device type only changes which features are enabled and which hardware/firmware type codes appear in the status message.

Contents: 0 sources, 1 framing conventions, 2 port and message id table, 3 uplink layouts per port, 4 downlinks (settings, commands, values, full settings table), 5 decoder sources verbatim, 6 example payloads, 7 version conventions, 8 gaps and questions for the maintainer.

## 0. Sources and provenance

| Source | What it gave | Commit or date |
| --- | --- | --- |
| `https://github.com/SmartParksOrg/smartparks-opencollar-edge-fw-public` (default branch `main`) | Firmware C source (message builders, downlink parser, flash log store), `scripts/ttn_decoder.js`, `scripts/settings/settings.json`, generated headers `app/src/settings/generated_settings/*.h`, module READMEs, CHANGELOG | commit `73fa4de0b831dac488c82398a215524186c003b6`, 2026-04-10, firmware 7.3.0 (CHANGELOG `[7.3.0] - 2026-04-09`) |
| `https://github.com/SmartParksOrg/raw_logs_decoder` | `ttn_decoder-v6.11.2.js`, `-v6.14.0.js`, `-v6.15.1.js`, `-v7.2.0.js`, `field-meta.json`, raw log file handling | commit `9b10e024397ca85488a14e0175732c64ca7ac6ee`, 2026-07-08, app version v1.43 |
| `https://github.com/SmartParksOrg/smartparks-toolset` | ChirpStack v4 decoders `CSv4_Decoder_OpenCollar_Edge_v4.4.3.js`, `_v6.1.2.js`, `_v6.5.0.js`; legacy (pre-Edge) OpenCollar decoders and encoders | commit `bb98fb81a633e320154d6ac5f4e36606d403e26e`, 2024-07-27 |
| `https://github.com/SmartParksOrg/lorawan-devices` | TTN device repository entry for first generation OpenCollar (firmware 2.6, not Edge): `vendor/smart-parks/opencollar-v26.js`, profile yaml | commit `0b9139c69e760f930a668df90c2df99a0f102424`, 2021-07-08 |
| `https://github.com/SmartParksOrg/lorawan-device-profiles` | ChirpStack device profile repository fork; contains no Smart Parks or OpenCollar entry | commit `28fa4cb446d6879154389f41ab9b3514bf1f1d30`, 2025-11-11 |
| `https://github.com/SmartParksOrg/smartparks-connect-web` | Go service that encodes settings/commands downlinks for ChirpStack and RockBLOCK (`utils/bytes.go`, `web/chirpstack.go`), settings templates 2.10, 2.15, 3.2 | commit `2a279a1f0a569ef4f7ffc1c626c469b3fce519e8`, 2023-12-13 |
| `https://github.com/SmartParksOrg/ble-settings-app` | Web BLE settings app; `settings/settings-v*.json` per firmware release (4.4.2 to 7.2.0), `device-version-notes.json`, raw flash log download | cloned 2026-09-03 |
| `https://github.com/SmartParksOrg/smartparks-lp0-replay-app`, `smartparks-lp0-platform` | Semtech UDP JSONL replay and decode tools; bundle `ttn_decoder-v6.15.3.js` | cloned 2026-09-03 |
| `https://github.com/SmartParksOrg/smartparks-*-master` (collaredge_38mm_50mm, rangeredge, rhinoedge_puck35, rhinoedge_puck50, rhinoedge_cube, elephantedge, wisentedge, fence_monitor, collaredge_free, collaredge_pico) | Only README, BOM, ASM, CHANGELOG and pictures. They contain no decoders, Node-RED flows or payload documentation; they link to the (private) IRNAS repositories | cloned 2026-09-03 |
| `https://wiki.smartparks.org/devices/opencollar/lorawan_messages` | Port table, one worked example (hex, base64, decoded JSON) per uplink port | fetched 2026-09-03 |
| `https://wiki.smartparks.org/devices/opencollar/settings-and-commands` | Downlink format, flag bitmask explanation, many hex/base64 downlink examples | fetched 2026-09-03 |
| `https://wiki.smartparks.org/devices/opencollar/features`, `/firmware`, `/satellite` | Feature descriptions, BLE advertisement format, flash storage sizing, RockBLOCK downlink framing, firmware release status | fetched 2026-09-03 |

Not reachable: `https://github.com/IRNAS/gitbook-opencollar` (404, private), `https://irnas.gitbook.io/opencollar/` (401), `https://github.com/IRNAS/smartparks-opencollar-edge-fw` (private upstream of the public mirror), `smartparks-connect-app`, `smartparks-provisioning-software` (private).

Where the firmware source and the JavaScript decoder disagree, this document says so explicitly and treats the firmware as authoritative for what is on the air.

## 1. Framing conventions shared by every message

### 1.1 Uplink frame

Every application uplink is one LoRaWAN FRMPayload on an FPort in 1 to 33. The FPort identifies the message type. The payload is:

```
byte 0      msg_id      one byte message identifier (0x90 to 0xFF, see table in section 2)
byte 1      len         number of data bytes that follow (does not count the two header bytes)
byte 2..    data        len bytes, little-endian multi-byte integers unless stated otherwise
```

`MESSAGE_HEAD_LEN` is 2 (`app/src/threads/definitions.h`). The firmware calls `len` "payload length"; the GPS README states explicitly: "Payload length does not include the space used for the first two bytes (message id and payload length)". The wiki "Length" column counts the header, so for example the port 2 message is "32" in the wiki (2 header + 30 data) and `len` on the air is 0x1E.

Exceptions to the two byte header:

* FPort 29 (flash log read) carries no header at all; it is a plain concatenation of stored records, each of which begins with its own port byte (section 3.29).
* FPort 3 (settings readback) and FPort 30 (values readback) carry a sequence of `id, len, value` triples with no message id in front (sections 3.3 and 3.30).

Over Bluetooth, over the RockBLOCK satellite link and in flash storage the same frame is prefixed by one extra byte holding the port (`MESSAGE_HEAD_LEN_BT` is 3): `[port][msg_id][len][data]`. That is why the raw log files produced by the BLE app and read by `raw_logs_decoder` start with a port byte.

### 1.2 Byte order and types

* Multi-byte integers are little-endian (memcpy of native nRF52 values). Latitude, longitude and altitude are signed int32. Timestamps are unsigned uint32 Unix seconds. Floats (air quality) are IEEE 754 binary32 little-endian.
* Exceptions: the CMDQ record fields raw temperature, impedance and HRV (port 15) are big-endian because they are copied verbatim from the cardiac monitor's BLE advertisement; and the course over ground in port 2 is written little-endian by the firmware but read big-endian by the decoder (see 3.2). The BLE scan timestamps (ports 7 and 11) are written byte by byte but are still little-endian (byte idx+5 is the least significant).
* The firmware's own decoder (`Decoder(bytes, port)`) is the reference for scaling. Since firmware 6.13.0 it applies `>>> 0` to every unsigned multi-byte field; earlier decoders produced negative numbers when bit 31 was set (CHANGELOG 6.13.0: "Fix TTN decoder's multi-byte unsigned variables being interpreted as signed").

### 1.3 Which messages are actually sent, stored or relayed

Four uint32 bitmask settings decide, per port, what happens with a produced message. Bit `n-1` corresponds to FPort `n` (bit 0 is port 1). All are sent as ordinary settings on FPort 3 (`id 04 <4 bytes LE>`).

| Setting | ID | Default (fw 7.3.0) | Ports enabled by default |
| --- | --- | --- | --- |
| `lr_send_flag` (send over LoRaWAN) | 0x0C | 4162715375 = 0xF81DFEEF | see generated table in section 4.4 |
| `flash_store_flag` (store to external flash) | 0x0D | 876143 = 0x000D5E6F | see section 4.4 |
| `sat_send_flag` (queue for RockBLOCK) | 0x39 | 16522 = 0x0000408A | see section 4.4 |
| `lp0_send_flag` (send over LP0 raw LoRa) | 0x88 | 0 | none |
| `lr_join_flag` (attempt rejoin before sending) | 0x22 | 0 | none |
| `lr_confirm_flag` (send as confirmed uplink) | 0x23 | 0 | none (since 6.2.0 status messages are unconfirmed by default) |

The wiki documents older defaults (`lr_send_flag` 0xFC00066F, `flash_store_flag` 0x0400066F); the values differ per firmware release, so always read `settings.json` of the release in use.

Message production itself is driven by interval settings (for example `ublox_send_interval` 0x02, `status_send_interval` 0x03). An interval of 0 disables the producer.

### 1.4 Maximum payload

The firmware buffers are 255 bytes (`MAX_BUF_SIZE`), but the LoRaWAN stack (Semtech LoRa Basics Modem on LR1110/LR1120) reports the current maximum FRMPayload for the data rate and the firmware trims variable length messages (scan results, satellite lists, flash logs) to fit. Fixed layout messages are never split. For EU868 at DR0 that is 51 bytes, which is why the wiki says a real-time BLE scan message is at most 52 bytes and why the wiki lists "252" as the maximum for variable messages (250 data + 2 header, the maximum at DR5 and above).

### 1.5 LoRaWAN parameters

* OTAA, class A, LoRaWAN 1.0.x, Semtech LoRa Basics Modem. Device joins on boot and after `rejoin_interval` (0x35, default 3600 s). The join request is followed by a status uplink on FPort 4.
* ADR profile setting `lr_adr_profile` (0x57): 0 network controlled, 1 mobile long range, 2 mobile low power, 3 custom (default). `lr_adr` (0x0E) holds the fixed data rate 0 to 15 used with the custom profile.
* `lr_region` (0x0F) selects the frequency plan, values 1 to 13. The wiki lists the supported plans in this order: EU868, US915, AU915, WW2.4 GHz, AS923 group 1, 2, 3, 4, IN865, KR920, RU864, CN470, CN470 RP1.0. The numeric mapping is not published; 1 is EU868 (default).
* Downlinks are accepted on FPort 3 (settings), 32 (commands), 28 (messaging), 33 (LP0 commands). Firmware 6.9.0 limited processing to 3 queued downlinks per receive window.
* A downlink that requests data is answered with an uplink on the natural port of the requested message (status on 4, values on 30, settings on 3, position on 31, flash logs on 29). A command that produces no data is acknowledged with a command confirmation on FPort 31 (section 3.31).

## 2. Port and message identifier table

Generated from `scripts/settings/settings.json` and `app/src/settings/generated_settings/messages_def.h` (firmware 7.3.0). `len` is the fixed data length where the message has one; 250 means variable, up to the LoRaWAN maximum.

| FPort | Port name | Direction | msg_id | Message name | Fixed data len | Decoder function (ttn_decoder v7.2.0) |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | port_lr_gps | up | 0xF1 | msg_gnss (LR11xx GNSS NAV payload) | variable | decodeGNSSMessage |
| 2 | port_ublox_gps | up | 0xF2 | msg_ublox_location | 30 | decodeUbloxLocationMessage |
| 3 | port_settings | down and up | (none, TLV) | settings write (down), settings readback (up) | variable | not decoded |
| 4 | port_status | up | 0xF4 | msg_status | 14 | decodeStatusMessage |
| 5 | port_lr_sat_data | up | 0xF5 | msg_lr_satellites | variable | decodeLRSatellitesMessage |
| 6 | port_wifi_scan_aggregated | up | 0xF7 | msg_wifi_scan_aggregated | variable | decodeScanMessage |
| 7 | port_ble_scan_aggregated | up | 0xF9 | msg_ble_scan_aggregated | variable | decodeScanMessage |
| 8 | (removed in 7.1.0) | up | 0xFB | msg_rf_scan (RF scanner, firmware 4.x to 6.16) | variable | decodeRfScannerMessage (decoders up to 6.15.3 only) |
| 9 | port_ublox_sat_data | up | 0xF6 | msg_ublox_satellites | variable | decodeUbloxSatellitesMessage |
| 10 | port_wifi_scan | up | 0xF8 | msg_wifi_scan (single scan) | variable | decodeScanMessage |
| 11 | port_ble_scan | up | 0xFA | msg_ble_scan (single scan) | variable | decodeLastScanMessage |
| 12 | port_fence | up | 0x92 | msg_fence | 6 | decodeFence |
| 13 | port_ublox_short_message | up | 0x93 | msg_ublox_location_short | 14 | decodeUbloxLocationMessageShort |
| 14 | port_flash_status | up | 0x94 | msg_flash_status | 5 | decodeFlashStatusMessage |
| 15 | port_ble_cmdq | up | 0xFC | msg_ble_cmdq (cardiac monitor Q) | variable, 15 per record | decodeBluetoothCMDQMessage |
| 16 | port_ublox_resend_location | up | 0x95 | msg_ublox_resend_location (same layout as 13) | 14 | decodeUbloxLocationMessageShort |
| 17 | (removed in 7.1.0) | up | (n/a) | RF open sky detection (firmware 6.x) | variable | decodeOpenSkyDetection (decoders up to 6.15.3 only) |
| 18 | port_timestamp | up | 0x97 | msg_timestamp | 4 | decodeTimestamp |
| 19 | port_external_switch_detection | up | 0x98 | msg_external_switch_detection | 5 | decodeExternalSwitchMessage |
| 20 | port_external_switch_detection_status | up | 0x99 | msg_external_switch_detection_status | 5 | decodeExternalSwitchStatusMessage |
| 21 | port_air_quality | up | 0x9A | msg_air_quality (RangerEdge AirQ build only) | 20, 25 or 45 | decodeAirQualityMessage |
| 22 | port_lp0_ping | LP0 only | 0x9B | msg_lp0_ping | 14 | not decoded |
| 27 | port_memfault | up | 0x91 | msg_memfault_chunks | variable | decodedMemfault |
| 28 | port_lr_messaging | up and down | 0x90 (0xF0 with timestamp) | msg_lr_messaging | variable | decodeDeviceMessage |
| 29 | port_flash_log | up | 0xFF (not on the air) | msg_read_flash | variable, records | decodeReadFlashMessage |
| 30 | port_values | up | (none, TLV) | values readback | variable | not decoded |
| 31 | port_messages | up | 0xF3 / 0xFD / 0xFE | msg_cmd_confirm (2) / msg_mac_id (6) / msg_last_position (16) | 2 / 6 / 16 | decodeLastPosition (0xFE only) |
| 32 | port_commands | down | (none, TLV) | commands | variable | n/a |
| 33 | port_lp0_commands | LP0 only | 0x9C | msg_lp0_commands, also used for the LP0 discovery ping | variable | n/a |
| 199 | (legacy) | up | | Modem-E info message, disabled by default since 6.2.0 | | n/a |

## 3. Uplink message layouts

Offsets below are absolute byte offsets in the FRMPayload (offset 0 is `msg_id`, offset 1 is `len`), matching the index used by the JavaScript decoders. "u8/u16/u32" are unsigned, "i32" signed, all little-endian unless stated.

### 3.1 FPort 1, msg 0xF1: LR11xx GNSS NAV message

Source: `communication.c prv_compose_message_lr_gnss`, `gnss.c gnss_get_last_nav_data`.

| Offset | Size | Field | Notes |
| --- | --- | --- | --- |
| 0 | 1 | msg_id | 0xF1 |
| 1 | 1 | len | number of NAV bytes (nav_result_size) |
| 2 | 1 | NAV destination/status byte | the decoder skips it ("Skip first byte"); it is the LR11xx NAV message first byte |
| 3 | len-1 | NAV payload | opaque Semtech GNSS NAV message, hex string in decoder output `nav_payload`; to be solved with LoRa Cloud (Semtech) GNSS solver, not on the device |

Error values the wiki documents for the NAV result: 0x07 no satellites found, 0x08 almanac too old. Interval setting `lr_gps_interval` (0x01, default 0 = disabled). Command `cmd_send_lr_fix` (0xAE) triggers one scan. One message per scan; there is no multi-record form.

### 3.2 FPort 2, msg 0xF2: u-blox GNSS position (standard)

Source: `communication.c prv_get_message_ublox_position`, `gps_ublox_interface.cpp`, `app/src/gps_ublox/README.md`. Sent on every `ublox_send_interval` (0x02) whether or not the fix succeeded ("Standard message will be sent regardless if fix is invalid"). Total 32 bytes on the air.

| Offset | Size | Type | Field | Scaling and meaning |
| --- | --- | --- | --- | --- |
| 0 | 1 | u8 | msg_id | 0xF2 |
| 1 | 1 | u8 | len | 0x1E (30) |
| 2 | 1 | u8 | success | bit 0 = fix obtained (1) or not (0). In builds with outdoor detection (PangolinEdge) bit 1 = outdoor detection status. Decoder reports the whole byte as `success` |
| 3 | 1 | u8 | hot_retry | hot fix attempt counter |
| 4 | 1 | u8 | cold_retry | cold fix attempt counter |
| 5 | 2 | u16 | ttf | time to fix, seconds |
| 7 | 4 | i32 | latitude | degrees * 1e7 (u-blox native). Decoder: value / 1e7 |
| 11 | 4 | i32 | longitude | degrees * 1e7 |
| 15 | 4 | i32 | altitude | millimetres (u-blox height above ellipsoid or MSL as delivered by SparkFun library `getAltitude`). Decoder: value / 1000 = metres |
| 19 | 1 | u8 | fixType | u-blox fix type: 0 no fix, 1 dead reckoning, 2 2D, 3 3D, 4 GNSS+DR, 5 time only |
| 20 | 1 | u8 | SIV | satellites in view used |
| 21 | 2 | u16 | h_acc_est | horizontal accuracy estimate in metres (u-blox hAcc in mm divided by 1000) |
| 23 | 1 | u8 | pDOP | u-blox pDOP (0.01 units) divided by 100, integer |
| 24 | 4 | u32 | fix_timestamp | Unix seconds of the fix (from u-blox time). In an empty message from outdoor detection this is the device clock instead |
| 28 | 1 | u8 | active_t | 1 if `ublox_active_tracking` (0x2B) is on, else 0. Bytes 29 to 31 are only filled when it is 1 |
| 29 | 2 | u16 | scaled_cog | course over ground: firmware writes `(heading_1e-5deg / 1000) + 18000` little-endian with memcpy, i.e. hundredths of a degree plus 18000. Decoder computes `((bytes[29] << 8 | bytes[30]) - 18000) / 100` which reads it big-endian. This is a decoder bug; treat the field as u16 LE, degrees = (value - 18000) / 100 |
| 31 | 1 | u8 | scaled_sog | speed over ground in m/s (u-blox mm/s / 1000, truncated to u8). Decoder multiplies by 3.6 and reports `sog` in km/h; `field-meta.json` labels it m/s, which is wrong for the decoder output |

Worked example (wiki): `f21e0100001000e6a40d1f97100e03a0cb000003082f00048c61686500000000` decodes to latitude 52.0987878, longitude 5.1253399, altitude 52.128, success 1, hot_retry 0, cold_retry 0, ttf 16, fixType 3, SIV 8, h_acc_est 47, pDOP 4, fix_time 1701339532, active_t 0.

### 3.3 FPort 3: settings readback (uplink) and settings write (downlink)

Uplink on FPort 3 is the response to `cmd_send_all_settings` (0xA7) or `cmd_send_single_setting` (0xA8). Source: `settings_interface.c prv_cmd_send_all_settings / prv_cmd_send_single_setting`.

```
repeated:   setting_id (1)   length (1)   value (length bytes, LE, type per settings.json)
```

There is no message id. For `cmd_send_all_settings` the firmware fills one message up to the maximum payload and then, when it runs over Bluetooth, sends further messages and finally a command confirmation; over LoRaWAN only the first chunk is guaranteed (CHANGELOG 6.9.0: "Add sending all settings in multiple messages over Bluetooth"). The downlink format on FPort 3 is identical (section 4.1). No published decoder parses FPort 3 uplinks for Edge devices; the legacy `d_opencollar_*` decoders that handle port 3 belong to the first generation trackers, not to Edge.

### 3.4 FPort 4, msg 0xF4: status message

Source: `status.h statusData_t` (packed, 14 bytes), `status.c status_update`. Sent every `status_send_interval` (0x03, default 3600 s), after every join attempt, on `cmd_send_status` (0xA4) and `cmd_send_status_lr` (0xAD), and it is the payload of the BLE advertisement (manufacturer data 0x0A61 followed by these 14 bytes). Total 16 bytes on the air.

| Offset | Size | Field | Encoding |
| --- | --- | --- | --- |
| 0 | 1 | msg_id | 0xF4 |
| 1 | 1 | len | 0x0E (14) |
| 2 | 1 | reset | `NRF_POWER->RESETREAS & 0x0F`: bit 0 reset pin, bit 1 watchdog, bit 2 software request (also DFU and `cmd_reset`), bit 3 CPU lockup. 0 = power on |
| 3 | 1 | err | error bits: bit 0 LR11xx module error, bit 1 BLE error, bit 2 u-blox error, bit 3 accelerometer error, bit 4 battery error (below critical level), bit 5 u-blox fix failed, bit 6 flash error, bit 7 u-blox busy (not decoded) |
| 4 | 1 | bat | battery voltage: `(mV - 2500) / 10`, 0 when below 2500 mV. Decode `bat_mV = byte * 10 + 2500`. Saturates at 5050 mV |
| 5 | 1 | operation | bit 0 unread LR message waiting (`msg`), bit 1 PIN protection active (`locked`), bit 2 LoRaWAN join error (`err_lr_join`), bits 4 to 7 number of satellites seen in the last LR11xx GNSS scan (`lr_sat`, 0 to 15) |
| 6 | 1 | temp | MCU/accelerometer temperature, float in range -100 to +100 mapped to 0 to 255: `byte = (t + 100) * 255 / 200`. Decode `t = byte * 200 / 255 - 100` degrees C |
| 7 | 1 | uptime | days since boot, `k_uptime / 86400000`, u8 (wraps after 255 days) |
| 8 | 1 | acc_x | LIS2DW12 X acceleration, m/s^2, same -100..+100 mapping as temp |
| 9 | 1 | acc_y | as above |
| 10 | 1 | acc_z | as above (about -10 when Z points up, see wiki example) |
| 11 | 1 | hw_ver | hardware version, high nibble major, low nibble minor (0x14 = 1.4) |
| 12 | 1 | fw_ver | firmware version, high nibble major, low nibble minor (0x44 = 4.4). Minor versions 16 and above (6.16.x) do not fit and appear modulo 16; the patch version is never sent |
| 13 | 1 | type | high nibble firmware (tracker) type, low nibble hardware type, enumerations in section 6.2 (0x55 = rangeredge_tracker on rangeredge hardware) |
| 14 | 1 | chg | charging input voltage: 0 if below 5000 mV, else `(mV - 5000) / 100`. Decode `chg_mV = byte * 100 + 5000` when byte > 0, else 0 |
| 15 | 1 | features | bit 0 satellite (RockBLOCK) enabled, bit 1 RF scanner enabled (removed in 7.1.0), bit 2 fence enabled, bits 4 to 7 current RockBLOCK retry count (`sat_try`, max 15) |

Decoder v7.2.0 also emits `version` = "v" + fw_major + "." + fw_minor.

Worked example (wiki): `f40e0400a00095007f7f721444550000` decodes to reset 4, bat 4100, chg 0, temp 16.86, uptime 0, acc_x -0.39, acc_y -0.39, acc_z -10.59, lr_sat 0, all err_* 0, ver_fw 4.4, ver_hw 1.4, ver_hw_type 5, ver_fw_type 5, sat_support 0, sat_try 0, rf_scan 0, fence 0.

The accelerometer values here are the only accelerometer data sent over LoRaWAN by the released firmware. The LIS2DW12 FIFO capture added in 6.14.0 (`accel_movement_data_fifo_enabled` 0x73, `accel_odr_hz` 0x74, `accel_g_scale` 0x75) is not emitted as a LoRaWAN message in the public source; the `opencollar-acc-calculator` repository sketches a future motion summary payload (timestamp u32, ODBA/VeDBA i16 in mg, and so on) but no firmware or decoder implements it.

### 3.5 FPort 5, msg 0xF5: LR11xx satellite list

Source: `communication.c prv_compose_message_lr_satellites`, `gnss.c gnss_get_last_sat_data`. Sent after an LR GNSS scan when `gnss_assisted_scan`/`lr_sat_data` debug setting (0x09) is on, or on `cmd_get_lr_satellite_data` (0xB4).

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | msg_id 0xF5 |
| 1 | 1 | len = 1 + 2 * n_sat |
| 2 | 1 | n_sat (satellites detected) |
| 3 + 2i | 1 | satellite id (Semtech SV id) |
| 4 + 2i | 1 | C/N0 (cnr) in dB |

Decoder emits `N_sat`, numbered objects `1..n` with `id`, `cnr`, and `N_reported` (records that fitted).

### 3.6 FPort 6 (aggregated, msg 0xF7) and FPort 10 (single scan, msg 0xF8): Wi-Fi scan results

Source: `wifi_scan_data.c compose_message_wifi_scan_results`, `communication.c`. Interval settings `wifi_scan_interval` (0x19) and `wifi_scan_aggregated_interval` (0x1A). Records are sorted by count (aggregated) and the aggregate is limited to the top results (wiki: top 3).

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | msg_id 0xF7 (port 6) or 0xF8 (port 10) |
| 1 | 1 | len = 1 + 9 * records |
| 2 | 1 | N_wifi_res: number of distinct access points seen (may exceed the records included) |
| 3 + 9i | 3 | first three octets of the BSSID (`WIFI_SCAN_MAC_ADDRESS_STORE_LENGTH` = 3, mac[0..2] in transmission order). The decoder prints them reversed as `mac[2]:mac[1]:mac[0]` without zero padding |
| 6 + 9i | 1 | rssi + 128 (decode `byte - 128` dBm) |
| 7 + 9i | 1 | count (times seen since last aggregate) |
| 8 + 9i | 4 | timestamp u32 LE, Unix seconds of the last sighting |

Empty result messages are only sent when `wifi_scan_report_zero_connections_found` (0x48) is true. Wi-Fi scanning needs RangerEdge, CollarEdge or CollarEdge Free hardware.

### 3.7 FPort 7, msg 0xF9: BLE scan aggregated

Source: `bt_scan.c compose_message_bt_scan_results` (`SINGLE_BT_SCAN_RESULT_LEN` 9, `BT_SCAN_SEND_MAX_RES` 5). Same 9 byte record as Wi-Fi:

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | msg_id 0xF9 |
| 1 | 1 | len = 1 + 9 * records |
| 2 | 1 | N_BT_res: number of distinct devices in the buffer (up to `BT_SCAN_MAX_RES` 20) |
| 3 + 9i | 3 | `bt_addr.val[0..2]`, the three least significant octets of the BLE address (Zephyr stores addresses little-endian, so these are the last three octets as printed). Decoder prints `val[2]:val[1]:val[0]` |
| 6 + 9i | 1 | best_rssi + 128 |
| 7 + 9i | 1 | counter (sightings) |
| 8 + 9i | 4 | best_timestamp u32 LE (Unix seconds of the strongest sighting) |

At most 5 records are included (`BT_SCAN_SEND_MAX_RES`). The buffer is cleared after composing. Interval `ble_scan_aggregated_interval` (0x1D); filter `ble_scan_filter` (0x1E: 0 none, 1 Smart Parks manufacturer id 0x0A61, 2 configured `ble_scan_manufacturer_id` 0x72, 3 phones).

### 3.8 FPort 9, msg 0xF6: u-blox satellite list

Source: `communication.c prv_get_message_ublox_satellites`, `gps.c gps_get_sat_data`. Sent with every fix when debug setting `gps_sat_data` (0x0A) is true, or on `cmd_get_ublox_satellite_data` (0xB5).

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | msg_id 0xF6 |
| 1 | 1 | len = 1 + 6 * records |
| 2 | 1 | N_sat |
| 3 + 6i | 1 | satellite id (PRN) |
| 4 + 6i | 1 | C/N0 (cn0) dB |
| 5 + 6i | 1 | elevation, degrees |
| 6 + 6i | 2 | azimuth u16 LE, degrees |
| 8 + 6i | 1 | constellation: 1 GPS, 2 GLONASS, 3 combined, 4 Galileo, 5 BeiDou |

### 3.9 FPort 11, msg 0xFA: BLE single scan (real time)

Source: `bt_scan.c compose_and_send_single_scan_result_message`, `compose_message_bt_scan_result_single_scan` (`SINGLE_BT_SCAN_SHORT_LEN` 4, `BT_SCAN_RES_HEAD_LEN` 6). Interval `ble_scan_interval` (0x1C), duration `ble_scan_duration` (0x1B, ms).

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | msg_id 0xFA |
| 1 | 1 | len = 4 + 1 + 4 * records |
| 2 | 4 | scan timestamp u32 LE, Unix seconds when the scan finished (`t`) |
| 6 | 1 | N_BT_res: records in this message |
| 7 + 4i | 3 | `bt_addr.val[0..2]` (see 3.7) |
| 10 + 4i | 1 | rssi + 128 |

Up to 20 devices per scan. If more results exist than fit one LoRaWAN payload, the firmware composes further messages: they are all stored to flash but only the first one is transmitted over LoRaWAN (`res_idx == 0`). Note the decoder key for the count is `N_BT_res` and it also uses the scan time as `t`.

### 3.10 FPort 12, msg 0x92: electric fence measurement

Source: `app/src/sensors/fence_port/fence/README.md`, `fence.c`. RangerEdge hardware 1.6.0 and later with the FenceEdge board; `fence_enabled` (0x3F), `fence_interval` (0x40, seconds), `fence_sampling_length` (0x41, s), `fence_mv_scaling_factor` (0x42). Also on `cmd_fence_measure` (0xC8).

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | msg_id 0x92 |
| 1 | 1 | len 0x06 |
| 2 | 1 | success: 0 measurement ok, 1 power up failed, 2 no pulse free interval detected before timeout, 3 ADC error, 4 other |
| 3 | 1 | N: pulse count during the sampling window |
| 4 | 2 | voltage u16 LE: average peak voltage in volts (measured mV times `fence_mv_scaling_factor` / 1000; README says "average peak voltage in V") |
| 6 | 2 | energy u16 LE: average pulse energy, arbitrary units |

Example (wiki): `9206000000000000` = success 0, N 0, voltage 0, energy 0.

### 3.11 FPort 13, msg 0x93 (and FPort 16, msg 0x95): u-blox short position

Source: `communication.c prv_get_message_ublox_short`, `prv_get_message_ublox_resend_short`. Port 13 is sent only after a successful fix (alongside port 2, subject to flags). Port 16 is the periodic resend of the last known position every `gps_resend_interval` (0x0A). Total 16 bytes.

| Offset | Size | Type | Field |
| --- | --- | --- | --- |
| 0 | 1 | u8 | msg_id 0x93 (port 13) or 0x95 (port 16) |
| 1 | 1 | u8 | len 0x0E (14) |
| 2 | 4 | u32 | fix_timestamp, Unix seconds of the last valid fix (`last_position_time` value 0xE9) |
| 6 | 4 | i32 | latitude, degrees * 1e7 |
| 10 | 4 | i32 | longitude, degrees * 1e7 |
| 14 | 2 | u16 | h_acc_est, metres |

Example (wiki): `930ef9636865aba50d1f8e090e031500` = fix_timestamp 1701340153, latitude 52.0988075, longitude 5.1251598, h_acc_est 21.

### 3.12 FPort 14, msg 0x94: flash status

Source: `app/src/flash/README.md`. Periodic every `flash_status_interval` (0x43, default 0 = off since 6.12.0), or on `cmd_get_flash_status` (0xB3).

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | msg_id 0x94 |
| 1 | 1 | len 0x05 |
| 2 | 1 | percentage of flash used (0 to 100) |
| 3 | 4 | n_msg u32 LE: number of messages stored in flash |

Example (wiki): `94050010000000` = percentage 0, n_msg 16.

### 3.13 FPort 15, msg 0xFC: cardiac monitoring device Q (CMDQ) results

Source: `bt_cmdq_messaging.c`, `app/src/bt_module/bt_cmdq/README.md`. One record per received BLE advertisement of the configured CMDQ MAC (`cmdq_searched_mac_address` 0x4D); reporting interval `cmdq_reporting_interval` (0x4E). Record length 13 bytes in firmware 6.1 to 6.8, 15 bytes since 6.9.0 (HRV added). Decoder v6.5.0 assumes 13, decoders 6.9.0 and later assume 15. The record is a 4 byte timestamp followed by the "important data" bytes copied verbatim from the CMDQ advertisement, so field byte order is the CMDQ device's (big-endian).

| Offset in record | Size | Field | Decode |
| --- | --- | --- | --- |
| 0 | 4 | cmdq_timestamp u32 LE (Unix seconds of the sighting) | |
| 4 | 1 | rr_median | R-R interval median, tens of ms |
| 5 | 1 | rr_median_modesum | |
| 6 | 1 | activity_average | |
| 7 | 1 | activity_max | |
| 8 | 1 | active_min_in_last_hour | |
| 9 | 2 | raw_temperature, big-endian (byte 9 high, byte 10 low) | temperature C = raw * 0.0248 - 18.09; `cmdq_success` = 1 when raw > 0 |
| 11 | 2 | h_impedance, big-endian | |
| 13 | 2 | hrv_raw, big-endian (since fw 6.9.0) | `cmdq_hrv` = sqrt(hrv_raw) |

Frame: `FC len records...` with `len = 15 * n`. Empty report `FC 00` when `cmdq_report_zero_messages_to_be_sent` (0x50) is on. The meaning of the CMDQ "important data" is documented only in the private IRNAS issue #389.

### 3.14 FPort 18, msg 0x97: device timestamp

Response to `cmd_send_timestamp` (0xCE, since 6.9.0). `97 04 <u32 LE Unix seconds from get_global_unix_time()>`. Useful to check the clock that stamps flash records.

### 3.15 FPort 19, msg 0x98 and FPort 20, msg 0x99: external switch

Source: `app/src/sensors/fence_port/external_switch/README.md` (since 6.13.0; RangerEdge fence port). Both are 7 bytes.

Port 19, state change (immediate): `98 05 [activity u8: 1 became active, 0 became inactive] [duration_ms u32 LE: length of the activity or inactivity period that just ended]`.

Port 20, periodic status every `external_switch_detection_reporting_interval` (0x81): `99 05 [state u8] [count u32 LE]`. When state is 0 or 1 the count is the number of inactive to active transitions in the interval (`num_of_active_detections`). When state is 2 the device is in impulse counter mode (`external_switch_counter_enabled` 0x85) and the count is `impulse_count`.

### 3.16 FPort 21, msg 0x9A: air quality (RangerEdge AirQ special firmware)

Source: `ttn_decoder.js decodeAirQualityMessage`, `app/src/sensors/air_quality/README.md`. Data are IEEE 754 float32 little-endian.

BMV080 block (25 bytes): pm2_5_mass, pm1_mass, pm10_mass (ug/m3), pm2_5_num, pm1_num, pm10_num (particles/cm3), then `is_obstructed` u8.
BME690 block (20 bytes): IAQ index, temperature C, pressure Pa, relative humidity, raw gas resistance ohm.

The decoder branches on `len`: len < 27 and > 2: BME690 block only at offset 2; len == 27: BMV080 block only at offset 2; 27 < len < 48: BMV080 at offset 2 then BME690 at offset 27; len == 2 or len > 47: no data. (These thresholds imply the firmware counts the header in `len` for this message: 25 + 2 = 27 and 45 + 2 = 47; `settings.json` gives the message length as 47.)

### 3.17 FPort 22, msg 0x9B: LP0 ping and FPort 33: LP0 commands

LP0 (firmware 7.2.0) is a raw LoRa mode with LoRaWAN ABP framing used for offloading flash logs to a local "offload station"; it is not sent to the LoRaWAN network server. The discovery ping actually sent by `lp0_offload.c prv_lp0_discovery_ping_send` uses FPort 33 with payload `03 0E [last_position_time u32][lat i32][lon i32]` (msg_id byte is written as 0x03, not 0x9B). Downlinks on FPort 33 are LP0 commands (`lp0_command_parser`: byte 0 command type, `LP0_CMD_SET_MODE` takes one mode byte). Experimental; ignore for a LoRaWAN integration.

### 3.18 FPort 27, msg 0x91: Memfault chunks

`91 len <opaque Memfault chunk bytes>`. Forward the bytes to Memfault; nothing to decode. Interval `memfault_send_interval` (0x34, default 0).

### 3.19 FPort 28, msg 0x90: device to server text message (LR messaging)

Source: `lr_messaging.c`, decoder `decodeDeviceMessage`. Queued by `cmd_send_lr_message` (0xC4, up to 46 bytes of text) and retried per `lr_messaging_retry_interval` (0x31) and `lr_messaging_retry_count` (0x32).

| Offset | Size | Field |
| --- | --- | --- |
| 0 | 1 | msg_id 0x90 |
| 1 | 1 | len = msg_len + 3 |
| 2 | 1 | msg_len |
| 3 | msg_len | message bytes (ASCII) |
| 3 + msg_len | 1 | seq (message sequence number) |
| 4 + msg_len | 1 | retry (attempt number) |

Example (wiki): `900d0a736d6172747061726b730101` = len 13, msg_len 10, msg "smartparks", seq 1, retry 1. A msg_id 0xF0 variant (`msg_lr_messaging_timestamp`) exists in the message table for a timestamped form, but no decoder handles it. Downlinks on FPort 28 are stored as incoming messages for the BLE app (`handle_lora_recv` routes them to `lr_messaging_store_incoming`); the status message bit `msg` then goes to 1 and value `n_mes` (0xEB) counts them.

### 3.20 FPort 29: flash log read (history records with embedded timestamps)

This is the message that carries older records with their own device timestamps inside a later uplink.

Source: `flash_interface.c prv_flash_store_message` (store), `prv_read_messages_from_head` and `prv_read_block` (read), `prv_send_payload` (send), decoder `decodeReadFlashMessage`.

Storage record format in external flash (written when a message's port bit is set in `flash_store_flag`):

```
port (1)   msg_id (1)   len (1)   data (len bytes, the message exactly as it would go on the air)   timestamp (4, u32 LE)
```

* The timestamp is `get_global_unix_time()` at the moment the record is stored, in Unix seconds (epoch 1970-01-01 UTC). It is the device clock, which is derived from the last u-blox fix time (the wiki example shows store timestamps 7 to 9 s after `fix_timestamp`), from `init_time` (setting 0x07, default 1606314575) plus uptime before any fix, or from `cmd_set_location_and_time` (0xAF). It is therefore only as good as the device clock; for position records prefer the `fix_timestamp` inside the record.
* `FLASH_HEAD_SIZE` = 3 (port, id, len), `TIMESTAMP_SIZE` = 4, so a record costs len + 7 bytes (the wiki's "37 bytes" for a port 2 message and "21 bytes" for status).
* Flash is a FIFO ring; oldest records are overwritten when full (4 MB, 16 MB or 32 MB depending on PCB).

On-air format of the FPort 29 uplink: records are concatenated back to back with no message id and no length prefix:

```
[port id len data... ts(4)] [port id len data... ts(4)] ...
```

The firmware appends records to a payload buffer and flushes it when the next record would not fit the current maximum LoRaWAN payload (`prv_check_payload_send`), so the number of records per uplink is `floor(max_payload / (len + 7))`: 10 records of a port 13 message (23 bytes each) in the wiki example (230 bytes at DR5), 1 record of a 32 byte port 2 message at DR0 (51 bytes), 2 at DR3 (115 bytes). Over LoRaWAN reads are done in batches of 6 messages (`FLASH_READ_NUM_OF_MESSAGES_PER_BATCH`), and the flash thread waits for an internal confirmation carrying the new maximum payload length before composing the next uplink.

Decoder algorithm (`decodeReadFlashMessage`): `i = 0; while (i < bytes.length - 7) { port = bytes[i]; len = bytes[i+2]; msg = bytes.slice(i+1, i+len+3) /* id, len, data */; i += len + 3; ts = u32le(bytes, i); i += 4; record = { data: port == 29 ? {} : Decoder(msg, port), port, timestamp: ts } }`. Output keys are "1", "2", ... (ChirpStack variants name the port field `fPort`).

Requests (downlink on FPort 32):

* `BB 01 <port>`: `cmd_flash_get_all` (0xBB), all stored records of one port (0 = all ports; over LoRaWAN the firmware reads them in batches).
* `BC 0C <port u32 LE> <start u32 LE> <count u32 LE>`: `cmd_flash_get_from_head` (0xBC), `count` records of `port` starting `start` records back from the newest (head). `start` 0 and `count` N returns the newest N. Firmware 4.4.2 to 6.15.x had a bug where the start index was shifted by the requested count (fixed in 7.1.0; `ble-settings-app/device-version-notes.json`).
* `BA 00`: `cmd_flash_clear` (0xBA).
* Responses to these commands end with a command confirmation on FPort 31.

Worked example (wiki, hex `0D930E3C636865FCA10D1F7D160E030C00436368650D930EF9636865...`): first record port 0x0D (13), id 0x93, len 0x0E, data `3C636865 FCA10D1F 7D160E03 0C00` (fix 1701339964, lat 52.0987132, lon 5.1254909, h_acc 12), store timestamp `43636865` = 1701339971.

The same record stream also appears in the raw log `.txt` files exported by the BLE web app: each line is one BLE notification frame, base64 encoded, beginning with the port byte 29 (0x1D) followed by the records; `raw_logs_decoder` strips the first byte as port and passes the rest to `Decoder(bytes, port)`.

### 3.21 FPort 30: values readback

Response to `cmd_send_all_val` (0xA2) or `cmd_send_single_val` (0xA3 with one byte value id). Same TLV format as FPort 3: `value_id (1) length (1) value (length bytes LE)` repeated, no message id. Value ids 0xD0 to 0xEF (table in section 4.3). Floats (`lis2_acc_*`, `mcu_temp`) are 4 byte IEEE 754 LE. No published decoder parses FPort 30.

### 3.22 FPort 31: predefined response messages

Three messages share this port; distinguish them by `msg_id`.

msg 0xF3 `msg_cmd_confirm` (source `thread_com.c compose_response_msg`), 4 bytes: `F3 02 <cmd_id> <status>` where status 1 = executed, 0 = error. Sent after commands that return no data (reset GPS, flash clear, flash reads finished, settings write actions, and so on).

msg 0xFD `msg_mac_id`, 8 bytes: `FD 06 <6 byte BLE MAC, val[0..5]>`, response to `cmd_get_mac` (0xB7).

msg 0xFE `msg_last_position`, 18 bytes, response to `cmd_send_position` (0xA5):

| Offset | Size | Type | Field (firmware order) |
| --- | --- | --- | --- |
| 0 | 1 | | msg_id 0xFE |
| 1 | 1 | | len 0x10 |
| 2 | 4 | i32 | longitude, degrees * 1e7 (`gps_lon`) |
| 6 | 4 | i32 | latitude, degrees * 1e7 (`gps_lat`) |
| 10 | 4 | i32 | altitude, mm (`gps_alt`) |
| 14 | 4 | u32 | fix_time, Unix seconds (`last_position_time`) |

The firmware (`prv_cmd_send_position`) writes longitude first and latitude second. The decoder (`decodeLastPosition`) and the wiki snippet read bytes 2 to 5 as latitude and 6 to 9 as longitude, so they swap the two. Trust the firmware order.

### 3.23 Legacy ports 8, 17 and 199

Port 8 (msg 0xFB, RF scanner, firmware 4.x to 6.16): `FB len version(1) should_alert(1) [start_MHz*10 u16 LE, stop_MHz*10 u16 LE, peak_count u8, max_rssi (negated) u8] * n`. Port 17 (open sky detection, 6.x): `len` then pairs of `average_rssi`, `max_rssi` as negated u8. Both removed in firmware 7.1.0 and absent from decoder 7.2.0; decoders 6.15.x still contain them. Port 199 was the Modem-E info message, disabled by default since 6.2.0.

## 4. Downlink commands and settings

### 4.1 Settings write (FPort 3)

Source: `settings_interface.c parse_settings_message` and `prv_execute_message`; wiki settings-and-commands page.

```
repeated:  setting_id (1)   length (1)   value (length bytes, little-endian)
```

* Several settings may be stacked in one downlink; the parser loops until the payload is consumed. A length larger than the setting's defined length is rejected; the value is range checked against `min`/`max` and rejected silently if invalid (logged only).
* Types (`conversion`): `uint8`, `uint16`, `uint32`, `int8`, `int16`, `int32` little-endian; `bool` one byte 0/1; `byte_array` raw bytes (keys, MAC, PIN); `string` ASCII padded to the declared length; `float` IEEE 754 LE (only used for values, not settings).
* The new value is written to NVS immediately. Some settings trigger an action (for example `fence_enabled` updates the status feature bit, `ble_adv` restarts advertising) and may return a confirmation on FPort 31.
* Settings can also be written with a length of 0 to execute the "message of zero length" path; only meaningful for commands.
* Example (wiki): set `ublox_send_interval` to 3600 s: `02 04 10 0E 00 00` (base64 `AgQQDgAA`). Set `status_send_interval` to 1800 s: `03 04 08 07 00 00` (`AwQIBwAA`).

### 4.2 Commands (FPort 32)

```
repeated:  cmd_id (1)   length (1)   argument bytes (length bytes, little-endian)
```

A command with no argument is `cmd_id 00`. Responses go to the channel the command arrived on; over LoRaWAN that means an uplink on the natural port (see table). Commands and settings must not be mixed in one downlink because the port selects the parser.

Command table (firmware 7.3.0, `commands_def.h` and `settings.json`):

| ID | Name | Arg len | Argument and response |
| --- | --- | --- | --- |
| 0xA0 | `cmd_join` | 0 | Rejoin the LoRaWAN network. Response: status uplink on FPort 4 after join |
| 0xA1 | `cmd_reset` | 0 | Reboot the device (sys_reboot). No response |
| 0xA2 | `cmd_send_all_val` | 0 | Response: all values as TLV on FPort 30 |
| 0xA3 | `cmd_send_single_val` | 1 | arg: value id (0xD0..0xEF). Response: `id len value` on FPort 30 |
| 0xA4 | `cmd_send_status` | 0 | Response: status message on FPort 4 to the requesting channel |
| 0xA5 | `cmd_send_position` | 0 | Response: msg_last_position 0xFE on FPort 31 |
| 0xA6 | `cmd_reset_gps` | 0 | Power cycle the u-blox module. Response: cmd confirm on FPort 31 |
| 0xA7 | `cmd_send_all_settings` | 0 | Response: settings TLV on FPort 3 (first chunk over LoRaWAN) |
| 0xA8 | `cmd_send_single_setting` | 1 | arg: setting id. Response: `id len value` on FPort 3 |
| 0xA9 | `cmd_reset_initial_position` | 1 | arg: 1 byte. Reset stored reference position to gps_init_lon/lat |
| 0xAA | `cmd_reset_initial_time` | 0 | Reset device clock from init_time setting |
| 0xAB | `cmd_clear_nvs` | 0 | Erase all stored settings (factory reset of NVS) |
| 0xAC | `cmd_reset_to_def_settings` | 0 | Restore settings.json defaults |
| 0xAD | `cmd_send_status_lr` | 0 | Force a status uplink over LoRaWAN regardless of origin |
| 0xAE | `cmd_send_lr_fix` | 0 | Perform LR11xx GNSS scan now. Response: FPort 1 (and 5) |
| 0xAF | `cmd_set_location_and_time` | 12 | arg: lon i32 (deg*1e7), lat i32, unix time u32, 12 bytes LE. Seeds assisted GNSS and the clock |
| 0xB1 | `cmd_get_wifi_scan` | 0 | Perform Wi-Fi scan now. Response: FPort 10 (and 6) |
| 0xB2 | `cmd_get_ble_scan` | 0 | Perform BLE scan now. Response: FPort 11 |
| 0xB3 | `cmd_get_flash_status` | 0 | Response: FPort 14 |
| 0xB4 | `cmd_get_lr_satellite_data` | 0 | Response: FPort 5 |
| 0xB5 | `cmd_get_ublox_satellite_data` | 0 | Response: FPort 9 |
| 0xB6 | `cmd_almanac_update` | 250 | arg: up to 250 bytes, stacked 20 byte almanac chunks (byte 0 of each chunk is the SV id, 128 = header; update executes when header received) |
| 0xB7 | `cmd_get_mac` | 0 | Response: msg_mac_id 0xFD on FPort 31 |
| 0xB8 | `cmd_get_ublox_fix` | 0 | Perform u-blox fix now. Response: FPort 2 (fixed for LoRaWAN in 6.4.0) |
| 0xB9 | `cmd_reset_lr` | 0 | Reset the LR11xx modem |
| 0xBA | `cmd_flash_clear` | 0 | Erase flash log. Response: cmd confirm FPort 31 |
| 0xBB | `cmd_flash_get_all` | 1 | arg: port (0 = all). Response: FPort 29 records, then cmd confirm |
| 0xBC | `cmd_flash_get_from_head` | 12 | arg: port u32, start u32, count u32 (12 bytes LE). Response: FPort 29 records, then cmd confirm |
| 0xBD | `cmd_s_band_send` | 0 | Send status and short position over S-band (RangerEdge 1.7+ only) |
| 0xBE | `cmd_set_operation_mode_com_th` | 1 | arg: mode byte for the communication thread (debug) |
| 0xBF | `cmd_disable_flash_th` | 0 | Disable the flash thread |
| 0xC0 | `cmd_disable_bt_th` | 0 | Disable Bluetooth |
| 0xC1 | `cmd_set_operation_mode_main_th` | 1 | arg: mode byte for the main thread (debug) |
| 0xC2 | `cmd_check_pin` | 16 | arg: 16 bytes (PIN or AppKey) to unlock a PIN protected device (BLE use) |
| 0xC3 | `cmd_set_hibernation_mode` | 0 | Enter hibernation (everything off until magnet). Wiki: `C3 00`, base64 `wwA=` |
| 0xC4 | `cmd_send_lr_message` | 46 | arg: up to 46 ASCII bytes, queued as FPort 28 uplink (msg 0x90) |
| 0xC5 | `cmd_read_all_lr_messages` | 0 | Deliver stored incoming messages (BLE use) |
| 0xC6 | `cmd_send_sat_buffer` | 0 | Flush the RockBLOCK send buffer now (adds a status message if empty) |
| 0xC7 | `cmd_lp0_command` | 1 | arg: 1 byte LP0 command (experimental) |
| 0xC8 | `cmd_fence_measure` | 1 | arg: 1 byte. Perform fence measurement now. Response: FPort 12 |
| 0xC9 | `cmd_aggregated_bt_scan` | 0 | Compose and send BLE aggregated message now. Response: FPort 7 |
| 0xCA | `cmd_single_bt_scan` | 0 | Perform BLE scan now. Response: FPort 11 |
| 0xCB | `cmd_bt_disconnect` | 0 | Drop the current BLE connection |
| 0xCC | `cmd_send_bt_cmdq_results` | 0 | Send latest CMDQ results. Response: FPort 15 |
| 0xCD | `cmd_decouple_collar` | 0 | CollarEdge drop-off: powers the P3 connector for 5 s. Wiki: `CD 00` |
| 0xCE | `cmd_send_timestamp` | 0 | Response: msg_timestamp 0x97 on FPort 18 |

Commands present in older firmware and in the wiki but not in 7.3.0: `cmd_get_rf_scan` 0xB0 and `cmd_pause_rf_scan` 0xC7 (RF scanner, removed 7.1.0; 0xC7 is now `cmd_lp0_command`). The pre-Edge trackers used a different command port (99) with single byte commands 0xAB reset, 0xDE rejoin, 0xAA send settings (see legacy encoders in section 5.6).

### 4.3 Values readable with cmd_send_single_val / cmd_send_all_val (FPort 30)

| ID | Name | Len | Type | Meaning |
| --- | --- | --- | --- | --- |
| 0xD0 | `reset_reason` | 4 | uint32 | NRF_POWER RESETREAS register |
| 0xD1 | `gps_lon` | 4 | int32 | last fix longitude deg*1e7 |
| 0xD2 | `gps_lat` | 4 | int32 | last fix latitude deg*1e7 |
| 0xD3 | `gps_alt` | 4 | int32 | last fix altitude mm |
| 0xD4 | `lis2_acc_x` | 4 | float | m/s^2 |
| 0xD5 | `lis2_acc_y` | 4 | float | m/s^2 |
| 0xD6 | `lis2_acc_z` | 4 | float | m/s^2 |
| 0xD7 | `batt_mV` | 4 | int32 | battery mV |
| 0xD8 | `ublox_time` | 4 | uint32 | last u-blox time (unix) |
| 0xD9 | `lr_satellites` | 1 | uint8 | satellites in last LR scan |
| 0xDA | `mcu_temp` | 4 | float | degrees C |
| 0xDB | `charge_mV` | 4 | int32 | charging input mV |
| 0xDC | `gps_h_acc_est` | 2 | uint16 | m |
| 0xE8 | `flash_nr_msg` | 4 | uint32 | records in flash |
| 0xE9 | `last_position_time` | 4 | uint32 | unix time of last valid fix |
| 0xEA | `last_accel_int_time` | 4 | uint32 | unix time of last accelerometer interrupt |
| 0xEB | `n_mes` | 1 | uint8 | unread incoming LR messages |
| 0xEC | `almanac_age` | 2 | uint16 | days since GPS epoch 2019-04-07 (wiki) |
| 0xED | `factory_device_name` | 8 | string | 8 ASCII bytes |
| 0xEF | `satellite_resend_try` | 1 | uint8 | current RockBLOCK retry |

### 4.4 Complete settings table (FPort 3), firmware 7.3.0

Defaults, ranges and types from `scripts/settings/settings.json` at commit 73fa4de. Intervals are seconds unless the name says ms or hz. `ble-settings-app/settings/settings-v*.json` holds the same table for each earlier release (4.4.2, 5.0.1, 6.8.1 to 7.2.0); ids are stable across releases, new ids are appended, removed features leave gaps (0x3C to 0x3E, 0x51, 0x53 to 0x56, 0x58 to 0x5E, 0x6F to 0x71 were RF scan, open sky and satellite settings).

| ID | Name | Len | Type | Default | Min | Max |
| --- | --- | --- | --- | --- | --- | --- |
| 0x00 | `tracker_type` | 1 | uint8 | 0 | 0 | 15 |
| 0x01 | `lr_gps_interval` | 4 | uint32 | 0 | 0 | 86400 |
| 0x02 | `ublox_send_interval` | 4 | uint32 | 0 | 0 | 172800 |
| 0x03 | `status_send_interval` | 4 | uint32 | 3600 | 1 | 86400 |
| 0x04 | `satellite_send_interval` | 4 | uint32 | 86400 | 0 | 86400 |
| 0x05 | `gps_init_lon` | 4 | int32 | 156447700 | -1800000000 | 1800000000 |
| 0x06 | `gps_init_lat` | 4 | int32 | 465556280 | -900000000 | 900000000 |
| 0x07 | `init_time` | 4 | uint32 | 1606314575 | 1606314575 | 4294967295 |
| 0x08 | `ble_adv` | 1 | bool | True | False | True |
| 0x09 | `gnss_assisted_scan` | 1 | bool | False | False | True |
| 0x0A | `gps_resend_interval` | 4 | uint32 | 0 | 0 | 86400 |
| 0x0B | `data_log` | 1 | bool | True | False | True |
| 0x0C | `lr_send_flag` | 4 | uint32 | 4162715375 | 0 | 4294967295 |
| 0x0D | `flash_store_flag` | 4 | uint32 | 876143 | 0 | 4294967295 |
| 0x0E | `lr_adr` | 1 | uint8 | 3 | 0 | 15 |
| 0x0F | `lr_region` | 1 | uint8 | 1 | 1 | 13 |
| 0x10 | `app_key` | 16 | byte_array | `{0x8B,0xCD,0x49,0x42,0x11,0x67,0xDD,0x03,0xBA,0xD3,0xAE,0xEA,0x98,0xEF,0xE4,0x09}` |  |  |
| 0x11 | `device_eui` | 8 | byte_array | `{0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00}` |  |  |
| 0x12 | `app_eui` | 8 | byte_array | `{0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00}` |  |  |
| 0x13 | `horizontal_accuracy` | 4 | uint32 | 50 | 1 | 1000 |
| 0x14 | `cold_fix_retry` | 1 | uint8 | 200 | 1 | 255 |
| 0x15 | `hot_fix_retry` | 1 | uint8 | 4 | 1 | 255 |
| 0x16 | `cold_fix_timeout` | 2 | uint16 | 200 | 1 | 600 |
| 0x17 | `hot_fix_timeout` | 2 | uint16 | 65 | 1 | 600 |
| 0x18 | `ble_advertisement_interval` | 4 | uint32 | 500 | 100 | 10000 |
| 0x19 | `wifi_scan_interval` | 4 | uint32 | 0 | 0 | 86400 |
| 0x1A | `wifi_scan_aggregated_interval` | 4 | uint32 | 0 | 0 | 86400 |
| 0x1B | `ble_scan_duration` | 4 | uint32 | 600 | 50 | 10000 |
| 0x1C | `ble_scan_interval` | 4 | uint32 | 0 | 0 | 86400 |
| 0x1D | `ble_scan_aggregated_interval` | 4 | uint32 | 0 | 0 | 86400 |
| 0x1E | `ble_scan_filter` | 1 | uint8 | 1 | 0 | 3 |
| 0x1F | `ble_auto_disconnect` | 4 | uint32 | 600 | 0 | 86400 |
| 0x20 | `s_band_send_interval` | 4 | uint32 | 0 | 0 | 604800 |
| 0x21 | `device_name` | 8 | string | `` |  |  |
| 0x22 | `lr_join_flag` | 4 | uint32 | 0 | 0 | 4294967295 |
| 0x23 | `lr_confirm_flag` | 4 | uint32 | 0 | 0 | 4294967295 |
| 0x24 | `lr_max_confirm_fail` | 2 | uint16 | 0 | 0 | 1000 |
| 0x25 | `gps_backoff_factor` | 1 | uint8 | 10 | 10 | 100 |
| 0x26 | `ublox_send_interval_2` | 4 | uint32 | 0 | 0 | 86400 |
| 0x27 | `ublox_interval1_start` | 1 | uint8 | 11 | 0 | 23 |
| 0x28 | `ublox_min_fix_time` | 1 | uint8 | 5 | 0 | 30 |
| 0x29 | `ublox_multiple_intervals` | 1 | bool | False | False | True |
| 0x2A | `device_pin` | 4 | byte_array | `{0x00,0x00,0x00,0x00}` |  |  |
| 0x2B | `ublox_active_tracking` | 1 | bool | False | False | True |
| 0x2C | `led_enabled` | 1 | bool | True | False | True |
| 0x2D | `motion_ths` | 1 | uint8 | 6 | 0 | 63 |
| 0x2E | `enable_motion_trig_gps` | 1 | bool | False | False | True |
| 0x2F | `gps_triggered_interval` | 4 | uint32 | 60 | 0 | 86400 |
| 0x30 | `gps_skipped_triggered_interval` | 1 | uint8 | 5 | 0 | 255 |
| 0x31 | `lr_messaging_retry_interval` | 4 | uint32 | 60 | 0 | 86400 |
| 0x32 | `lr_messaging_retry_count` | 1 | uint8 | 1 | 1 | 5 |
| 0x33 | `ublox_leave_on` | 1 | uint8 | 15 | 0 | 60 |
| 0x34 | `memfault_send_interval` | 4 | uint32 | 0 | 0 | 86400 |
| 0x35 | `rejoin_interval` | 4 | uint32 | 3600 | 600 | 86400 |
| 0x36 | `check_error_interval` | 4 | uint32 | 86400 | 0 | 2678400 |
| 0x37 | `gnss_constellation_to_use` | 1 | uint8 | 3 | 1 | 3 |
| 0x38 | `ublox_min_satellites_timer` | 1 | uint8 | 30 | 5 | 255 |
| 0x39 | `sat_send_flag` | 4 | uint32 | 16522 | 0 | 4294967295 |
| 0x3A | `satellite_enabled` | 1 | bool | False | False | True |
| 0x3B | `satellite_retry` | 1 | uint8 | 10 | 1 | 15 |
| 0x3F | `fence_enabled` | 1 | bool | False | False | True |
| 0x40 | `fence_interval` | 4 | uint32 | 60 | 0 | 604800 |
| 0x41 | `fence_sampling_length` | 2 | uint16 | 10 | 1 | 60 |
| 0x42 | `fence_mv_scaling_factor` | 4 | uint32 | 100000 | 100 | 1000000 |
| 0x43 | `flash_status_interval` | 4 | uint32 | 0 | 0 | 604800 |
| 0x44 | `lp0_app_key` | 16 | byte_array | `{0xEC,0x7F,0x38,0x0E,0x7A,0xDF,0xB2,0xE5,0xC9,0xBB,0xDE,0x5A,0xC2,0x16,0x94,0xA8}` |  |  |
| 0x45 | `lp0_network_key` | 16 | byte_array | `{0xDB,0x7E,0x27,0x26,0xCF,0xF5,0x8C,0x13,0x3A,0x07,0xB5,0xA1,0xB4,0x00,0xE1,0xD0}` |  |  |
| 0x46 | `lp0_dev_addr` | 4 | byte_array | `{0x26,0x0B,0xF6,0xEF}` |  |  |
| 0x47 | `ble_scan_report_zero_connections_found` | 1 | bool | False | False | True |
| 0x48 | `wifi_scan_report_zero_connections_found` | 1 | bool | False | False | True |
| 0x49 | `cmdq_enabled` | 1 | bool | False | False | True |
| 0x4A | `cmdq_scan_duration` | 4 | uint32 | 10000 | 1 | 10000 |
| 0x4B | `cmdq_search_interval` | 4 | uint32 | 300 | 1 | 10000 |
| 0x4C | `cmdq_on_no_detection_wait_duration` | 4 | uint32 | 1800 | 1 | 10000 |
| 0x4D | `cmdq_searched_mac_address` | 6 | byte_array | `{0xD8,0x10,0x68,0xAC,0xDA,0xE4}` |  |  |
| 0x4E | `cmdq_reporting_interval` | 4 | uint32 | 300 | 1 | 10000 |
| 0x4F | `s_band_rf_frequency_hz` | 4 | uint32 | 2008450000 | 1980000000 | 2100000000 |
| 0x50 | `cmdq_report_zero_messages_to_be_sent` | 1 | bool | False | False | True |
| 0x52 | `ublox_interval2_start` | 1 | uint8 | 19 | 0 | 23 |
| 0x57 | `lr_adr_profile` | 1 | uint8 | 3 | 0 | 3 |
| 0x5F | `ublox_min_satellites` | 1 | uint8 | 3 | 0 | 255 |
| 0x60 | `external_switch_detection_gpio_pin_power_enabled` | 1 | bool | False | False | True |
| 0x61 | `vhf_enabled` | 1 | bool | False | False | True |
| 0x62 | `vhf_interval1` | 4 | uint32 | 2 | 0 | 86400 |
| 0x63 | `vhf_interval2` | 4 | uint32 | 2 | 0 | 86400 |
| 0x64 | `vhf_interval1_start` | 1 | uint8 | 7 | 0 | 23 |
| 0x65 | `vhf_interval2_start` | 1 | uint8 | 19 | 0 | 23 |
| 0x66 | `vhf_multiple_intervals` | 1 | bool | False | False | True |
| 0x67 | `vhf_num_of_packets_per_burst` | 1 | uint8 | 1 | 1 | 255 |
| 0x68 | `vhf_time_between_packets_ms` | 2 | uint16 | 250 | 1 | 10000 |
| 0x69 | `vhf_external_path` | 1 | bool | False | False | True |
| 0x6A | `vhf_tx_frequency_khz` | 4 | uint32 | 150000 | 150000 | 300000 |
| 0x6B | `vhf_single_pulse_duration_ms` | 2 | uint16 | 18 | 5 | 10000 |
| 0x6C | `s_band_send_mode` | 1 | uint8 | 1 | 0 | 2 |
| 0x6D | `fence_led_blink` | 1 | bool | False | False | True |
| 0x6E | `gps_motion_triggered_min_num_of_triggers_per_interval` | 1 | uint8 | 0 | 0 | 255 |
| 0x72 | `ble_scan_manufacturer_id` | 2 | uint16 | 2657 | 0 | 65535 |
| 0x73 | `accel_movement_data_fifo_enabled` | 1 | bool | False | False | True |
| 0x74 | `accel_odr_hz` | 2 | uint16 | 12 | 0 | 1600 |
| 0x75 | `accel_g_scale` | 1 | uint8 | 2 | 2 | 16 |
| 0x76 | `satellite_send_interval2` | 4 | uint32 | 86400 | 0 | 86400 |
| 0x77 | `satellite_send_interval2_start` | 1 | uint8 | 19 | 0 | 23 |
| 0x78 | `satellite_multiple_intervals` | 1 | bool | False | False | True |
| 0x79 | `satellite_interval1_start` | 1 | uint8 | 7 | 0 | 23 |
| 0x7A | `outdoor_detection_enabled` | 1 | bool | False | False | True |
| 0x7B | `outdoor_detection_tau` | 1 | uint8 | 11 | 0 | 100 |
| 0x7C | `outdoor_detection_parameters` | 12 | byte_array | `{0xCB,0xEC,0x6B,0x12,0x2A,0x13,0x79,0x0F,0x20,0x1C,0x00,0x00}` |  |  |
| 0x7D | `ublox_cold_fix_hour_interval` | 2 | uint16 | 0 | 0 | 4320 |
| 0x7E | `external_switch_detection_enabled` | 1 | bool | False | False | True |
| 0x7F | `external_switch_detection_trigger_type` | 1 | uint8 | 0 | 0 | 1 |
| 0x80 | `external_switch_detection_trigger_debounce_ms` | 2 | uint16 | 50 | 0 | 2000 |
| 0x81 | `external_switch_detection_reporting_interval` | 4 | uint32 | 3600 | 0 | 86400 |
| 0x82 | `external_switch_send_inactivity_report` | 1 | bool | True | False | True |
| 0x83 | `external_switch_minimal_report_duration_ms` | 2 | uint16 | 250 | 0 | 65000 |
| 0x84 | `external_switch_input_pull` | 1 | uint8 | 1 | 0 | 2 |
| 0x85 | `external_switch_counter_enabled` | 1 | bool | False | False | True |
| 0x86 | `air_quality_enabled` | 1 | bool | False | False | True |
| 0x87 | `air_quality_interval` | 4 | uint32 | 300 | 10 | 86400 |
| 0x88 | `lp0_send_flag` | 4 | uint32 | 0 | 0 | 4294967295 |
| 0x89 | `lp0_tx_frequency_hz` | 4 | uint32 | 869150000 | 0 | 2100000000 |
| 0x8A | `lp0_rx_frequency_hz` | 4 | uint32 | 869150000 | 0 | 2100000000 |
| 0x8B | `lp0_communication_params` | 4 | byte_array | `{0x07,0x05,0x01,0x01}` |  |  |
| 0x8C | `lp0_node_params` | 5 | byte_array | `{0x00,0x00,0x0a,0x01,0x3c}` |  |  |

Default port bitmasks decoded (bit n-1 = FPort n):

* `lr_send_flag` 0x0C = 4162715375 (0xF81DFEEF): ports 1 (lr_gps), 2 (ublox_gps), 3 (settings), 4 (status), 6 (wifi_scan_aggregated), 7 (ble_scan_aggregated), 8 (legacy rf_scan, bit still set), 10 (wifi_scan), 11 (ble_scan), 12 (fence), 13 (ublox_short_message), 14 (flash_status), 15 (ble_cmdq), 16 (ublox_resend_location), 17 (legacy open sky detection, bit still set), 19 (external_switch_detection), 20 (external_switch_detection_status), 21 (air_quality), 28 (lr_messaging), 29 (flash_log), 30 (values), 31 (messages), 32 (commands)
* `flash_store_flag` 0x0D = 876143 (0x000D5E6F): ports 1 (lr_gps), 2 (ublox_gps), 3 (settings), 4 (status), 6 (wifi_scan_aggregated), 7 (ble_scan_aggregated), 10 (wifi_scan), 11 (ble_scan), 12 (fence), 13 (ublox_short_message), 15 (ble_cmdq), 17 (legacy open sky detection, bit still set), 19 (external_switch_detection), 20 (external_switch_detection_status)
* `sat_send_flag` 0x39 = 16522 (0x0000408A): ports 2 (ublox_gps), 4 (status), 8 (legacy rf_scan, bit still set), 15 (ble_cmdq)

Setting notes that matter for an integration:

* `tracker_type` 0x00 selects the firmware type reported in status byte 13 (section 6.2). RangerEdge hardware can be set to 5 rangeredge, 10 fenceedge, 7 scanneredge, 2 elephantedge, 3 wisentedge; RhinoEdge hardware to 1, 11, 14, 15, 12, 13.
* `ublox_send_interval` 0x02 (interval 1), `ublox_send_interval_2` 0x26 (interval 2), `ublox_multiple_intervals` 0x29, `ublox_interval1_start` 0x27 and `ublox_interval2_start` 0x52 (UTC hours) define a two period daily schedule. The wiki still calls 0x27 `ublox_switch_interval`.
* `gps_resend_interval` 0x0A periodically resends the last position on FPort 16.
* `horizontal_accuracy` 0x13 (m) is the acceptance threshold for a fix; `hot_fix_timeout` 0x17 and `cold_fix_timeout` 0x16 are u16 seconds.
* `data_log` 0x0B enables flash logging globally; `flash_store_flag` selects ports.
* `device_pin` 0x2A (4 ASCII digits, 0000 = off) locks BLE access; status bit `locked` reflects it.
* `lp0_*` (0x44 to 0x46, 0x88 to 0x8C) were `s_band_*` in 6.x (the wiki still names 0x44/0x45/0x46 `s_band_app_key`, `s_band_network_key`, `s_band_dev_adr`).

### 4.5 Downlinks over other channels

* Bluetooth (Smart Parks Connect app, BLE web app): same bytes with the port in front: `03 3F 01 01` enables the fence; `32 195 0` (decimal) is `cmd_set_hibernation_mode`.
* RockBLOCK mobile terminated message (wiki satellite page): `[port, msg_id, msg_len, msg_data]`, TLVs on the same port may be stacked. Examples `03 02 04 08 07 00 00` (GPS interval 30 min), `03 04 04 10 0E 00 00` (satellite send interval 1 h).
* `smartparks-connect-web` (`utils/bytes.go`, `web/chirpstack.go`) builds exactly `id, length, value` with uint32/int32/float little-endian, bool as 1 byte, byte arrays from hex, strings raw, and enqueues on FPort 3 for settings and FPort 32 for commands via the ChirpStack gRPC API.


## 5. Decoder sources (verbatim)

### 5.1 Which decoder applies to which device and firmware

All OpenCollar Edge devices (every *Edge and *Free device, every RangerEdge/RhinoEdge/CollarEdge hardware) use one decoder family, `ttn_decoder.js`, that ships in the firmware repository and is released alongside each firmware version as `ttn_decoder-v<fw>.js`. Choose by firmware version of the device:

| Device firmware | Decoder | Where | Notes |
| --- | --- | --- | --- |
| 7.1.0 to 7.3.0 (current) | `ttn_decoder-v7.2.0.js` | `raw_logs_decoder`, identical to `scripts/ttn_decoder.js` at fw commit 73fa4de (7.3.0) | Adds FPort 21 air quality and `version` string; drops ports 8 and 17 and the `rf_scan` feature bit. Backward compatible for all other ports |
| 6.15.0 to 6.16.3 | `ttn_decoder-v6.15.1.js` (byte identical to `-v6.15.3.js` in the lp0 tools) | `raw_logs_decoder`, `smartparks-lp0-*` | Adds `>>> 0` unsigned fixes, ports 18, 19, 20 |
| 6.9.0 to 6.14.3 | `ttn_decoder-v6.11.2.js` (byte identical to `-v6.14.0.js`) | `raw_logs_decoder` | 15 byte CMDQ records with HRV |
| 6.1.x to 6.8.x | `CSv4_Decoder_OpenCollar_Edge_v6.5.0.js` | `smartparks-toolset` | ChirpStack v4 wrapper; 13 byte CMDQ records; ports 8 and 17 present |
| 4.x | `CSv4_Decoder_OpenCollar_Edge_v4.4.3.js`, `d_opencollar_Edge_v2.js` | `smartparks-toolset` | No CMDQ (port 15) |
| pre-Edge OpenCollar v2.x/v3 (STM32 "OpenCollar Tracker", Lion, Rhino legacy, first fence) | `d_opencollar_tracker_v1.js`, `d_opencollar_v3.js`, `d_opencollar_fence_v2.js`, `d_opencollar_rhino_tracker_legacy.js`, `d_opencollar_lion_tracker_legacy.js`, `d_opencollar_rhinoedge_v0_1.js`, TTN repo `opencollar-v26.js` | `smartparks-toolset`, `lorawan-devices` | Completely different protocol (24 bit lat/lon, status on port 12). Included below for completeness; do not use for Edge devices |

Decoder entry points differ per network server:

* TTN v2 / the firmware file: `Decoder(bytes, port)` returns the object. The raw_logs_decoder and lp0 tools call this signature directly.
* TTN v3 / LoRaWAN device repository style: wrap as `function decodeUplink(input) { return { data: Decoder(input.bytes, input.fPort) }; }`.
* ChirpStack v3: `function Decode(fPort, bytes, variables)`; ChirpStack v4: `decodeUplink(input)` returning `{ data }`. The toolset `CSv4_*` files contain `Decode(fPort, bytes, variables)` plus a `decodeUplink` wrapper; they are otherwise the same code as the TTN file of the matching version with `port` renamed to `fPort` (and the flash log record key `fPort` instead of `port`).

### 5.2 ttn_decoder v7.2.0 (current; identical to firmware 7.3.0 `scripts/ttn_decoder.js`)

Source URL: https://raw.githubusercontent.com/SmartParksOrg/raw_logs_decoder/main/ttn_decoder-v7.2.0.js (repository commit 9b10e024397ca85488a14e0175732c64ca7ac6ee, 2026-07-08). Also https://raw.githubusercontent.com/SmartParksOrg/smartparks-opencollar-edge-fw-public/main/scripts/ttn_decoder.js (commit 73fa4de0b831dac488c82398a215524186c003b6, 2026-04-10). `diff` between the two files is empty.

```javascript
function decode_uint8(byte, min, max)
{
	var val;
	val = byte * (max - min) / 255 + min;
	return val;
}
function decode_nav_payload(bytes, index, nav_len)
{
	var nav_payload = "";
	var one_byte;
	var one_byte_str;
	// Skip first byte
	for (var i = 1; i < nav_len; i++) {
		one_byte = bytes[index + i];
		one_byte_str = one_byte.toString(16);
		if (one_byte_str.length == 1) {
			nav_payload += ("0" + one_byte_str);
		} else {
			nav_payload += one_byte_str;
		}
	}
	return nav_payload;
}
function get_constellation_name(id)
{
	var name;
	if (id == 1) {
		name = "GPS";
	} else if (id == 2) {
		name = "GLONASS";
	} else if (id == 3) {
		name = "combined";
	} else if (id == 4) {
		name = "Galileo";
	} else if (id == 5) {
		name = "BeiDou";
	} else {
		name = "";
	}
	return name;
}
function decodeGNSSMessage(bytes)
{
	// Skip header 0 and 1
	var nav_len = bytes[1];
	var decoded = {
		nav_payload : decode_nav_payload(bytes, 2, nav_len),
	};
	return decoded;
}
function decodeUbloxLocationMessage(bytes)
{
	var success = bytes[2];
	var hot_retry = bytes[3];
	var cold_retry = bytes[4];
	var ttf = (bytes[6] << 8 | bytes[5]) >>> 0;
	var value = bytes[10] << 24 | bytes[9] << 16 | bytes[8] << 8 | bytes[7];
	var latitude = value / 10000000; // gps latitude,units: °
	value = bytes[14] << 24 | bytes[13] << 16 | bytes[12] << 8 | bytes[11];
	var longitude = value / 10000000; // gps longitude,units: °
	value = bytes[18] << 24 | bytes[17] << 16 | bytes[16] << 8 | bytes[15];
	var altitude = value / 1000;
	var fixType = bytes[19];
	var SIV = bytes[20];
	var h_acc_est = (bytes[22] << 8 | bytes[21]) >>> 0;
	var pDOP = bytes[23];
	var fix_time = (bytes[27] << 24 | bytes[26] << 16 | bytes[25] << 8 | bytes[24]) >>> 0;
	var active_tracking = bytes[28];
	value = (bytes[29] << 8 | bytes[30]) >>> 0;
	var cog = (value - 18000) / 100;
	var sog = bytes[31] * 3.6;
	var decoded = {
		latitude : latitude,
		longitude : longitude,
		altitude : altitude,
		success : success,
		hot_retry : hot_retry,
		cold_retry : cold_retry,
		ttf : ttf,
		fixType : fixType,
		SIV : SIV,
		h_acc_est : h_acc_est,
		pDOP : pDOP,
		fix_timestamp : fix_time,
		active_t : active_tracking,
	};

	if (active_tracking) {
		decoded["cog"] = cog;
		decoded["sog"] = sog;
	}
	return decoded;
}
function decodeStatusMessage(bytes)
{
	// Skip header 0 and 1
	var reset = bytes[2];
	var err = bytes[3];
	var bat = (bytes[4] * 10) + 2500;
	var operation = bytes[5];
	var msg = 0;
	if (operation & 1)
		msg = 1;
	var locked = 0;
	if (operation & 2)
		locked = 1;
	var lr_join = 0;
	if (operation & 4)
		lr_join = 1;
	var lr_sat = operation >> 4;
	var temp = decode_uint8(bytes[6], -100, 100);
	var uptime = bytes[7];
	var acc_x = decode_uint8(bytes[8], -100, 100);
	var acc_y = decode_uint8(bytes[9], -100, 100);
	var acc_z = decode_uint8(bytes[10], -100, 100);
	var version = bytes[11];
	var ver_hw_minor = version & 0x0F;
	var ver_hw_major = version >> 4;
	version = bytes[12];
	var ver_fw_minor = version & 0x0F;
	var ver_fw_major = version >> 4;
	var ver_hw_type = bytes[13] & 0x0F;
	var ver_fw_type = bytes[13] >> 4;
	var version = "v" + ver_fw_major.toString() + "." + ver_fw_minor.toString()
	var chg = 0;
	if (bytes[14] > 0)
		chg = (bytes[14] * 100) + 5000;
	var features = bytes[15];
	var sat_support = 0;
	if (features & 1)
		sat_support = 1;
	var fence = 0;
	if (features & 4)
		fence = 1;
	var sat_try = features >> 4;
	// Errors
	var err_lr = 0;
	if (err & 1)
		err_lr = 1;
	var err_ble = 0;
	if (err & 2)
		err_ble = 1;
	var err_ublox = 0;
	if (err & 4)
		err_ublox = 1;
	var err_acc = 0;
	if (err & 8)
		err_acc = 1;
	var err_bat = 0;
	if (err & 16)
		err_bat = 1;
	var err_ublox_fix = 0;
	if (err & 32)
		err_ublox_fix = 1;
	var err_flash = 0;
	if (err & 64)
		err_flash = 1;
	var decoded = {
		reset : reset,
		bat : bat,
		chg : chg,
		temp : temp,
		uptime : uptime,
		locked : locked,
		msg : msg,
		acc_x : acc_x,
		acc_y : acc_y,
		acc_z : acc_z,
		lr_sat : lr_sat,
		err_lr : err_lr,
		err_lr_join : lr_join,
		err_ble : err_ble,
		err_ublox : err_ublox,
		err_acc : err_acc,
		err_bat : err_bat,
		err_ublox_fix : err_ublox_fix,
		err_flash : err_flash,
		ver_fw_major : ver_fw_major,
		ver_fw_minor : ver_fw_minor,
		ver_hw_major : ver_hw_major,
		ver_hw_minor : ver_hw_minor,
		ver_hw_type : ver_hw_type,
		ver_fw_type : ver_fw_type,
		sat_support : sat_support,
		sat_try : sat_try,
		fence : fence,
		version : version,
	};
	return decoded;
}
function decodeLRSatellitesMessage(bytes)
{
	// Skip header 0
	var len = bytes[1];
	var n_sat = bytes[2];
	var decoded = {
		N_sat : n_sat,
	};
	var i = 0;
	var idx = 2;
	var object = [];
	while (i < n_sat && idx < len) {
		object[i] = {
			id : bytes[2 * i + 3],
			cnr : bytes[2 * i + 4],
		};
		decoded[String(1 + i)] = object[i];
		i++;
		idx += 2;
	}
	decoded["N_reported"] = i;
	return decoded;
}
function decodeScanMessage(bytes, port)
{
	// Skip header 0
	var len = bytes[1];
	var n_wifi_res = bytes[2];
	var decoded = {};
	if (port == 6 || port == 10) {
		decoded = {
			N_wifi_res : n_wifi_res,
		};
	} else {
		decoded = {
			N_BT_res : n_wifi_res,
		};
	}
	var i = 0;
	var idx = 0;
	var object = [];
	var mac = [];
	while (i < n_wifi_res && idx < len - 1) {
		mac[i] = "";
		for (var j = 2; j > 0; j--) {
			mac[i] = mac[i].concat(bytes[3 + i * 9 + j].toString(16) + ":");
		}
		mac[i] = mac[i].concat(bytes[3 + i * 9 + 0].toString(16));
		object[i] = {
			rssi : bytes[3 + i * 9 + 3] - 128,
			count : bytes[3 + i * 9 + 4],
			mac : mac[i],
			t : (bytes[3 + i * 9 + 8] << 24 | bytes[3 + i * 9 + 7] << 16 |
			     bytes[3 + i * 9 + 6] << 8 | bytes[3 + i * 9 + 5]) >>>
				    0,
		};
		decoded[String(1 + i)] = object[i];
		i++;
		idx += 9;
	}
	return decoded;
}
function decodeLastScanMessage(bytes)
{
	// Skip header 0
	var len = bytes[1];
	var timestamp = (bytes[5] << 24 | bytes[4] << 16 | bytes[3] << 8 | bytes[2]) >>> 0;
	var n_wifi_res = bytes[6];
	var decoded = {
		N_BT_res : n_wifi_res,
		t : timestamp,
	};
	var i = 0;
	var idx = 5; // Set index to end of timestamp and data count
	var object = [];
	var mac = [];
	while (i < n_wifi_res && idx < len - 1) {
		mac[i] = "";
		for (var j = 2; j > 0; j--) {
			mac[i] = mac[i].concat(bytes[7 + i * 4 + j].toString(16) + ":");
		}
		mac[i] = mac[i].concat(bytes[7 + i * 4 + 0].toString(16));
		object[i] = {
			rssi : bytes[7 + i * 4 + 3] - 128,
			mac : mac[i],
		};
		decoded[String(1 + i)] = object[i];
		i++;
		idx += 4;
	}
	return decoded;
}
function decodeUbloxSatellitesMessage(bytes)
{
	// Skip header 0 and 1
	var len = bytes[1];
	var n_sat = bytes[2];
	var decoded = {
		N_sat : n_sat,
	};
	var i = 0;
	var idx = 2;
	var object = [];
	while (i < n_sat && idx < len - 1) {
		object[i] = {
			id : bytes[6 * i + 3],
			cn0 : bytes[6 * i + 4],
			ele : bytes[6 * i + 5],
			azi : bytes[6 * i + 7] << 8 | bytes[6 * i + 6],
			con : get_constellation_name(bytes[6 * i + 8]),
		};
		decoded[String(1 + i)] = object[i];
		i++;
		idx += 6;
	}
	decoded["N_reported"] = i;
	return decoded;
}
function decodeReadFlashMessage(bytes)
{
	var decoded = {};
	var msg_len = bytes.length;
	var i = 0;
	var port = 0;
	var len = 0;
	var msg = [];
	var msg_idx = 0;
	var timestamp = [];
	var object = [];
	var parsed_msg = {};
	while (i < msg_len - 7) {
		port = bytes[i]; // Read port
		// We do not need id
		len = bytes[i + 2];                    // Read msg len
		msg = bytes.slice(i + 1, i + len + 3); // Slice message part
		i += len + 3;
		timestamp =
			(bytes[i + 3] << 24 | bytes[i + 2] << 16 | bytes[i + 1] << 8 | bytes[i]) >>>
			0;
		i += 4;
		parsed_msg = {};
		if (port != 29) {
			parsed_msg = Decoder(msg, port);
		}
		object[msg_idx] = {
			data : parsed_msg,
			port : port,
			timestamp : timestamp,
		};
		decoded[String(1 + msg_idx)] = object[msg_idx];
		msg_idx++;
	}
	return decoded;
}

function decodeUbloxLocationMessageShort(bytes)
{
	var fix_timestamp = (bytes[5] << 24 | bytes[4] << 16 | bytes[3] << 8 | bytes[2]) >>> 0;
	var latitude = bytes[9] << 24 | bytes[8] << 16 | bytes[7] << 8 | bytes[6];
	latitude = latitude / 10000000;
	var longitude = bytes[13] << 24 | bytes[12] << 16 | bytes[11] << 8 | bytes[10];
	longitude = longitude / 10000000;
	var h_acc_est = (bytes[15] << 8 | bytes[14]) >>> 0;
	var decoded = {
		fix_timestamp : fix_timestamp,
		latitude : latitude,
		longitude : longitude,
		h_acc_est : h_acc_est
	};
	return decoded;
}

function decodeDeviceMessage(bytes)
{
	var len = bytes[1];
	var msg_len = bytes[2];
	var msg = bytes.slice(3, 3 + msg_len);
	var seq = bytes[3 + msg_len];
	var retry = bytes[4 + msg_len];

	var decoded = {
		len : len,
		msg_len : msg_len,
		msg : msg,
		seq : seq,
		retry : retry,
	};

	return decoded;
}

function decodedMemfault(bytes)
{
	var len = bytes[1];
	var msg = bytes.slice(2);

	var decoded = {
		len : len,
		msg : msg,
	};

	return decoded;
}

function uint16(b1, b2)
{
	return (b1 & 0xff) | ((b2 & 0xff) << 8);
}

function getBandDisplayName(start, stop)
{
	if (start >= 1920 && stop <= 1980) {
		return "1";
	} else if (start >= 2110 && stop <= 2170) {
		return "1d";
	} else if (start >= 1710 && stop <= 1785) {
		return "3";
	} else if (start >= 1805 && stop <= 1880) {
		return "3d";
	} else if (start >= 2500 && stop <= 2570) {
		return "7";
	} else if (start >= 2620 && stop <= 2690) {
		return "7d";
	} else if (start >= 880 && stop <= 915) {
		return "8";
	} else if (start >= 925 && stop <= 960) {
		return "8d";
	} else if (start >= 832 && stop <= 862) {
		return "20";
	} else if (start >= 791 && stop <= 821) {
		return "20d";
	} else if (start >= 2401 && stop <= 2484) {
		return "wifi_bt";
	} else {
		return "unknown";
	}
}

function decodeFence(bytes)
{
	// Skip header 0
	var len = bytes[1];
	var success = bytes[2];
	var N = bytes[3];
	var voltage = uint16(bytes[4], bytes[5]);
	var energy = uint16(bytes[6], bytes[7]);

	var decoded = {
		success : success,
		N : N,
		voltage : voltage,
		energy : energy,
	};

	return decoded;
}

function decodeFlashStatusMessage(bytes)
{
	// Skip header 0
	var len = bytes[1];
	var percentage = bytes[2];
	var n_msg = (bytes[6] << 24 | bytes[5] << 16 | bytes[4] << 8 | bytes[3]) >>> 0;

	var decoded = {
		percentage : percentage,
		n_msg : n_msg,
	};

	return decoded;
}

function decodeBluetoothCMDQMessage(bytes)
{
	const one_CMDQ_message_length = 15;
	var len = bytes[1];
	var n_res = Math.floor(len / one_CMDQ_message_length);
	var decoded = {};
	for (var i = 0; i < n_res; i++) {
		var offset = 2 + (i * one_CMDQ_message_length);
		var measurement_timestamp =
			(((bytes[offset + 3] & 0xff) << 24) | ((bytes[offset + 2] & 0xff) << 16) |
			 ((bytes[offset + 1] & 0xff) << 8) | (bytes[offset] & 0xff)) >>>
			0;
		var rr_median = bytes[offset + 4];
		var rr_median_modesum = bytes[offset + 5];
		var activity_average = bytes[offset + 6];
		var activity_max = bytes[offset + 7];
		var active_min_in_last_hour = bytes[offset + 8];
		var raw_temperature = uint16(bytes[offset + 10], bytes[offset + 9]);
		var temperature = 0;
		var cmdq_success = 0;
		if (raw_temperature > 0) {
			temperature = (raw_temperature * 0.0248) - 18.09;
			cmdq_success = 1;
		}
		var h_impedance = uint16(bytes[offset + 12], bytes[offset + 11]);
		var hrv_raw = uint16(bytes[offset + 14], bytes[offset + 13]);
		var hrv = Math.sqrt(hrv_raw);

		decoded[i] = {
			cmdq_timestamp : measurement_timestamp,
			cmdq_rr_median : rr_median,
			cmdq_rr_median_modesum : rr_median_modesum,
			cmdq_activity_average : activity_average,
			cmdq_activity_max : activity_max,
			cmdq_active_min_in_last_hour : active_min_in_last_hour,
			cmdq_temp : temperature,
			cmdq_raw_temp : raw_temperature,
			cmdq_h_impedance : h_impedance,
			cmdq_hrv : hrv,
			cmdq_hrv_raw : hrv_raw,
			cmdq_success : cmdq_success
		}
	}
	return decoded;
}

function decodeLastPosition(bytes)
{
	if (bytes[0] == 0xfe) {
		var value = bytes[5] << 24 | bytes[4] << 16 | bytes[3] << 8 | bytes[2];
		var latitude = value / 10000000; // gps latitude,units: °
		value = bytes[9] << 24 | bytes[8] << 16 | bytes[7] << 8 | bytes[6];
		var longitude = value / 10000000; // gps longitude,units: °
		value = bytes[13] << 24 | bytes[12] << 16 | bytes[11] << 8 | bytes[10];
		var altitude = value / 1000;
		var fix_time =
			(bytes[17] << 24 | bytes[16] << 16 | bytes[15] << 8 | bytes[14]) >>> 0;
		var decoded = {
			latitude : latitude,
			longitude : longitude,
			altitude : altitude,
			fix_time : fix_time,
		};
	};
	return decoded;
}

function decodeTimestamp(bytes)
{
	var decoded = {};
	var len = bytes[1];
	if (len == 4) {
		var timestamp = (bytes[5] << 24 | bytes[4] << 16 | bytes[3] << 8 | bytes[2]) >>> 0;
		decoded = {
			timestamp : timestamp,
		};
	}
	return decoded;
}

function decodeExternalSwitchMessage(bytes)
{
	var decoded = {};
	var pressed = bytes[2];
	var duration_ms = (bytes[6] << 24 | bytes[5] << 16 | bytes[4] << 8 | bytes[3]) >>> 0;
	decoded = {
		activity : pressed,
		duration_ms : duration_ms,
	};
	return decoded;
}

function decodeExternalSwitchStatusMessage(bytes)
{
	var decoded = {};
	var pressed = bytes[2];
	/* Pressed value 2 means the message contains impulse count */
	if (pressed == 2) {
		var impulse_count =
			(bytes[6] << 24 | bytes[5] << 16 | bytes[4] << 8 | bytes[3]) >>> 0;
		decoded = {
			impulse_count : impulse_count,
		};
	} else {
		var num_of_active_detections =
			(bytes[6] << 24 | bytes[5] << 16 | bytes[4] << 8 | bytes[3]) >>> 0;
		decoded = {
			activity : pressed,
			num_of_active_detections : num_of_active_detections,
		};
	}
	return decoded;
}

function decodeAirQualityBME690(bytes, offset)
{
	return {
		air_q_IAQ : new DataView(new Uint8Array([
						 bytes[offset], bytes[offset + 1],
						 bytes[offset + 2], bytes[offset + 3]
					 ]).buffer)
				    .getFloat32(0, true),

		air_q_temperature : new DataView(new Uint8Array([
							 bytes[offset + 4], bytes[offset + 5],
							 bytes[offset + 6], bytes[offset + 7]
						 ]).buffer)
					    .getFloat32(0, true),

		air_q_pressure : new DataView(new Uint8Array([
						      bytes[offset + 8], bytes[offset + 9],
						      bytes[offset + 10], bytes[offset + 11]
					      ]).buffer)
					 .getFloat32(0, true),

		air_q_humidity : new DataView(new Uint8Array([
						      bytes[offset + 12], bytes[offset + 13],
						      bytes[offset + 14], bytes[offset + 15]
					      ]).buffer)
					 .getFloat32(0, true),

		air_q_raw_gas : new DataView(new Uint8Array([
						     bytes[offset + 16], bytes[offset + 17],
						     bytes[offset + 18], bytes[offset + 19]
					     ]).buffer)
					.getFloat32(0, true),
	};
}

function decodeAirQualityBMV080(bytes, offset)
{
	return {
		air_q_pm2_5_mass : new DataView(new Uint8Array([
							bytes[offset], bytes[offset + 1],
							bytes[offset + 2], bytes[offset + 3]
						]).buffer)
					   .getFloat32(0, true),

		air_q_pm1_mass : new DataView(new Uint8Array([
						      bytes[offset + 4], bytes[offset + 5],
						      bytes[offset + 6], bytes[offset + 7]
					      ]).buffer)
					 .getFloat32(0, true),

		air_q_pm10_mass : new DataView(new Uint8Array([
						       bytes[offset + 8], bytes[offset + 9],
						       bytes[offset + 10], bytes[offset + 11]
					       ]).buffer)
					  .getFloat32(0, true),

		air_q_pm2_5_num : new DataView(new Uint8Array([
						       bytes[offset + 12], bytes[offset + 13],
						       bytes[offset + 14], bytes[offset + 15]
					       ]).buffer)
					  .getFloat32(0, true),

		air_q_pm1_num : new DataView(new Uint8Array([
						     bytes[offset + 16], bytes[offset + 17],
						     bytes[offset + 18], bytes[offset + 19]
					     ]).buffer)
					.getFloat32(0, true),

		air_q_pm10_num : new DataView(new Uint8Array([
						      bytes[offset + 20], bytes[offset + 21],
						      bytes[offset + 22], bytes[offset + 23]
					      ]).buffer)
					 .getFloat32(0, true),

		air_q_is_obstructed : bytes[offset + 24],
	};
}

function decodeAirQualityMessage(bytes)
{
	var decoded = {};
	var len = bytes[1];

	if (len == 2) {
		/* Only header was sent - No data available */
		decoded = {};
	} else if (len > 2 && len < 27) {
		/* Only BME690 data */
		decoded = decodeAirQualityBME690(bytes, 2);
	} else if (len == 27) {
		/* Only BMV080 data */
		decoded = decodeAirQualityBMV080(bytes, 2);
	} else if (len > 27 && len < 48) {
		/* Both BMV080 and BME690 data */
		let bmv = decodeAirQualityBMV080(bytes, 2);
		let bme = decodeAirQualityBME690(bytes, 27);
		decoded = {...bmv, ...bme};
	} else if (len > 47) {
		/* Invalid message length */
		decoded = {};
	}

	return decoded;
}

function Decoder(bytes, port)
{
	// Decode an uplink message from a buffer
	// (array) of bytes to an object of fields.
	var decoded = {};
	if (port == 1) {
		decoded = decodeGNSSMessage(bytes);
	} else if (port == 2) {
		decoded = decodeUbloxLocationMessage(bytes);
	} else if (port == 4) {
		decoded = decodeStatusMessage(bytes);
	} else if (port == 5) {
		decoded = decodeLRSatellitesMessage(bytes);
	} else if (port == 6 || port == 7 || port == 10) {
		decoded = decodeScanMessage(bytes, port);
	} else if (port == 9) {
		decoded = decodeUbloxSatellitesMessage(bytes);
	} else if (port == 11) {
		decoded = decodeLastScanMessage(bytes);
	} else if (port == 12) {
		decoded = decodeFence(bytes);
	} else if (port == 13) {
		decoded = decodeUbloxLocationMessageShort(bytes);
	} else if (port == 14) {
		decoded = decodeFlashStatusMessage(bytes);
	} else if (port == 15) {
		decoded = decodeBluetoothCMDQMessage(bytes);
	} else if (port == 16) {
		decoded = decodeUbloxLocationMessageShort(bytes);
	} else if (port == 18) {
		decoded = decodeTimestamp(bytes);
	} else if (port == 19) {
		decoded = decodeExternalSwitchMessage(bytes);
	} else if (port == 20) {
		decoded = decodeExternalSwitchStatusMessage(bytes);
	} else if (port == 21) {
		decoded = decodeAirQualityMessage(bytes);
	} else if (port == 27) {
		decoded = decodedMemfault(bytes);
	} else if (port == 28) {
		decoded = decodeDeviceMessage(bytes);
	} else if (port == 29) {
		decoded = decodeReadFlashMessage(bytes);
	} else if (port == 31) {
		decoded = decodeLastPosition(bytes);
	}
	return decoded;
}

```

### 5.3 ttn_decoder v6.15.1 (for firmware 6.15.x and 6.16.x; byte identical to ttn_decoder-v6.15.3.js in smartparks-lp0-replay-app and smartparks-lp0-platform)

Source URL: https://raw.githubusercontent.com/SmartParksOrg/raw_logs_decoder/main/ttn_decoder-v6.15.1.js (commit 9b10e02, 2026-07-08). Differences to v7.2.0: contains `decodeRfScannerMessage` (port 8), `decodeOpenSkyDetection` (port 17) and the status `rf_scan` bit; lacks air quality (port 21) and the `version` string. Only the differing parts are reproduced here (the rest is identical to 5.2):

```javascript
// status message, inside decodeStatusMessage (v6.15.x):
	var rf_scan = 0;
	if (features & 2)
		rf_scan = 1;
	// ... and `rf_scan : rf_scan,` in the returned object; no `version` field.

function decodeRfScannerMessage(bytes)
{
	var len = bytes[1];
	var msg = bytes.slice(2);
	var decoded = {
		version : msg[0],
		should_alert : msg[1],
	};
	var offset = 2;
	var range_len = 6;
	for (var i = 0; i < (len - offset) / range_len; i++) {
		var x = offset + range_len * i;
		var c = 0;
		var start = uint16(msg[x + c++], msg[x + c++]) / 10;
		var stop = uint16(msg[x + c++], msg[x + c++]) / 10;
		decoded["band_" + getBandDisplayName(start, stop)] = {
			start : start,
			stop : stop,
			peak_count : msg[x + c++],
			max_rssi : -msg[x + c++],
		};
	}
	return decoded;
}

function decodeOpenSkyDetection(bytes)
{
	var decoded = {};
	var len = bytes[1];
	var n_res = Math.floor(len / 2);
	for (var i = 0; i < n_res; i++) {
		decoded[i] = { average_rssi : -bytes[2 + (i * 2)], max_rssi : -bytes[3 + (i * 2)] }
	}
	return decoded;
}

// in Decoder(bytes, port):
	} else if (port == 8) {
		decoded = decodeRfScannerMessage(bytes);
	...
	} else if (port == 17) {
		decoded = decodeOpenSkyDetection(bytes);
	// and no `port == 21` branch.
```

### 5.4 ttn_decoder v6.11.2 (for firmware 6.9.0 to 6.14.x; byte identical to ttn_decoder-v6.14.0.js)

Source URL: https://raw.githubusercontent.com/SmartParksOrg/raw_logs_decoder/main/ttn_decoder-v6.11.2.js (commit 9b10e02). Same message set as v6.15.1 minus ports 18, 19, 20 (timestamp, external switch), and without the `>>> 0` unsigned corrections (timestamps and counters with bit 31 set decode negative). Full file:

```javascript
function decode_uint8(byte, min, max) {
    var val;
    val = byte * (max - min) / 255 + min;
    return val;
}
function decode_nav_payload(bytes, index, nav_len) {
    var nav_payload = "";
    var one_byte;
    var one_byte_str;
    // Skip first byte
    for (var i = 1; i < nav_len; i++) {
        one_byte = bytes[index + i];
        one_byte_str = one_byte.toString(16);
        if (one_byte_str.length == 1) {
            nav_payload += ("0" + one_byte_str);
        }
        else {
            nav_payload += one_byte_str;
        }
    }
    return nav_payload;
}
function get_constellation_name(id) {
    var name;
    if (id == 1) {
        name = "GPS";
    }
    else if (id == 2) {
        name = "GLONASS";
    }
    else if (id == 3) {
        name = "combined";
    }
    else if (id == 4) {
        name = "Galileo";
    }
    else if (id == 5) {
        name = "BeiDou";
    }
    else {
        name = "";
    }
    return name;
}
function decodeGNSSMessage(bytes) {
    //Skip header 0 and 1
    var nav_len = bytes[1];
    var decoded = {
        nav_payload: decode_nav_payload(bytes, 2, nav_len),
    };
    return decoded;
}
function decodeUbloxLocationMessage(bytes) {
    var success = bytes[2];
    var hot_retry = bytes[3];
    var cold_retry = bytes[4];
    var ttf = bytes[6] << 8 | bytes[5];
    var value = bytes[10] << 24 | bytes[9] << 16 | bytes[8] << 8 | bytes[7];
    var latitude = value / 10000000; // gps latitude,units: °
    value = bytes[14] << 24 | bytes[13] << 16 | bytes[12] << 8 | bytes[11];
    var longitude = value / 10000000; // gps longitude,units: °
    value = bytes[18] << 24 | bytes[17] << 16 | bytes[16] << 8 | bytes[15];
    var altitude = value / 1000;
    var fixType = bytes[19];
    var SIV = bytes[20];
    var h_acc_est = bytes[22] << 8 | bytes[21];
    var pDOP = bytes[23];
    var fix_time = bytes[27] << 24 | bytes[26] << 16 | bytes[25] << 8 | bytes[24];
    var active_tracking = bytes[28];
    value = bytes[29] << 8 | bytes[30];
    var cog = (value - 18000) / 100;
    var sog = bytes[31] * 3.6;
    var decoded = {
        latitude: latitude,
        longitude: longitude,
        altitude: altitude,
        success: success,
        hot_retry: hot_retry,
        cold_retry: cold_retry,
        ttf: ttf,
        fixType: fixType,
        SIV: SIV,
        h_acc_est: h_acc_est,
        pDOP: pDOP,
        fix_timestamp: fix_time,
        active_t: active_tracking,
    };

    if (active_tracking) {
        decoded["cog"] = cog;
        decoded["sog"] = sog;
    }
    return decoded;
}
function decodeStatusMessage(bytes) {
    //Skip header 0 and 1
    var reset = bytes[2];
    var err = bytes[3];
    var bat = (bytes[4] * 10) + 2500;
    var operation = bytes[5];
    var msg = 0;
    if (operation & 1) msg = 1;
    var locked = 0;
    if (operation & 2) locked = 1;
    var lr_join = 0;
    if (operation & 4) lr_join = 1;
    var lr_sat = operation >> 4;
    var temp = decode_uint8(bytes[6], -100, 100);
    var uptime = bytes[7];
    var acc_x = decode_uint8(bytes[8], -100, 100);
    var acc_y = decode_uint8(bytes[9], -100, 100);
    var acc_z = decode_uint8(bytes[10], -100, 100);
    var version = bytes[11];
    var ver_hw_minor = version & 0x0F;
    var ver_hw_major = version >> 4;
    version = bytes[12];
    var ver_fw_minor = version & 0x0F;
    var ver_fw_major = version >> 4;
    var ver_hw_type = bytes[13] & 0x0F;
    var ver_fw_type = bytes[13] >> 4;
    var chg = 0;
    if (bytes[14] > 0) chg = (bytes[14] * 100) + 5000;
    var features = bytes[15];
    var sat_support = 0;
    if (features & 1) sat_support = 1;
    var rf_scan = 0;
    if (features & 2) rf_scan = 1;
    var fence = 0;
    if (features & 4) fence = 1;
    var sat_try = features >> 4;
    //Errors
    var err_lr = 0;
    if (err & 1) err_lr = 1;
    var err_ble = 0;
    if (err & 2) err_ble = 1;
    var err_ublox = 0;
    if (err & 4) err_ublox = 1;
    var err_acc = 0;
    if (err & 8) err_acc = 1;
    var err_bat = 0;
    if (err & 16) err_bat = 1;
    var err_ublox_fix = 0;
    if (err & 32) err_ublox_fix = 1;
    var err_flash = 0;
    if (err & 64) err_flash = 1;
    var decoded = {
        reset: reset,
        bat: bat,
        chg: chg,
        temp: temp,
        uptime: uptime,
        locked: locked,
        msg: msg,
        acc_x: acc_x,
        acc_y: acc_y,
        acc_z: acc_z,
        lr_sat: lr_sat,
        err_lr: err_lr,
        err_lr_join: lr_join,
        err_ble: err_ble,
        err_ublox: err_ublox,
        err_acc: err_acc,
        err_bat: err_bat,
        err_ublox_fix: err_ublox_fix,
        err_flash: err_flash,
        ver_fw_major: ver_fw_major,
        ver_fw_minor: ver_fw_minor,
        ver_hw_major: ver_hw_major,
        ver_hw_minor: ver_hw_minor,
        ver_hw_type: ver_hw_type,
        ver_fw_type: ver_fw_type,
        sat_support: sat_support,
        sat_try: sat_try,
        rf_scan: rf_scan,
        fence: fence,
    };
    return decoded;
}
function decodeLRSatellitesMessage(bytes) {
    //Skip header 0
    var len = bytes[1];
    var n_sat = bytes[2];
    var decoded = {
        N_sat: n_sat,
    };
    var i = 0;
    var idx = 2;
    var object = [];
    while (i < n_sat && idx < len) {
        object[i] = {
            id: bytes[2 * i + 3],
            cnr: bytes[2 * i + 4],
        };
        decoded[String(1 + i)] = object[i];
        i++;
        idx += 2;
    }
    decoded["N_reported"] = i;
    return decoded;
}
function decodeScanMessage(bytes, port) {
    //Skip header 0
    var len = bytes[1];
    var n_wifi_res = bytes[2];
    var decoded = {};
    if (port == 6 || port == 10) {
        decoded = {
            N_wifi_res: n_wifi_res,
        };
    }
    else {
        decoded = {
            N_BT_res: n_wifi_res,
        };
    }
    var i = 0;
    var idx = 0;
    var object = [];
    var mac = [];
    while (i < n_wifi_res && idx < len - 1) {
        mac[i] = "";
        for (var j = 2; j > 0; j--) {
            mac[i] = mac[i].concat(bytes[3 + i * 9 + j].toString(16) + ":");
        }
        mac[i] = mac[i].concat(bytes[3 + i * 9 + 0].toString(16));
        object[i] = {
            rssi: bytes[3 + i * 9 + 3] - 128,
            count: bytes[3 + i * 9 + 4],
            mac: mac[i],
            t: bytes[3 + i * 9 + 8] << 24 | bytes[3 + i * 9 + 7] << 16 | bytes[3 + i * 9 + 6] << 8 | bytes[3 + i * 9 + 5],
        };
        decoded[String(1 + i)] = object[i];
        i++;
        idx += 9;
    }
    return decoded;
}
function decodeLastScanMessage(bytes) {
    //Skip header 0
    var len = bytes[1];
    var timestamp = bytes[5] << 24 | bytes[4] << 16 | bytes[3] << 8 | bytes[2];
    var n_wifi_res = bytes[6];
    var decoded = {
        N_BT_res: n_wifi_res,
        t: timestamp,
    };
    var i = 0;
    var idx = 5; //Set index to end of timestamp and data count
    var object = [];
    var mac = [];
    while (i < n_wifi_res && idx < len - 1) {
        mac[i] = "";
        for (var j = 2; j > 0; j--) {
            mac[i] = mac[i].concat(bytes[7 + i * 4 + j].toString(16) + ":");
        }
        mac[i] = mac[i].concat(bytes[7 + i * 4 + 0].toString(16));
        object[i] = {
            rssi: bytes[7 + i * 4 + 3] - 128,
            mac: mac[i],
        };
        decoded[String(1 + i)] = object[i];
        i++;
        idx += 4;
    }
    return decoded;
}
function decodeUbloxSatellitesMessage(bytes) {
    //Skip header 0 and 1
    var len = bytes[1];
    var n_sat = bytes[2];
    var decoded = {
        N_sat: n_sat,
    };
    var i = 0;
    var idx = 2;
    var object = [];
    while (i < n_sat && idx < len - 1) {
        object[i] = {
            id: bytes[6 * i + 3],
            cn0: bytes[6 * i + 4],
            ele: bytes[6 * i + 5],
            azi: bytes[6 * i + 7] << 8 | bytes[6 * i + 6],
            con: get_constellation_name(bytes[6 * i + 8]),
        };
        decoded[String(1 + i)] = object[i];
        i++;
        idx += 6;
    }
    decoded["N_reported"] = i;
    return decoded;
}
function decodeReadFlashMessage(bytes) {
    var decoded = {};
    var msg_len = bytes.length;
    var i = 0;
    var port = 0;
    var len = 0;
    var msg = [];
    var msg_idx = 0;
    var timestamp = [];
    var object = [];
    var parsed_msg = {};
    while (i < msg_len - 7) {
        port = bytes[i]; //Read port
        //We do not need id
        len = bytes[i + 2]; //Read msg len
        msg = bytes.slice(i + 1, i + len + 3); //Slice message part
        i += len + 3;
        timestamp = bytes[i + 3] << 24 | bytes[i + 2] << 16 | bytes[i + 1] << 8 | bytes[i];
        i += 4;
        parsed_msg = {};
        if (port != 29) {
            parsed_msg = Decoder(msg, port);
        }
        object[msg_idx] = {
            data: parsed_msg,
            port: port,
            timestamp: timestamp,
        };
        decoded[String(1 + msg_idx)] = object[msg_idx];
        msg_idx++;
    }
    return decoded;
}

function decodeUbloxLocationMessageShort(bytes){
    var fix_timestamp = bytes[5] << 24 | bytes[4] << 16| bytes[3] << 8 | bytes[2];
    var latitude = bytes[9] << 24 | bytes[8] << 16| bytes[7] << 8 | bytes[6];
    latitude = latitude / 10000000; 
    var longitude = bytes[13] << 24 | bytes[12] << 16| bytes[11] << 8 | bytes[10];
    longitude = longitude / 10000000; 
    var h_acc_est = bytes[15] << 8 | bytes[14];
    var decoded = {
        fix_timestamp: fix_timestamp,
        latitude: latitude,
        longitude: longitude,
        h_acc_est: h_acc_est
    };
    return decoded;
}

function decodeDeviceMessage(bytes) {
    var len = bytes[1];
    var msg_len = bytes[2];
    var msg = bytes.slice(3, 3 + msg_len);
    var seq = bytes[3 + msg_len]
    var retry = bytes[4 + msg_len];

    var decoded = {
        len: len,
        msg_len: msg_len,
        msg: msg,
        seq: seq,
        retry: retry,
    };

    return decoded;
}

function decodedMemfault(bytes) {
    var len = bytes[1];
    var msg = bytes.slice(2);

    var decoded = {
        len: len,
        msg: msg,
    };

    return decoded;
}



function uint16(b1, b2) {
    return (b1 & 0xff) | ((b2 & 0xff) << 8);
}

function getBandDisplayName(start, stop) {
    if (start >= 1920 && stop <= 1980) {
        return "1";
    } else if (start >= 2110 && stop <= 2170) {
        return "1d";
    } else if (start >= 1710 && stop <= 1785) {
        return "3";
    } else if (start >= 1805 && stop <= 1880) {
        return "3d";
    } else if (start >= 2500 && stop <= 2570) {
        return "7";
    } else if (start >= 2620 && stop <= 2690) {
        return "7d";
    } else if (start >= 880 && stop <= 915) {
        return "8";
    } else if (start >= 925 && stop <= 960) {
        return "8d";
    } else if (start >= 832 && stop <= 862) {
        return "20";
    } else if (start >= 791 && stop <= 821) {
        return "20d";
    } else if (start >= 2401 && stop <= 2484) {
        return "wifi_bt";
    } else {
        return "unknown";
    }
}

function decodeRfScannerMessage(bytes) {
    var len = bytes[1];
    var msg = bytes.slice(2);
    var decoded = {
        version: msg[0],
        should_alert: msg[1],
    };
    var offset = 2;
    var range_len = 6;
    for (var i = 0; i < (len - offset) / range_len; i++) {
        var x = offset + range_len * i;
        var c = 0;
        var start = uint16(msg[x + c++], msg[x + c++]) / 10;
        var stop = uint16(msg[x + c++], msg[x + c++]) / 10;
        decoded["band_" + getBandDisplayName(start, stop)] = {
            start: start,
            stop: stop,
            peak_count: msg[x + c++],
            max_rssi: -msg[x + c++],
        };
    }
    return decoded;
}

function decodeFence(bytes) {
    //Skip header 0
    var len = bytes[1];
    var success = bytes[2];
    var N = bytes[3];
    var voltage = uint16(bytes[4], bytes[5]);
    var energy = uint16(bytes[6], bytes[7]);

    var decoded = {
        success: success,
        N: N,
        voltage: voltage,
        energy: energy,
    };

    return decoded;
}

function decodeFlashStatusMessage(bytes) {
    //Skip header 0
    var len = bytes[1];
    var percentage = bytes[2];
    var n_msg = bytes[6] << 24 | bytes[5] << 16 | bytes[4] << 8 | bytes[3];

    var decoded = {
        percentage: percentage,
        n_msg: n_msg,
    };

    return decoded;
}

function decodeBluetoothCMDQMessage(bytes) {
    const one_CMDQ_message_length = 15;
    var len = bytes[1];
    var n_res = Math.floor(len / one_CMDQ_message_length);
    var decoded = {};
    for(var i = 0; i < n_res; i++) {
        var offset = 2 + (i * one_CMDQ_message_length);
        var measurement_timestamp = ((bytes[offset + 3] & 0xff) << 24)| ((bytes[offset + 2] & 0xff) << 16) | ((bytes[offset + 1] & 0xff) << 8) | (bytes[offset] & 0xff);
        var rr_median = bytes[offset + 4];
        var rr_median_modesum = bytes[offset + 5];
        var activity_average = bytes[offset + 6];
        var activity_max = bytes[offset + 7];
        var active_min_in_last_hour = bytes[offset + 8];
        var raw_temperature = uint16(bytes[offset + 10], bytes[offset + 9]);
        var temperature = 0;
        var cmdq_success = 0;
        if (raw_temperature > 0) {
            temperature = (raw_temperature*0.0248) - 18.09;
            cmdq_success = 1;
        }
        var h_impedance = uint16(bytes[offset + 12], bytes[offset + 11]);
        var hrv_raw = uint16(bytes[offset + 14], bytes[offset + 13]);
        var hrv = Math.sqrt(hrv_raw);

        decoded[i]= {
            cmdq_timestamp: measurement_timestamp,
            cmdq_rr_median: rr_median,
            cmdq_rr_median_modesum: rr_median_modesum,
            cmdq_activity_average: activity_average,
            cmdq_activity_max: activity_max,
            cmdq_active_min_in_last_hour: active_min_in_last_hour,
            cmdq_temp: temperature,
            cmdq_raw_temp: raw_temperature,
            cmdq_h_impedance: h_impedance,
            cmdq_hrv: hrv,
            cmdq_hrv_raw: hrv_raw,
            cmdq_success:cmdq_success 
        }
    }
    return decoded;
}

function decodeOpenSkyDetection(bytes){
    var decoded = {};
    var len = bytes[1];
    var n_res = Math.floor(len / 2);
    for(var i = 0; i < n_res; i++) {
        decoded[i] = {
            average_rssi: -bytes[2 + (i * 2)],
            max_rssi: -bytes[3 + (i * 2)]
        }
    }
    return decoded;
}

function decodeLastPosition(bytes) {
    if (bytes[0] == 0xfe) {
        var value = bytes[5] << 24 | bytes[4] << 16 | bytes[3] << 8 | bytes[2];
        var latitude = value / 10000000; // gps latitude,units: °
        value = bytes[9] << 24 | bytes[8] << 16 | bytes[7] << 8 | bytes[6];
        var longitude = value / 10000000; // gps longitude,units: °
        value = bytes[13] << 24 | bytes[12] << 16 | bytes[11] << 8 | bytes[10];
        var altitude = value / 1000;
        var fix_time = bytes[17] << 24 | bytes[16] << 16 | bytes[15] << 8 | bytes[14];
        var decoded = {
            latitude: latitude,
            longitude: longitude,
            altitude: altitude,
            fix_time: fix_time,
        };
    };
    return decoded;
}

function decodeTimestamp(bytes) {
    var decoded = {};
    var len = bytes[1];
    if(len == 4){
        var timestamp = bytes[5] << 24 | bytes[4] << 16 | bytes[3] << 8 | bytes[2];
        decoded = {
            timestamp: timestamp,
        };
    }
    return decoded;
}

function Decoder(bytes, port) {
    // Decode an uplink message from a buffer
    // (array) of bytes to an object of fields.
    var decoded = {};
    if (port == 1) {
        decoded = decodeGNSSMessage(bytes);
    }
    else if (port == 2) {
        decoded = decodeUbloxLocationMessage(bytes);
    }
    else if (port == 4) {
        decoded = decodeStatusMessage(bytes);
    }
    else if (port == 5) {
        decoded = decodeLRSatellitesMessage(bytes);
    }
    else if (port == 6 || port == 7 || port == 10) {
        decoded = decodeScanMessage(bytes, port);
    }
    else if (port == 8) {
        decoded = decodeRfScannerMessage(bytes);
    }
    else if (port == 9) {
        decoded = decodeUbloxSatellitesMessage(bytes);
    }
    else if (port == 11) {
        decoded = decodeLastScanMessage(bytes);
    }
    else if (port == 12) {
        decoded = decodeFence(bytes);
    }
    else if (port == 13) {
        decoded = decodeUbloxLocationMessageShort(bytes);
    }
    else if (port == 14) {
        decoded = decodeFlashStatusMessage(bytes);
    }
    else if (port == 15) {
        decoded = decodeBluetoothCMDQMessage(bytes);
    }
    else if (port == 16) {
        decoded = decodeUbloxLocationMessageShort(bytes);
    }
    else if (port == 17) {
        decoded = decodeOpenSkyDetection(bytes);
    }
    else if (port == 18) {
        decoded = decodeTimestamp(bytes);
    }
    else if (port == 27) {
        decoded = decodedMemfault(bytes);
    }
    else if (port == 28) {
        decoded = decodeDeviceMessage(bytes);
    }
    else if (port == 29) {
        decoded = decodeReadFlashMessage(bytes);
    }
    else if (port == 31) {
        decoded = decodeLastPosition(bytes);
    }
    return decoded;
}

```

### 5.5 ChirpStack v4 decoder for firmware 6.1.x to 6.8.x: CSv4_Decoder_OpenCollar_Edge_v6.5.0.js

Source URL: https://raw.githubusercontent.com/SmartParksOrg/smartparks-toolset/main/assets/Decoders/CSv4_Decoder_OpenCollar_Edge_v6.5.0.js (commit bb98fb81a633e320154d6ac5f4e36606d403e26e, 2024-07-27). CMDQ records are 13 bytes here (no HRV). `CSv4_Decoder_OpenCollar_Edge_v6.1.2.js` differs only in formatting and in naming the port 2 time field `fix_time` instead of `fix_timestamp`; `CSv4_Decoder_OpenCollar_Edge_v4.4.3.js` (firmware 4.4.x) additionally lacks the port 15 branch. `d_opencollar_Edge_v2.js` is the 4.4.3 code with a comment header and with the features byte parsing (sat_support, rf_scan, fence, sat_try) missing.

```javascript
function decode_uint8(byte, min, max) {
    var val;
    val = byte * (max - min) / 255 + min;
    return val;
}
function decode_nav_payload(bytes, index, nav_len) {
    var nav_payload = "";
    var one_byte;
    var one_byte_str;
    // Skip first byte
    for (var i = 1; i < nav_len; i++) {
        one_byte = bytes[index + i];
        one_byte_str = one_byte.toString(16);
        if (one_byte_str.length == 1) {
            nav_payload += ("0" + one_byte_str);
        }
        else {
            nav_payload += one_byte_str;
        }
    }
    return nav_payload;
}
function get_constellation_name(id) {
    var name;
    if (id == 1) {
        name = "GPS";
    }
    else if (id == 2) {
        name = "GLONASS";
    }
    else if (id == 3) {
        name = "combined";
    }
    else if (id == 4) {
        name = "Galileo";
    }
    else if (id == 5) {
        name = "BeiDou";
    }
    else {
        name = "";
    }
    return name;
}
function decodeGNSSMessage(bytes) {
    //Skip header 0 and 1
    var nav_len = bytes[1];
    var decoded = {
        nav_payload: decode_nav_payload(bytes, 2, nav_len),
    };
    return decoded;
}
function decodeUbloxLocationMessage(bytes) {
    var success = bytes[2];
    var hot_retry = bytes[3];
    var cold_retry = bytes[4];
    var ttf = bytes[6] << 8 | bytes[5];
    var value = bytes[10] << 24 | bytes[9] << 16 | bytes[8] << 8 | bytes[7];
    var latitude = value / 10000000; // gps latitude,units: °
    value = bytes[14] << 24 | bytes[13] << 16 | bytes[12] << 8 | bytes[11];
    var longitude = value / 10000000; // gps longitude,units: °
    value = bytes[18] << 24 | bytes[17] << 16 | bytes[16] << 8 | bytes[15];
    var altitude = value / 1000;
    var fixType = bytes[19];
    var SIV = bytes[20];
    var h_acc_est = bytes[22] << 8 | bytes[21];
    var pDOP = bytes[23];
    var fix_time = bytes[27] << 24 | bytes[26] << 16 | bytes[25] << 8 | bytes[24];
    var active_tracking = bytes[28];
    value = bytes[29] << 8 | bytes[30];
    var cog = (value - 18000) / 100;
    var sog = bytes[31] * 3.6;
    var decoded = {
        latitude: latitude,
        longitude: longitude,
        altitude: altitude,
        success: success,
        hot_retry: hot_retry,
        cold_retry: cold_retry,
        ttf: ttf,
        fixType: fixType,
        SIV: SIV,
        h_acc_est: h_acc_est,
        pDOP: pDOP,
        fix_timestamp: fix_time,
        active_t: active_tracking,
    };

    if (active_tracking) {
        decoded["cog"] = cog;
        decoded["sog"] = sog;
    }
    return decoded;
}
function decodeStatusMessage(bytes) {
    //Skip header 0 and 1
    var reset = bytes[2];
    var err = bytes[3];
    var bat = (bytes[4] * 10) + 2500;
    var operation = bytes[5];
    var msg = 0;
    if (operation & 1) msg = 1;
    var locked = 0;
    if (operation & 2) locked = 1;
    var lr_join = 0;
    if (operation & 4) lr_join = 1;
    var lr_sat = operation >> 4;
    var temp = decode_uint8(bytes[6], -100, 100);
    var uptime = bytes[7];
    var acc_x = decode_uint8(bytes[8], -100, 100);
    var acc_y = decode_uint8(bytes[9], -100, 100);
    var acc_z = decode_uint8(bytes[10], -100, 100);
    var version = bytes[11];
    var ver_hw_minor = version & 0x0F;
    var ver_hw_major = version >> 4;
    version = bytes[12];
    var ver_fw_minor = version & 0x0F;
    var ver_fw_major = version >> 4;
    var ver_hw_type = bytes[13] & 0x0F;
    var ver_fw_type = bytes[13] >> 4;
    var chg = 0;
    if (bytes[14] > 0) chg = (bytes[14] * 100) + 5000;
    var features = bytes[15];
    var sat_support = 0;
    if (features & 1) sat_support = 1;
    var rf_scan = 0;
    if (features & 2) rf_scan = 1;
    var fence = 0;
    if (features & 4) fence = 1;
    var sat_try = features >> 4;
    //Errors
    var err_lr = 0;
    if (err & 1) err_lr = 1;
    var err_ble = 0;
    if (err & 2) err_ble = 1;
    var err_ublox = 0;
    if (err & 4) err_ublox = 1;
    var err_acc = 0;
    if (err & 8) err_acc = 1;
    var err_bat = 0;
    if (err & 16) err_bat = 1;
    var err_ublox_fix = 0;
    if (err & 32) err_ublox_fix = 1;
    var err_flash = 0;
    if (err & 64) err_flash = 1;
    var decoded = {
        reset: reset,
        bat: bat,
        chg: chg,
        temp: temp,
        uptime: uptime,
        locked: locked,
        msg: msg,
        acc_x: acc_x,
        acc_y: acc_y,
        acc_z: acc_z,
        lr_sat: lr_sat,
        err_lr: err_lr,
        err_lr_join: lr_join,
        err_ble: err_ble,
        err_ublox: err_ublox,
        err_acc: err_acc,
        err_bat: err_bat,
        err_ublox_fix: err_ublox_fix,
        err_flash: err_flash,
        ver_fw_major: ver_fw_major,
        ver_fw_minor: ver_fw_minor,
        ver_hw_major: ver_hw_major,
        ver_hw_minor: ver_hw_minor,
        ver_hw_type: ver_hw_type,
        ver_fw_type: ver_fw_type,
        sat_support: sat_support,
        sat_try: sat_try,
        rf_scan: rf_scan,
        fence: fence,
    };
    return decoded;
}
function decodeLRSatellitesMessage(bytes) {
    //Skip header 0
    var len = bytes[1];
    var n_sat = bytes[2];
    var decoded = {
        N_sat: n_sat,
    };
    var i = 0;
    var idx = 2;
    var object = [];
    while (i < n_sat && idx < len) {
        object[i] = {
            id: bytes[2 * i + 3],
            cnr: bytes[2 * i + 4],
        };
        decoded[String(1 + i)] = object[i];
        i++;
        idx += 2;
    }
    decoded["N_reported"] = i;
    return decoded;
}
function decodeScanMessage(bytes, fPort) {
    //Skip header 0
    var len = bytes[1];
    var n_wifi_res = bytes[2];
    var decoded = {};
    if (fPort == 6 || fPort == 10) {
        decoded = {
            N_wifi_res: n_wifi_res,
        };
    }
    else {
        decoded = {
            N_BT_res: n_wifi_res,
        };
    }
    var i = 0;
    var idx = 0;
    var object = [];
    var mac = [];
    while (i < n_wifi_res && idx < len - 1) {
        mac[i] = "";
        for (var j = 2; j > 0; j--) {
            mac[i] = mac[i].concat(bytes[3 + i * 9 + j].toString(16) + ":");
        }
        mac[i] = mac[i].concat(bytes[3 + i * 9 + 0].toString(16));
        object[i] = {
            rssi: bytes[3 + i * 9 + 3] - 128,
            count: bytes[3 + i * 9 + 4],
            mac: mac[i],
            t: bytes[3 + i * 9 + 8] << 24 | bytes[3 + i * 9 + 7] << 16 | bytes[3 + i * 9 + 6] << 8 | bytes[3 + i * 9 + 5],
        };
        decoded[String(1 + i)] = object[i];
        i++;
        idx += 9;
    }
    return decoded;
}
function decodeLastScanMessage(bytes) {
    //Skip header 0
    var len = bytes[1];
    var timestamp = bytes[5] << 24 | bytes[4] << 16 | bytes[3] << 8 | bytes[2];
    var n_wifi_res = bytes[6];
    var decoded = {
        N_BT_res: n_wifi_res,
        t: timestamp,
    };
    var i = 0;
    var idx = 5; //Set index to end of timestamp and data count
    var object = [];
    var mac = [];
    while (i < n_wifi_res && idx < len - 1) {
        mac[i] = "";
        for (var j = 2; j > 0; j--) {
            mac[i] = mac[i].concat(bytes[7 + i * 4 + j].toString(16) + ":");
        }
        mac[i] = mac[i].concat(bytes[7 + i * 4 + 0].toString(16));
        object[i] = {
            rssi: bytes[7 + i * 4 + 3] - 128,
            mac: mac[i],
        };
        decoded[String(1 + i)] = object[i];
        i++;
        idx += 4;
    }
    return decoded;
}
function decodeUbloxSatellitesMessage(bytes) {
    //Skip header 0 and 1
    var len = bytes[1];
    var n_sat = bytes[2];
    var decoded = {
        N_sat: n_sat,
    };
    var i = 0;
    var idx = 2;
    var object = [];
    while (i < n_sat && idx < len - 1) {
        object[i] = {
            id: bytes[6 * i + 3],
            cn0: bytes[6 * i + 4],
            ele: bytes[6 * i + 5],
            azi: bytes[6 * i + 7] << 8 | bytes[6 * i + 6],
            con: get_constellation_name(bytes[6 * i + 8]),
        };
        decoded[String(1 + i)] = object[i];
        i++;
        idx += 6;
    }
    decoded["N_reported"] = i;
    return decoded;
}
function decodeReadFlashMessage(bytes) {
    var decoded = {};
    var msg_len = bytes.length;
    var i = 0;
    var fPort = 0;
    var len = 0;
    var msg = [];
    var msg_idx = 0;
    var timestamp = [];
    var object = [];
    var parsed_msg = {};
    while (i < msg_len - 7) {
        fPort = bytes[i]; //Read fPort
        //We do not need id
        len = bytes[i + 2]; //Read msg len
        msg = bytes.slice(i + 1, i + len + 3); //Slice message part
        i += len + 3;
        timestamp = bytes[i + 3] << 24 | bytes[i + 2] << 16 | bytes[i + 1] << 8 | bytes[i];
        i += 4;
        parsed_msg = {};
        if (fPort != 29) {
            parsed_msg = Decoder(msg, fPort);
        }
        object[msg_idx] = {
            data: parsed_msg,
            fPort: fPort,
            timestamp: timestamp,
        };
        decoded[String(1 + msg_idx)] = object[msg_idx];
        msg_idx++;
    }
    return decoded;
}

function decodeUbloxLocationMessageShort(bytes){
    var fix_timestamp = bytes[5] << 24 | bytes[4] << 16| bytes[3] << 8 | bytes[2];
    var latitude = bytes[9] << 24 | bytes[8] << 16| bytes[7] << 8 | bytes[6];
    latitude = latitude / 10000000; 
    var longitude = bytes[13] << 24 | bytes[12] << 16| bytes[11] << 8 | bytes[10];
    longitude = longitude / 10000000; 
    var h_acc_est = bytes[15] << 8 | bytes[14];
    var decoded = {
        fix_timestamp: fix_timestamp,
        latitude: latitude,
        longitude: longitude,
        h_acc_est: h_acc_est
    };
    return decoded;
}

function decodeDeviceMessage(bytes) {
    var len = bytes[1];
    var msg_len = bytes[2];
    var msg = bytes.slice(3, 3 + msg_len);
    var seq = bytes[3 + msg_len]
    var retry = bytes[4 + msg_len];

    var decoded = {
        len: len,
        msg_len: msg_len,
        msg: msg,
        seq: seq,
        retry: retry,
    };

    return decoded;
}

function decodedMemfault(bytes) {
    var len = bytes[1];
    var msg = bytes.slice(2);

    var decoded = {
        len: len,
        msg: msg,
    };

    return decoded;
}



function uint16(b1, b2) {
    return (b1 & 0xff) | ((b2 & 0xff) << 8);
}

function getBandDisplayName(start, stop) {
    if (start >= 1920 && stop <= 1980) {
        return "1";
    } else if (start >= 2110 && stop <= 2170) {
        return "1d";
    } else if (start >= 1710 && stop <= 1785) {
        return "3";
    } else if (start >= 1805 && stop <= 1880) {
        return "3d";
    } else if (start >= 2500 && stop <= 2570) {
        return "7";
    } else if (start >= 2620 && stop <= 2690) {
        return "7d";
    } else if (start >= 880 && stop <= 915) {
        return "8";
    } else if (start >= 925 && stop <= 960) {
        return "8d";
    } else if (start >= 832 && stop <= 862) {
        return "20";
    } else if (start >= 791 && stop <= 821) {
        return "20d";
    } else if (start >= 2401 && stop <= 2484) {
        return "wifi_bt";
    } else {
        return "unknown";
    }
}

function decodeRfScannerMessage(bytes) {
    var len = bytes[1];
    var msg = bytes.slice(2);
    var decoded = {
        version: msg[0],
        should_alert: msg[1],
    };
    var offset = 2;
    var range_len = 6;
    for (var i = 0; i < (len - offset) / range_len; i++) {
        var x = offset + range_len * i;
        var c = 0;
        start = uint16(msg[x + c++], msg[x + c++]) / 10;
        stop = uint16(msg[x + c++], msg[x + c++]) / 10;
        decoded["band_" + getBandDisplayName(start, stop)] = {
            start: start,
            stop: stop,
            peak_count: msg[x + c++],
            max_rssi: -msg[x + c++],
        };
    }
    return decoded;
}

function decodeFence(bytes) {
    //Skip header 0
    var len = bytes[1];
    var success = bytes[2];
    var N = bytes[3];
    var voltage = uint16(bytes[4], bytes[5]);
    var energy = uint16(bytes[6], bytes[7]);

    var decoded = {
        success: success,
        N: N,
        voltage: voltage,
        energy: energy,
    };

    return decoded;
}

function decodeFlashStatusMessage(bytes) {
    //Skip header 0
    var len = bytes[1];
    var percentage = bytes[2];
    var n_msg = bytes[6] << 24 | bytes[5] << 16 | bytes[4] << 8 | bytes[3];

    var decoded = {
        percentage: percentage,
        n_msg: n_msg,
    };

    return decoded;
}

function decodeBluetoothCMDQMessage(bytes) {
    var len = bytes[1];
    var n_res = Math.floor(len / 13);
    var decoded = {};
    for(var i = 0; i < n_res; i++) {
        var offset = 2 + (i * 13);
        var measurement_timestamp = ((bytes[offset + 3] & 0xff) << 24)| ((bytes[offset + 2] & 0xff) << 16) | ((bytes[offset + 1] & 0xff) << 8) | (bytes[offset] & 0xff);
        var rr_median = bytes[offset + 4];
        var rr_median_modesum = bytes[offset + 5];
        var activity_average = bytes[offset + 6];
        var activity_max = bytes[offset + 7];
        var active_min_in_last_hour = bytes[offset + 8];
        var raw_temperature = uint16(bytes[offset + 10], bytes[offset + 9]);
        var temperature = 0;
        var cmdq_success = 0;
        if (raw_temperature > 0) {
            temperature = (raw_temperature*0.0248) - 18.09;
            cmdq_success = 1;
        }
        var h_impedance = uint16(bytes[offset + 12], bytes[offset + 11]); 
        decoded[i]= {
            cmdq_timestamp: measurement_timestamp,
            cmdq_rr_median: rr_median,
            cmdq_rr_median_modesum: rr_median_modesum,
            cmdq_activity_average: activity_average,
            cmdq_activity_max: activity_max,
            cmdq_active_min_in_last_hour: active_min_in_last_hour,
            cmdq_temp: temperature,
            cmdq_raw_temp: raw_temperature,
            cmdq_h_impedance: h_impedance,
            cmdq_success:cmdq_success 
        }
    }
    return decoded;
}

function decodeOpenSkyDetection(bytes){
    var decoded = {};
    var len = bytes[1];
    var n_res = Math.floor(len / 2);
    for(var i = 0; i < n_res; i++) {
        decoded[i] = {
            average_rssi: -bytes[2 + (i * 2)],
            max_rssi: -bytes[3 + (i * 2)]
        }
    }
    return decoded;
}

function decodeLastPosition(bytes) {
    if (bytes[0] == 0xfe) {
    var value = bytes[5] << 24 | bytes[4] << 16 | bytes[3] << 8 | bytes[2];
    var latitude = value / 10000000; // gps latitude,units: °
    value = bytes[9] << 24 | bytes[8] << 16 | bytes[7] << 8 | bytes[6];
    var longitude = value / 10000000; // gps longitude,units: °
    value = bytes[13] << 24 | bytes[12] << 16 | bytes[11] << 8 | bytes[10];
    var altitude = value / 1000;
    var fix_time = bytes[17] << 24 | bytes[16] << 16 | bytes[15] << 8 | bytes[14];
    var decoded = {
        latitude: latitude,
        longitude: longitude,
        altitude: altitude,
        fix_time: fix_time,
    };
  };
    return decoded;
  }

function Decode(fPort, bytes, variables) {
    // Decode an uplink message from a buffer
    // (array) of bytes to an object of fields.
    var decoded = {};
    if (fPort == 1) {
        decoded = decodeGNSSMessage(bytes);
    }
    else if (fPort == 2) {
        decoded = decodeUbloxLocationMessage(bytes);
    }
    else if (fPort == 4) {
        decoded = decodeStatusMessage(bytes);
    }
    else if (fPort == 5) {
        decoded = decodeLRSatellitesMessage(bytes);
    }
    else if (fPort == 6 || fPort == 7 || fPort == 10) {
        decoded = decodeScanMessage(bytes, fPort);
    }
    else if (fPort == 8) {
        decoded = decodeRfScannerMessage(bytes);
    }
    else if (fPort == 9) {
        decoded = decodeUbloxSatellitesMessage(bytes);
    }
    else if (fPort == 11) {
        decoded = decodeLastScanMessage(bytes);
    }
    else if (fPort == 12) {
        decoded = decodeFence(bytes);
    }
    else if (fPort == 13) {
        decoded = decodeUbloxLocationMessageShort(bytes);
    }
    else if (fPort == 14) {
        decoded = decodeFlashStatusMessage(bytes);
    }
    else if (fPort == 15) {
        decoded = decodeBluetoothCMDQMessage(bytes);
    }
    else if (fPort == 16) {
        decoded = decodeUbloxLocationMessageShort(bytes);
    }
    else if (fPort == 17) {
        decoded = decodeOpenSkyDetection(bytes);
    }
    else if (fPort == 27) {
        decoded = decodedMemfault(bytes);
    }
    else if (fPort == 28) {
        decoded = decodeDeviceMessage(bytes);
    }
    else if (fPort == 29) {
        decoded = decodeReadFlashMessage(bytes);
    }
    else if (fPort == 31) {
        decoded = decodeLastPosition(bytes);
    }
    return decoded;
}

// v3 to v4 compatibility wrapper
function decodeUplink(input) {
  return {
    data: Decode(input.fPort, input.bytes, input.variables)
  };
}
```

### 5.6 Legacy first generation OpenCollar decoders and encoders (not for Edge devices)

These describe the STM32 based OpenCollar trackers (2019 to 2021): GPS on port 1 (24 bit packed lat/lon), status on port 12, settings block on port 3, location history on port 11, VSWR on port 30, commands on port 99. They are listed because the toolset offers them next to the Edge decoders and because the TTN device repository entry for Smart Parks (`lorawan-devices`) only describes this generation (firmware 2.6, hardware 2.3, ABP EU868 profile).

`d_opencollar_tracker_v1.js`, https://raw.githubusercontent.com/SmartParksOrg/smartparks-toolset/main/assets/Decoders/d_opencollar_tracker_v1.js (commit bb98fb8):

```javascript
//note some values need to be tuned to the hardware in here, make sure to do so
function get_num(x, min, max, precision, round) {

  var range = max - min;
  var new_range = (Math.pow(2, precision) - 1) / range;
  var back_x = x / new_range;

  if (back_x === 0) {
    back_x = min;
  } else if (back_x === (max - min)) {
    back_x = max;
  } else {
    back_x += min;
  }
  return Math.round(back_x * Math.pow(10, round)) / Math.pow(10, round);
}

// TTN decoder function, using the ChripStack decoder
function Decoder(bytes) {
  return Decode(port, bytes);
}

// ChirpStack decode function
function Decode(fPort, bytes) {

  var decoded = {};
  var cnt = 0;
  var resetCause_dict = {
    0: "POWERON",
    1: "EXTERNAL",
    2: "SOFTWARE",
    3: "WATCHDOG",
    4: "FIREWALL",
    5: "OTHER",
    6: "STANDBY"
  };


  // settings
  if (fPort === 3) {
    decoded.system_status_interval = (bytes[1] << 8) | bytes[0];
    decoded.system_functions = {};//bytes[2];
    decoded.system_functions.gps_periodic = ((bytes[2] >> 0) & 0x01) ? 1 : 0;
    decoded.system_functions.gps_triggered = ((bytes[2] >> 1) & 0x01) ? 1 : 0;
    decoded.system_functions.gps_hot_fix = ((bytes[2] >> 2) & 0x01) ? 1 : 0;
    decoded.system_functions.accelerometer_enabled = ((bytes[2] >> 3) & 0x01) ? 1 : 0;
    decoded.system_functions.light_enabled = ((bytes[2] >> 4) & 0x01) ? 1 : 0;
    decoded.system_functions.temperature_enabled = ((bytes[2] >> 5) & 0x01) ? 1 : 0;
    decoded.system_functions.humidity_enabled = ((bytes[2] >> 6) & 0x01) ? 1 : 0;
    decoded.system_functions.charging_enabled = ((bytes[2] >> 7) & 0x01) ? 1 : 0;

    decoded.lorawan_datarate_adr = {};//bytes[3];
    decoded.lorawan_datarate_adr.datarate = bytes[3] & 0x0f;
    decoded.lorawan_datarate_adr.confirmed_uplink = ((bytes[3] >> 6) & 0x01) ? 1 : 0;
    decoded.lorawan_datarate_adr.adr = ((bytes[3] >> 7) & 0x01) ? 1 : 0;

    decoded.gps_periodic_interval = (bytes[5] << 8) | bytes[4];
    decoded.gps_triggered_interval = (bytes[7] << 8) | bytes[6];
    decoded.gps_triggered_threshold = bytes[8];
    decoded.gps_triggered_duration = bytes[9];
    decoded.gps_cold_fix_timeout = (bytes[11] << 8) | bytes[10];
    decoded.gps_hot_fix_timeout = (bytes[13] << 8) | bytes[12];
    decoded.gps_min_fix_time = bytes[14];
    decoded.gps_min_ehpe = bytes[15];
    decoded.gps_hot_fix_retry = bytes[16];
    decoded.gps_cold_fix_retry = bytes[17];
    decoded.gps_fail_retry = bytes[18];
    decoded.gps_settings = {};//bytes[19];
    decoded.gps_settings.d3_fix = ((bytes[19] >> 0) & 0x01) ? 1 : 0;
    decoded.gps_settings.fail_backoff = ((bytes[19] >> 1) & 0x01) ? 1 : 0;
    decoded.gps_settings.hot_fix = ((bytes[19] >> 2) & 0x01) ? 1 : 0;
    decoded.gps_settings.fully_resolved = ((bytes[19] >> 3) & 0x01) ? 1 : 0;
    decoded.system_voltage_interval = bytes[20];
    decoded.gps_charge_min = bytes[21] * 10 + 2500;
    decoded.system_charge_min = bytes[22] * 10 + 2500;
    decoded.system_charge_max = bytes[23] * 10 + 2500;
    decoded.system_input_charge_min = (bytes[25] << 8) | bytes[24];
    decoded.pulse_threshold = bytes[26];
    decoded.pulse_on_timeout = bytes[27];
    decoded.pulse_min_interval = (bytes[29] << 8) | bytes[28];
    decoded.gps_accel_z_threshold = ((bytes[31] << 8) | bytes[30]) - 2000;
    decoded.fw_version = (bytes[33] << 8) | bytes[32];
  } else if (fPort === 12) {
    decoded.resetCause = resetCause_dict[bytes[0] & 0x07];
    decoded.system_state_timeout = bytes[0] >> 3;
    decoded.battery = bytes[1] * 10 + 2500; // result in mV
    decoded.temperature = get_num(bytes[2], -20, 80, 8, 1);
    decoded.system_functions_errors = {};//bytes[5];
    decoded.system_functions_errors.gps_periodic_error = ((bytes[3] >> 0) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.gps_triggered_error = ((bytes[3] >> 1) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.gps_fix_error = ((bytes[3] >> 2) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.accelerometer_error = ((bytes[3] >> 3) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.light_error = ((bytes[3] >> 4) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.charging_status = (bytes[3] >> 5) & 0x07;
    decoded.latitude = ((bytes[4] << 16) >>> 0) + ((bytes[5] << 8) >>> 0) + bytes[6];
    decoded.longitude = ((bytes[7] << 16) >>> 0) + ((bytes[8] << 8) >>> 0) + bytes[9];
    if (decoded.latitude !== 0 && decoded.longitude !== 0) {
      decoded.latitude = (decoded.latitude / 16777215.0 * 180) - 90;
      decoded.longitude = (decoded.longitude / 16777215.0 * 360) - 180;
      decoded.latitude = Math.round(decoded.latitude * 100000) / 100000;
      decoded.longitude = Math.round(decoded.longitude * 100000) / 100000;
    }
    decoded.gps_resend = bytes[10];
    decoded.accelx = get_num(bytes[11], -2000, 2000, 8, 1);
    decoded.accely = get_num(bytes[12], -2000, 2000, 8, 1);
    decoded.accelz = get_num(bytes[13], -2000, 2000, 8, 1);
    decoded.battery_low = (bytes[15] << 8) | bytes[14];
    ; // result in mV
    decoded.gps_on_time_total = (bytes[17] << 8) | bytes[16];
    decoded.gps_time = bytes[18] | (bytes[19] << 8) | (bytes[20] << 16) | (bytes[21] << 24);
    var d = new Date(decoded.gps_time * 1000);
    decoded.gps_time_decoded = d.toLocaleString();
    decoded.pulse_counter = bytes[22];
    decoded.pulse_energy = (bytes[23] << 4) | (bytes[24] | (bytes[25] << 8) >> 12);
    decoded.pulse_voltage = (bytes[24] | (bytes[25] << 8)) & 0x0fff;
    decoded.voltage_fence_v = decoded.pulse_voltage * 8;
  } else if (fPort === 1) {
    decoded.latitude = ((bytes[cnt++] << 16) >>> 0) + ((bytes[cnt++] << 8) >>> 0) + bytes[cnt++];
    decoded.longitude = ((bytes[cnt++] << 16) >>> 0) + ((bytes[cnt++] << 8) >>> 0) + bytes[cnt++];
    if (decoded.latitude !== 0 && decoded.longitude !== 0) {
      decoded.latitude = (decoded.latitude / 16777215.0 * 180) - 90;
      decoded.longitude = (decoded.longitude / 16777215.0 * 360) - 180;
      decoded.latitude = Math.round(decoded.latitude * 100000) / 100000;
      decoded.longitude = Math.round(decoded.longitude * 100000) / 100000;
    }
    decoded.alt = bytes[cnt++] | (bytes[cnt++] << 8);
    decoded.satellites = (bytes[cnt] >> 4);
    decoded.hdop = (bytes[cnt++] & 0x0f);
    decoded.time_to_fix = bytes[cnt++];
    decoded.epe = bytes[cnt++];
    decoded.snr = bytes[cnt++];
    decoded.lux = bytes[cnt++];
    decoded.motion = bytes[cnt++];
    decoded.time = bytes[cnt++] | (bytes[cnt++] << 8) | (bytes[cnt++] << 16) | (bytes[cnt++] << 24);
    var d = new Date(decoded.time * 1000);
    decoded.time_decoded = d.toLocaleString();
  } else if (fPort === 11) {
    var locations = [];
    for (i = 0; i < 5; i++) {
      var location = {}
      location.latitude = ((bytes[cnt++] << 16) >>> 0) + ((bytes[cnt++] << 8) >>> 0) + bytes[cnt++];
      location.longitude = ((bytes[cnt++] << 16) >>> 0) + ((bytes[cnt++] << 8) >>> 0) + bytes[cnt++];
      if (location.latitude !== 0 && location.longitude !== 0) {
        location.latitude = (location.latitude / 16777215.0 * 180) - 90;
        location.longitude = (location.longitude / 16777215.0 * 360) - 180;
        location.latitude = Math.round(location.latitude * 100000) / 100000;
        location.longitude = Math.round(location.longitude * 100000) / 100000;
      }
      location.time = bytes[cnt++] | (bytes[cnt++] << 8) | (bytes[cnt++] << 16) | (bytes[cnt++] << 24);
      var d = new Date(location.time * 1000);
      location.time_decoded = d.toLocaleString();
      locations.push(location);
    }
    decoded.locations = JSON.stringify(locations);
  } else if (fPort === 30) {
    var vswr = [];
    for (i = 0; i < bytes.length; i++) {
      var value = (bytes[i]);
      vswr.push(value);
    }
    decoded.vswr = vswr;
  }

  return decoded;
}

```

`d_opencollar_v3.js`, https://raw.githubusercontent.com/SmartParksOrg/smartparks-toolset/main/assets/Decoders/d_opencollar_v3.js (commit bb98fb8; port 11 holds 20 packed locations with minute resolution time since 1600000000, port 12 adds `downlink_counter`):

```javascript
//note some values need to be tuned to the hardware in here, make sure to do so
function get_num(x, min, max, precision, round) {

  var range = max - min;
  var new_range = (Math.pow(2, precision) - 1) / range;
  var back_x = x / new_range;

  if (back_x === 0) {
    back_x = min;
  }
  else if (back_x === (max - min)) {
    back_x = max;
  }
  else {
    back_x += min;
  }
  return Math.round(back_x * Math.pow(10, round)) / Math.pow(10, round);
}

// TTN decoder function, using the ChripStack decoder
function Decoder(bytes) {
  return Decoder(port, bytes);
}

// ChirpStack decode function
function Decode(port, bytes) {

  var decoded = {};
  var cnt = 0;
  var resetCause_dict = {
    0: "POWERON",
    1: "EXTERNAL",
    2: "SOFTWARE",
    3: "WATCHDOG",
    4: "FIREWALL",
    5: "OTHER",
    6: "STANDBY"
  };


  // settings
  if (port === 3) {
    decoded.system_status_interval = (bytes[1] << 8) | bytes[0];
    decoded.system_functions = {};//bytes[2];
    decoded.system_functions.gps_periodic = ((bytes[2] >> 0) & 0x01) ? 1 : 0;
    decoded.system_functions.gps_triggered = ((bytes[2] >> 1) & 0x01) ? 1 : 0;
    decoded.system_functions.gps_hot_fix = ((bytes[2] >> 2) & 0x01) ? 1 : 0;
    decoded.system_functions.accelerometer_enabled = ((bytes[2] >> 3) & 0x01) ? 1 : 0;
    decoded.system_functions.light_enabled = ((bytes[2] >> 4) & 0x01) ? 1 : 0;
    decoded.system_functions.temperature_enabled = ((bytes[2] >> 5) & 0x01) ? 1 : 0;
    decoded.system_functions.humidity_enabled = ((bytes[2] >> 6) & 0x01) ? 1 : 0;
    decoded.system_functions.charging_enabled = ((bytes[2] >> 7) & 0x01) ? 1 : 0;

    decoded.lorawan_datarate_adr = {};//bytes[3];
    decoded.lorawan_datarate_adr.datarate = bytes[3] & 0x0f;
    decoded.lorawan_datarate_adr.confirmed_uplink = ((bytes[3] >> 6) & 0x01) ? 1 : 0;
    decoded.lorawan_datarate_adr.adr = ((bytes[3] >> 7) & 0x01) ? 1 : 0;

    decoded.gps_periodic_interval = (bytes[5] << 8) | bytes[4];
    decoded.gps_triggered_interval = (bytes[7] << 8) | bytes[6];
    decoded.gps_triggered_threshold = bytes[8];
    decoded.gps_triggered_duration = bytes[9];
    decoded.gps_cold_fix_timeout = (bytes[11] << 8) | bytes[10];
    decoded.gps_hot_fix_timeout = (bytes[13] << 8) | bytes[12];
    decoded.gps_min_fix_time = bytes[14];
    decoded.gps_min_ehpe = bytes[15];
    decoded.gps_hot_fix_retry = bytes[16];
    decoded.gps_cold_fix_retry = bytes[17];
    decoded.gps_fail_retry = bytes[18];
    decoded.gps_settings = {};//bytes[19];
    decoded.gps_settings.d3_fix = ((bytes[19] >> 0) & 0x01) ? 1 : 0;
    decoded.gps_settings.fail_backoff = ((bytes[19] >> 1) & 0x01) ? 1 : 0;
    decoded.gps_settings.hot_fix = ((bytes[19] >> 2) & 0x01) ? 1 : 0;
    decoded.gps_settings.fully_resolved = ((bytes[19] >> 3) & 0x01) ? 1 : 0;
    decoded.system_voltage_interval = bytes[20];
    decoded.gps_charge_min = bytes[21]*10+2500;
    decoded.system_charge_min = bytes[22]*10+2500;
    decoded.system_charge_max = bytes[23]*10+2500;
    decoded.system_input_charge_min = (bytes[25] << 8) | bytes[24];
    decoded.pulse_threshold = bytes[26];
    decoded.pulse_on_timeout = bytes[27];
    decoded.pulse_min_interval = (bytes[29] << 8) | bytes[28];
    decoded.gps_accel_z_threshold = ((bytes[31] << 8) | bytes[30])-2000;
    decoded.fw_version = (bytes[33] << 8) | bytes[32];
  }
  else if (port === 12) {
    decoded.resetCause = resetCause_dict[bytes[0]&0x07];
    decoded.system_state_timeout = bytes[0]>>3;
    decoded.battery = bytes[1]*10+2500; // result in mV
    decoded.temperature = get_num(bytes[2], -20, 80, 8, 1);
    decoded.system_functions_errors = {};//bytes[5];
    decoded.system_functions_errors.gps_periodic_error = ((bytes[3] >> 0) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.gps_triggered_error = ((bytes[3] >> 1) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.gps_fix_error = ((bytes[3] >> 2) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.accelerometer_error = ((bytes[3] >> 3) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.light_error = ((bytes[3] >> 4) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.charging_status = (bytes[3] >> 5) & 0x07;
    decoded.lat = ((bytes[4] << 16) >>> 0) + ((bytes[5] << 8) >>> 0) + bytes[6];
    decoded.lon = ((bytes[7] << 16) >>> 0) + ((bytes[8] << 8) >>> 0) + bytes[9];
    if(decoded.lat!==0 && decoded.lon!==0){
      decoded.lat = (decoded.lat / 16777215.0 * 180) - 90;
      decoded.lon = (decoded.lon / 16777215.0 * 360) - 180;
      decoded.lat = Math.round(decoded.lat*100000)/100000;
      decoded.lon = Math.round(decoded.lon*100000)/100000;
    }
    decoded.gps_resend = bytes[10];
    decoded.accelx = get_num(bytes[11], -2000, 2000, 8, 1);
    decoded.accely = get_num(bytes[12], -2000, 2000, 8, 1);
    decoded.accelz = get_num(bytes[13], -2000, 2000, 8, 1);
    decoded.battery_low = (bytes[15] << 8) | bytes[14];; // result in mV
    decoded.gps_on_time_total = (bytes[17] << 8) | bytes[16];
    decoded.gps_time = bytes[18] | (bytes[19] << 8) | (bytes[20] << 16) | (bytes[21] << 24);
    var d= new Date(decoded.gps_time*1000);
    decoded.gps_time_decoded = d.toLocaleString();
    decoded.pulse_counter = bytes[22];
    decoded.pulse_energy = (bytes[23]<<4) | (bytes[24] | (bytes[25] << 8)>>12);
    decoded.pulse_voltage = (bytes[24] | (bytes[25] << 8)) & 0x0fff;
    decoded.voltage_fence_v = decoded.pulse_voltage * 8;
    decoded.downlink_counter = (bytes[26] | (bytes[27] << 8));
  }
  else if (port === 1) {
    decoded.lat = ((bytes[cnt++] << 16) >>> 0) + ((bytes[cnt++] << 8) >>> 0) + bytes[cnt++];
    decoded.lon = ((bytes[cnt++] << 16) >>> 0) + ((bytes[cnt++] << 8) >>> 0) + bytes[cnt++];
    if(decoded.lat!==0 && decoded.lon!==0){
      decoded.lat = (decoded.lat / 16777215.0 * 180) - 90;
      decoded.lon = (decoded.lon / 16777215.0 * 360) - 180;
      decoded.lat = Math.round(decoded.lat*100000)/100000;
      decoded.lon = Math.round(decoded.lon*100000)/100000;
    }
    decoded.alt = bytes[cnt++] | (bytes[cnt++] << 8);
    decoded.satellites = (bytes[cnt] >> 4);
    decoded.hdop = (bytes[cnt++] & 0x0f);
    decoded.time_to_fix = bytes[cnt++];
    decoded.epe = bytes[cnt++];
    decoded.snr = bytes[cnt++];
    decoded.lux = bytes[cnt++];
    decoded.motion = bytes[cnt++];
    decoded.gps_time = bytes[cnt++] | (bytes[cnt++] << 8) | (bytes[cnt++] << 16) | (bytes[cnt++] << 24);
    var d= new Date(decoded.gps_time*1000);
    decoded.gps_time_decoded = d.toLocaleString();
  }
  else if (port === 11) {
    var locations=[];
    for(i = 0; i < 20; i++){
      var location={}
      location.lat = ((bytes[cnt++] << 16) >>> 0) + ((bytes[cnt++] << 8) >>> 0) + bytes[cnt++];
      location.lon = ((bytes[cnt++] << 16) >>> 0) + ((bytes[cnt++] << 8) >>> 0) + bytes[cnt++];
      location.gps_time = ((bytes[cnt++] << 16) >>> 0) + ((bytes[cnt++] << 8) >>> 0) + bytes[cnt++];
      location.gps_time = location.gps_time * 60 + 1600000000;
      var d= new Date(location.gps_time*1000);
      location.gps_time_decoded = d.toLocaleString();
      var fix_stats= bytes[cnt++];
      location.motion = fix_stats>>7;
      location.epe = ((fix_stats>>4)&0x07)*12;
      location.ttf = (fix_stats&0x0f)*5;
      if(location.lat!==0 && location.lon!==0){
        location.lat = (location.lat / 16777215.0 * 180) - 90;
        location.lon = (location.lon / 16777215.0 * 360) - 180;
        location.lat = Math.round(location.lat*100000)/100000;
        location.lon = Math.round(location.lon*100000)/100000;
        // push only valid locations
        locations.push(location);
      }
    }
    decoded.locations=JSON.stringify(locations);
  }
  else if (port === 30) {
    var vswr=[];
    for(i = 0; i < bytes.length; i++){
      var value=(bytes[i]);
      vswr.push(value);
    }
    decoded.vswr=vswr;
  }

  return decoded;
}

```

`d_opencollar_fence_v2.js`, https://raw.githubusercontent.com/SmartParksOrg/smartparks-toolset/main/assets/Decoders/d_opencollar_fence_v2.js (commit bb98fb8; first generation fence monitor, `fence_calibration_factor` variable, default 8):

```javascript
//note some values need to be tuned to the hardware in here, make sure to do so
function get_num(x, min, max, precision, round) {

  var range = max - min;
  var new_range = (Math.pow(2, precision) - 1) / range;
  var back_x = x / new_range;

  if (back_x === 0) {
    back_x = min;
  } else if (back_x === (max - min)) {
    back_x = max;
  } else {
    back_x += min;
  }
  return Math.round(back_x * Math.pow(10, round)) / Math.pow(10, round);
}

// TTN decoder function, using the ChripStack decoder
function Decoder(bytes) {
  return Decode(port, bytes, null);
}

// ChirpStack decode function
function Decode(fPort, bytes, variables) {
  if (!variables) {
    variables = {};
  }
  if (!variables.fence_calibration_factor) {
    variables.fence_calibration_factor = 8;
  }
  var decoded = {};
  var cnt = 0;
  var resetCause_dict = {
    0: "POWERON",
    1: "EXTERNAL",
    2: "SOFTWARE",
    3: "WATCHDOG",
    4: "FIREWALL",
    5: "OTHER",
    6: "STANDBY"
  };


  // settings
  if (fPort === 3) {
    decoded.system_status_interval = (bytes[1] << 8) | bytes[0];
    decoded.system_functions = {};//bytes[2];
    decoded.system_functions.gps_periodic = ((bytes[2] >> 0) & 0x01) ? 1 : 0;
    decoded.system_functions.gps_triggered = ((bytes[2] >> 1) & 0x01) ? 1 : 0;
    decoded.system_functions.gps_hot_fix = ((bytes[2] >> 2) & 0x01) ? 1 : 0;
    decoded.system_functions.accelerometer_enabled = ((bytes[2] >> 3) & 0x01) ? 1 : 0;
    decoded.system_functions.light_enabled = ((bytes[2] >> 4) & 0x01) ? 1 : 0;
    decoded.system_functions.temperature_enabled = ((bytes[2] >> 5) & 0x01) ? 1 : 0;
    decoded.system_functions.humidity_enabled = ((bytes[2] >> 6) & 0x01) ? 1 : 0;
    decoded.system_functions.charging_enabled = ((bytes[2] >> 7) & 0x01) ? 1 : 0;

    decoded.lorawan_datarate_adr = {};//bytes[3];
    decoded.lorawan_datarate_adr.datarate = bytes[3] & 0x0f;
    decoded.lorawan_datarate_adr.confirmed_uplink = ((bytes[3] >> 6) & 0x01) ? 1 : 0;
    decoded.lorawan_datarate_adr.adr = ((bytes[3] >> 7) & 0x01) ? 1 : 0;

    decoded.gps_periodic_interval = (bytes[5] << 8) | bytes[4];
    decoded.gps_triggered_interval = (bytes[7] << 8) | bytes[6];
    decoded.gps_triggered_threshold = bytes[8];
    decoded.gps_triggered_duration = bytes[9];
    decoded.gps_cold_fix_timeout = (bytes[11] << 8) | bytes[10];
    decoded.gps_hot_fix_timeout = (bytes[13] << 8) | bytes[12];
    decoded.gps_min_fix_time = bytes[14];
    decoded.gps_min_ehpe = bytes[15];
    decoded.gps_hot_fix_retry = bytes[16];
    decoded.gps_cold_fix_retry = bytes[17];
    decoded.gps_fail_retry = bytes[18];
    decoded.gps_settings = {};//bytes[19];
    decoded.gps_settings.d3_fix = ((bytes[19] >> 0) & 0x01) ? 1 : 0;
    decoded.gps_settings.fail_backoff = ((bytes[19] >> 1) & 0x01) ? 1 : 0;
    decoded.gps_settings.hot_fix = ((bytes[19] >> 2) & 0x01) ? 1 : 0;
    decoded.gps_settings.fully_resolved = ((bytes[19] >> 3) & 0x01) ? 1 : 0;
    decoded.system_voltage_interval = bytes[20];
    decoded.gps_charge_min = bytes[21] * 10 + 2500;
    decoded.system_charge_min = bytes[22] * 10 + 2500;
    decoded.system_charge_max = bytes[23] * 10 + 2500;
    decoded.system_input_charge_min = (bytes[25] << 8) | bytes[24];
    decoded.pulse_threshold = bytes[26];
    decoded.pulse_on_timeout = bytes[27];
    decoded.pulse_min_interval = (bytes[29] << 8) | bytes[28];
    decoded.gps_accel_z_threshold = ((bytes[31] << 8) | bytes[30]) - 2000;
    decoded.fw_version = (bytes[33] << 8) | bytes[32];
  } else if (fPort === 12) {
    decoded.resetCause = resetCause_dict[bytes[0] & 0x07];
    decoded.system_state_timeout = bytes[0] >> 3;
    decoded.battery = bytes[1] * 10 + 2500; // result in mV
    decoded.temperature = get_num(bytes[2], -20, 80, 8, 1);
    decoded.system_functions_errors = {};//bytes[5];
    decoded.system_functions_errors.gps_periodic_error = ((bytes[3] >> 0) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.gps_triggered_error = ((bytes[3] >> 1) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.gps_fix_error = ((bytes[3] >> 2) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.accelerometer_error = ((bytes[3] >> 3) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.light_error = ((bytes[3] >> 4) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.charging_status = (bytes[3] >> 5) & 0x07;
    decoded.latitude = ((bytes[4] << 16) >>> 0) + ((bytes[5] << 8) >>> 0) + bytes[6];
    decoded.longitude = ((bytes[7] << 16) >>> 0) + ((bytes[8] << 8) >>> 0) + bytes[9];
    if (decoded.latitude !== 0 && decoded.longitude !== 0) {
      decoded.latitude = (decoded.latitude / 16777215.0 * 180) - 90;
      decoded.longitude = (decoded.longitude / 16777215.0 * 360) - 180;
      decoded.latitude = Math.round(decoded.latitude * 100000) / 100000;
      decoded.longitude = Math.round(decoded.longitude * 100000) / 100000;
    }
    decoded.gps_resend = bytes[10];
    decoded.accelx = get_num(bytes[11], -2000, 2000, 8, 1);
    decoded.accely = get_num(bytes[12], -2000, 2000, 8, 1);
    decoded.accelz = get_num(bytes[13], -2000, 2000, 8, 1);
    decoded.battery_low = (bytes[15] << 8) | bytes[14];
    ; // result in mV
    decoded.gps_on_time_total = (bytes[17] << 8) | bytes[16];
    decoded.gps_time = bytes[18] | (bytes[19] << 8) | (bytes[20] << 16) | (bytes[21] << 24);
    var d = new Date(decoded.gps_time * 1000);
    decoded.gps_time_decoded = d.toLocaleString();
    decoded.pulse_counter = bytes[22];
    decoded.pulse_energy = (bytes[23] << 4) | (bytes[24] | (bytes[25] << 8) >> 12);
    decoded.pulse_voltage = (bytes[24] | (bytes[25] << 8)) & 0x0fff;
    decoded.voltage_fence_v = decoded.pulse_voltage * variables.fence_calibration_factor;
  } else if (fPort === 1) {
    decoded.latitude = ((bytes[cnt++] << 16) >>> 0) + ((bytes[cnt++] << 8) >>> 0) + bytes[cnt++];
    decoded.longitude = ((bytes[cnt++] << 16) >>> 0) + ((bytes[cnt++] << 8) >>> 0) + bytes[cnt++];
    if (decoded.latitude !== 0 && decoded.longitude !== 0) {
      decoded.latitude = (decoded.latitude / 16777215.0 * 180) - 90;
      decoded.longitude = (decoded.longitude / 16777215.0 * 360) - 180;
      decoded.latitude = Math.round(decoded.latitude * 100000) / 100000;
      decoded.longitude = Math.round(decoded.longitude * 100000) / 100000;
    }
    decoded.alt = bytes[cnt++] | (bytes[cnt++] << 8);
    decoded.satellites = (bytes[cnt] >> 4);
    decoded.hdop = (bytes[cnt++] & 0x0f);
    decoded.time_to_fix = bytes[cnt++];
    decoded.epe = bytes[cnt++];
    decoded.snr = bytes[cnt++];
    decoded.lux = bytes[cnt++];
    decoded.motion = bytes[cnt++];
    decoded.time = bytes[cnt++] | (bytes[cnt++] << 8) | (bytes[cnt++] << 16) | (bytes[cnt++] << 24);
    var d = new Date(decoded.time * 1000);
    decoded.time_decoded = d.toLocaleString();
  } else if (fPort === 11) {
    var locations = [];
    for (i = 0; i < 5; i++) {
      var location = {}
      location.latitude = ((bytes[cnt++] << 16) >>> 0) + ((bytes[cnt++] << 8) >>> 0) + bytes[cnt++];
      location.longitude = ((bytes[cnt++] << 16) >>> 0) + ((bytes[cnt++] << 8) >>> 0) + bytes[cnt++];
      if (location.latitude !== 0 && location.longitude !== 0) {
        location.latitude = (location.latitude / 16777215.0 * 180) - 90;
        location.longitude = (location.longitude / 16777215.0 * 360) - 180;
        location.latitude = Math.round(location.latitude * 100000) / 100000;
        location.longitude = Math.round(location.longitude * 100000) / 100000;
      }
      location.time = bytes[cnt++] | (bytes[cnt++] << 8) | (bytes[cnt++] << 16) | (bytes[cnt++] << 24);
      var d = new Date(location.time * 1000);
      location.time_decoded = d.toLocaleString();
      locations.push(location);
    }
    decoded.locations = JSON.stringify(locations);
  } else if (fPort === 30) {
    var vswr = [];
    for (i = 0; i < bytes.length; i++) {
      var value = (bytes[i]);
      vswr.push(value);
    }
    decoded.vswr = vswr;
  }

  return decoded;
}

```

`d_opencollar_rhino_tracker_legacy.js`, https://raw.githubusercontent.com/SmartParksOrg/smartparks-toolset/main/assets/Decoders/d_opencollar_rhino_tracker_legacy.js (commit bb98fb8). `d_opencollar_lion_tracker_legacy.js` is identical except that on port 12 it uses `battery_low = get_num(bytes[1], 0, 43750, 8, 1)` (lion) instead of `get_num(bytes[1], 0, 4096, 8, 1)` (rhino):

```javascript
//note some values need to be tuned to the hardware in here, make sure to do so
function get_num(x, min, max, precision, round) {

  var range = max - min;
  var new_range = (Math.pow(2, precision) - 1) / range;
  var back_x = x / new_range;

  if (back_x === 0) {
    back_x = min;
  } else if (back_x === (max - min)) {
    back_x = max;
  } else {
    back_x += min;
  }
  return Math.round(back_x * Math.pow(10, round)) / Math.pow(10, round);
}

// TTN decoder function, using the ChripStack decoder
function Decoder(bytes) {
  return Decode(port, bytes);
}

// ChirpStack decode function
function Decode(fPort, bytes) {

  var decoded = {};

  var resetCause_dict = {
    0: "POWERON",
    1: "EXTERNAL",
    2: "SOFTWARE",
    3: "WATCHDOG",
    4: "FIREWALL",
    5: "OTHER",
    6: "STANDBY"
  };

  // settings
  if (fPort === 3) {
    decoded.system_status_interval = (bytes[1] << 8) | bytes[0];
    decoded.system_functions = {};//bytes[2];
    decoded.system_functions.gps_periodic = ((bytes[2] >> 0) & 0x01) ? 1 : 0;
    decoded.system_functions.gps_triggered = ((bytes[2] >> 1) & 0x01) ? 1 : 0;
    decoded.system_functions.gps_hot_fix = ((bytes[2] >> 2) & 0x01) ? 1 : 0;
    decoded.system_functions.accelerometer_enabled = ((bytes[2] >> 3) & 0x01) ? 1 : 0;
    decoded.system_functions.light_enabled = ((bytes[2] >> 4) & 0x01) ? 1 : 0;
    decoded.system_functions.temperature_enabled = ((bytes[2] >> 5) & 0x01) ? 1 : 0;
    decoded.system_functions.humidity_enabled = ((bytes[2] >> 6) & 0x01) ? 1 : 0;
    decoded.system_functions.pressure_enabled = ((bytes[2] >> 7) & 0x01) ? 1 : 0;

    decoded.lorawan_datarate_adr = {};//bytes[3];
    decoded.lorawan_datarate_adr.datarate = bytes[3] & 0x0f;
    decoded.lorawan_datarate_adr.confirmed_uplink = ((bytes[3] >> 6) & 0x01) ? 1 : 0;
    decoded.lorawan_datarate_adr.adr = ((bytes[3] >> 7) & 0x01) ? 1 : 0;

    decoded.gps_periodic_interval = (bytes[5] << 8) | bytes[4];
    decoded.gps_triggered_interval = (bytes[7] << 8) | bytes[6];
    decoded.gps_triggered_threshold = bytes[8];
    decoded.gps_triggered_duration = bytes[9];
    decoded.gps_cold_fix_timeout = (bytes[11] << 8) | bytes[10];
    decoded.gps_hot_fix_timeout = (bytes[13] << 8) | bytes[12];
    decoded.gps_min_fix_time = bytes[14];
    decoded.gps_min_ehpe = bytes[15];
    decoded.gps_hot_fix_retry = bytes[16];
    decoded.gps_cold_fix_retry = bytes[17];
    decoded.gps_fail_retry = bytes[18];
    decoded.gps_settings = {};//bytes[19];
    decoded.gps_settings.d3_fix = ((bytes[19] >> 0) & 0x01) ? 1 : 0;
    decoded.gps_settings.fail_backoff = ((bytes[19] >> 1) & 0x01) ? 1 : 0;
    decoded.gps_settings.hot_fix = ((bytes[19] >> 2) & 0x01) ? 1 : 0;
    decoded.gps_settings.fully_resolved = ((bytes[19] >> 3) & 0x01) ? 1 : 0;
  } else if (fPort === 12) {
    decoded.resetCause = resetCause_dict[bytes[0]];
    // Lion tracker
    //decoded.battery_low = get_num(bytes[1], 0, 43750, 8, 1);
    //decoded.battery = get_num(bytes[2], 2048, 4096, 8, 1);
    // Rhino tracker
    decoded.battery_low = get_num(bytes[1], 0, 4096, 8, 1);
    decoded.battery = get_num(bytes[2], 2048, 4096, 8, 1);
    decoded.temperature = get_num(bytes[3], -20, 80, 8, 1);
    decoded.vbus = get_num(bytes[4], 0, 3.6, 8, 2);
    decoded.system_functions_errors = {};//bytes[5];
    decoded.system_functions_errors.gps_periodic_error = ((bytes[5] >> 0) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.gps_triggered_error = ((bytes[5] >> 1) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.gps_fix_error = ((bytes[5] >> 2) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.accelerometer_error = ((bytes[5] >> 3) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.light_error = ((bytes[5] >> 4) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.temperature_error = ((bytes[5] >> 5) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.humidity_error = ((bytes[5] >> 6) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.pressure_error = ((bytes[5] >> 7) & 0x01) ? 1 : 0;
    decoded.lat = ((bytes[6] << 16) >>> 0) + ((bytes[7] << 8) >>> 0) + bytes[8];
    decoded.lon = ((bytes[9] << 16) >>> 0) + ((bytes[10] << 8) >>> 0) + bytes[11];
    if (decoded.lat !== 0 && decoded.lon !== 0) {
      decoded.lat = (decoded.lat / 16777215.0 * 180) - 90;
      decoded.lon = (decoded.lon / 16777215.0 * 360) - 180;
      decoded.lat = Math.round(decoded.lat * 100000) / 100000;
      decoded.lon = Math.round(decoded.lon * 100000) / 100000;
      decoded.time_to_fix = bytes[12];
    }
    decoded.gps_resend = bytes[13];
  }
  //depreciated - used only for legacy devices
  else if (fPort === 2) {
    decoded.resetCause = resetCause_dict[bytes[0]];
    // Lion tracker
    decoded.battery_low = get_num(bytes[1], 0, 43750, 8, 1);
    decoded.battery = get_num(bytes[2], 2048, 4096, 8, 1);
    // Rhino tracker
    //decoded.battery_low = get_num(bytes[1], 400, 4000, 8, 1);
    //decoded.battery = get_num(bytes[2], 400, 4000, 8, 1);
    decoded.temperature = get_num(bytes[3], -20, 80, 8, 1);
    decoded.vbus = get_num(bytes[4], 0, 3.6, 8, 2);
    decoded.system_functions_errors = {};//bytes[5];
    decoded.system_functions_errors.gps_periodic_error = ((bytes[5] >> 0) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.gps_triggered_error = ((bytes[5] >> 1) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.gps_fix_error = ((bytes[5] >> 2) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.accelerometer_error = ((bytes[5] >> 3) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.light_error = ((bytes[5] >> 4) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.temperature_error = ((bytes[5] >> 5) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.humidity_error = ((bytes[5] >> 6) & 0x01) ? 1 : 0;
    decoded.system_functions_errors.pressure_error = ((bytes[5] >> 7) & 0x01) ? 1 : 0;
  } else if (fPort === 1) {
    decoded.lat = ((bytes[0] << 16) >>> 0) + ((bytes[1] << 8) >>> 0) + bytes[2];
    decoded.lon = ((bytes[3] << 16) >>> 0) + ((bytes[4] << 8) >>> 0) + bytes[5];
    console.log(decoded.lat)
    if (decoded.lat !== 0 && decoded.lon !== 0) {
      decoded.lat = (decoded.lat / 16777215.0 * 180) - 90;
      decoded.lon = (decoded.lon / 16777215.0 * 360) - 180;
      decoded.lat = Math.round(decoded.lat * 100000) / 100000;
      decoded.lon = Math.round(decoded.lon * 100000) / 100000;
    }
    decoded.alt = (bytes[7] << 8) | bytes[6];
    decoded.satellites = (bytes[8] >> 4);
    decoded.hdop = (bytes[8] & 0x0f);
    decoded.time_to_fix = bytes[9];
    decoded.epe = bytes[10];
    decoded.snr = bytes[11];
    decoded.lux = bytes[12];
    decoded.motion = bytes[13];
  }

  return decoded;
}

```

`d_opencollar_rhinoedge_v0_1.js`, https://raw.githubusercontent.com/SmartParksOrg/smartparks-toolset/main/assets/Decoders/d_opencollar_rhinoedge_v0_1.js (commit bb98fb8): the very first RhinoEdge prototype firmware (0.1) before the `msg_id, len` header existed; port 1 carried gps time, lat, lon, alt and the LR1110 NAV payload, port 4 a 20 byte status with a 24 bit packed position.

```javascript
// Decode decodes an array of bytes into an object.
//  - fPort contains the LoRaWAN fPort number
//  - bytes is an array of bytes, e.g. [225, 230, 255, 0]
//  - variables contains the device variables e.g. {"calibration": "3.5"} (both the key / value are of type string)
// The function must return an object, e.g. {"temperature": 22.5}

function decode_uint8_t(bytes, index) {
  var data = bytes[index.i];
  index.i += 1;
  return data;
}

function decode_32_bits(bytes, index) {
  var data = (bytes[index.i + 3] << 24) |
    (bytes[index.i + 2] << 16) |
    (bytes[index.i + 1] << 8) |
    bytes[index.i];

  index.i += 4;
  return data;
}

function decode_nav_payload(bytes, index, nav_len) {
  var nav_payload = "";
  var one_byte;
  var one_byte_str;

  // Skip first byte
  for (var i = 1; i < nav_len; i++) {
    one_byte = bytes[index.i + i];
    one_byte_str = one_byte.toString(16);
    if (one_byte_str.length == 1) {
      nav_payload += ("0" + one_byte_str);
    } else {
      nav_payload += one_byte_str;
    }
  }

  index.i += nav_len;
  return nav_payload;

}

function decode_uint8(byte, min, max) {
  var val;
  val = byte * (max - min) / 255 + min;

  return val;
}

// TTN decoder function, using the ChripStack decoder
function Decoder(bytes) {
  return Decode(port, bytes, null);
}

// ChirpStack decode function
function Decode(fPort, bytes, variables) {
  // Decode an uplink message from a buffer
  // (array) of bytes to an object of fields.
  var decoded = {};

  var index = {
    i: 0
  };

  if (fPort == 1) {

    gps_time = decode_32_bits(bytes, index);
    lat = decode_32_bits(bytes, index) / 10000000;
    lon = decode_32_bits(bytes, index) / 10000000;
    alt = decode_32_bits(bytes, index) / 1000;
    nav_len = decode_uint8_t(bytes, index);

    decoded = {
      gps_time: gps_time,
      latitude: lat,
      longitude: lon,
      altitude: alt,
      lr1110_gnss: decode_nav_payload(bytes, index, nav_len),
    };

  }

  if (fPort == 2) {

    var value = bytes[6] << 24 | bytes[5] << 16 | bytes[4] << 8 | bytes[3];
    var latitude = value / 10000000; // gps latitude,units: °
    value = bytes[10] << 24 | bytes[9] << 16 | bytes[8] << 8 | bytes[7];
    var longitude = value / 10000000; // gps longitude,units: °
    value = bytes[14] << 24 | bytes[13] << 16 | bytes[12] << 8 | bytes[11];
    var altitude = value / 1000;

    var success = bytes[0];
    var hot_retry = bytes[1];
    var cold_retry = bytes[2];

    decoded = {
      latitude: latitude,
      longitude: longitude,
      altitude: altitude,
      success: success,
      hot_retry: hot_retry,
      cold_retry: cold_retry,
    };
  }

  if (fPort == 4) {
    var reset = bytes[0];
    var err = bytes[1];
    var bat = (bytes[2] * 10) + 2500;
    var volt = bytes[3] * 100;
    var temp = decode_uint8(bytes[4], -100, 100);
    var uptime = bytes[5];
    var acc_x = decode_uint8(bytes[6], -100, 100);
    var acc_y = decode_uint8(bytes[7], -100, 100);
    var acc_z = decode_uint8(bytes[8], -100, 100);
    var version = bytes[9];
    var ver_hw_minor = version & 0x0F;
    var ver_hw_major = version >> 4;
    version = bytes[10];
    var ver_fw_minor = version & 0x0F;
    var ver_fw_major = version >> 4;
    var ver_hw_type = bytes[11];
    var lr_sat = bytes[12];
    var lr_fix = bytes[13];
    var value = bytes[16] << 16 | bytes[15] << 8 | bytes[14];
    var lat = (value - 900000) / 10000;
    value = bytes[19] << 16 | bytes[18] << 8 | bytes[17];
    var lon = (value - 1800000) / 10000;

    //Errors
    var err_lr = 0;
    if (err & 1) err_lr = 1;
    var err_ble = 0;
    if (err & 2) err_ble = 1;
    var err_ublox = 0;
    if (err & 4) err_ublox = 1;
    var err_acc = 0;
    if (err & 8) err_acc = 1;
    var err_bat = 0;
    if (err & 16) err_bat = 1;
    var err_time = 0;
    if (err & 32) err_time = 1;

    decoded = {
      reset: reset,
      bat: bat,
      volt: volt,
      temp: temp,
      uptime: uptime,
      acc_x: acc_x,
      acc_y: acc_y,
      acc_z: acc_z,
      lr_sat: lr_sat,
      lr_fix: lr_fix,
      //lat         : lat,
      //lon         : lon,
      err_lr: err_lr,
      err_ble: err_ble,
      err_ublox: err_ublox,
      err_acc: err_acc,
      err_bat: err_bat,
      err_time: err_time,
      ver_fw_major: ver_fw_major,
      ver_fw_minor: ver_fw_minor,
      ver_hw_major: ver_hw_major,
      ver_hw_minor: ver_hw_minor,
      ver_hw_type: ver_hw_type
    };

  }
  return decoded;
}


```

TTN device repository codec `vendor/smart-parks/opencollar-v26.js`, https://raw.githubusercontent.com/SmartParksOrg/lorawan-devices/master/vendor/smart-parks/opencollar-v26.js (commit 0b9139c69e760f930a668df90c2df99a0f102424, 2021-07-08), referenced by `opencollar-v26-codec.yaml`; `opencollar.yaml` declares hardware 2.3, firmware 2.6, profile `opencollar-eu868-profile` (LoRaWAN 1.0.2, RP001-1.0.2-RevB, ABP, RX2 DR3 at 868.525 MHz, 32 bit FCnt). Functionally the same as `d_opencollar_v3.js`:

```javascript
function get_num(x, min, max, precision, round) {

  var range = max - min;
  var new_range = (Math.pow(2, precision) - 1) / range;
  var back_x = x / new_range;

  if (back_x === 0) {
    back_x = min;
  }
  else if (back_x === (max - min)) {
    back_x = max;
  }
  else {
    back_x += min;
  }
  return Math.round(back_x * Math.pow(10, round)) / Math.pow(10, round);
}

function decodeUplink(input) {

  var data = {};
  var bytes = input.bytes;
  var port = input.fPort;
  var cnt = 0;
  var resetCause_dict = {
    0: "POWERON",
    1: "EXTERNAL",
    2: "SOFTWARE",
    3: "WATCHDOG",
    4: "FIREWALL",
    5: "OTHER",
    6: "STANDBY"
  };


  // settings
  if (port === 3) {
    data.system_status_interval = (bytes[1] << 8) | bytes[0];
    data.system_functions = {};//bytes[2];
    data.system_functions.gps_periodic = ((bytes[2] >> 0) & 0x01) ? 1 : 0;
    data.system_functions.gps_triggered = ((bytes[2] >> 1) & 0x01) ? 1 : 0;
    data.system_functions.gps_hot_fix = ((bytes[2] >> 2) & 0x01) ? 1 : 0;
    data.system_functions.accelerometer_enabled = ((bytes[2] >> 3) & 0x01) ? 1 : 0;
    data.system_functions.light_enabled = ((bytes[2] >> 4) & 0x01) ? 1 : 0;
    data.system_functions.temperature_enabled = ((bytes[2] >> 5) & 0x01) ? 1 : 0;
    data.system_functions.humidity_enabled = ((bytes[2] >> 6) & 0x01) ? 1 : 0;
    data.system_functions.charging_enabled = ((bytes[2] >> 7) & 0x01) ? 1 : 0;

    data.lorawan_datarate_adr = {};//bytes[3];
    data.lorawan_datarate_adr.datarate = bytes[3] & 0x0f;
    data.lorawan_datarate_adr.confirmed_uplink = ((bytes[3] >> 6) & 0x01) ? 1 : 0;
    data.lorawan_datarate_adr.adr = ((bytes[3] >> 7) & 0x01) ? 1 : 0;

    data.gps_periodic_interval = (bytes[5] << 8) | bytes[4];
    data.gps_triggered_interval = (bytes[7] << 8) | bytes[6];
    data.gps_triggered_threshold = bytes[8];
    data.gps_triggered_duration = bytes[9];
    data.gps_cold_fix_timeout = (bytes[11] << 8) | bytes[10];
    data.gps_hot_fix_timeout = (bytes[13] << 8) | bytes[12];
    data.gps_min_fix_time = bytes[14];
    data.gps_min_ehpe = bytes[15];
    data.gps_hot_fix_retry = bytes[16];
    data.gps_cold_fix_retry = bytes[17];
    data.gps_fail_retry = bytes[18];
    data.gps_settings = {};//bytes[19];
    data.gps_settings.d3_fix = ((bytes[19] >> 0) & 0x01) ? 1 : 0;
    data.gps_settings.fail_backoff = ((bytes[19] >> 1) & 0x01) ? 1 : 0;
    data.gps_settings.hot_fix = ((bytes[19] >> 2) & 0x01) ? 1 : 0;
    data.gps_settings.fully_resolved = ((bytes[19] >> 3) & 0x01) ? 1 : 0;
    data.system_voltage_interval = bytes[20];
    data.gps_charge_min = bytes[21]*10+2500;
    data.system_charge_min = bytes[22]*10+2500;
    data.system_charge_max = bytes[23]*10+2500;
    data.system_input_charge_min = (bytes[25] << 8) | bytes[24];
    data.pulse_threshold = bytes[26];
    data.pulse_on_timeout = bytes[27];
    data.pulse_min_interval = (bytes[29] << 8) | bytes[28];
    data.gps_accel_z_threshold = ((bytes[31] << 8) | bytes[30])-2000;
    data.fw_version = (bytes[33] << 8) | bytes[32];
  }
  else if (port === 12) {
    data.resetCause = resetCause_dict[bytes[0]&0x07];
    data.system_state_timeout = bytes[0]>>3;
    data.battery = bytes[1]*10+2500; // result in mV
    data.temperature = get_num(bytes[2], -20, 80, 8, 1);
    data.system_functions_errors = {};//bytes[5];
    data.system_functions_errors.gps_periodic_error = ((bytes[3] >> 0) & 0x01) ? 1 : 0;
    data.system_functions_errors.gps_triggered_error = ((bytes[3] >> 1) & 0x01) ? 1 : 0;
    data.system_functions_errors.gps_fix_error = ((bytes[3] >> 2) & 0x01) ? 1 : 0;
    data.system_functions_errors.accelerometer_error = ((bytes[3] >> 3) & 0x01) ? 1 : 0;
    data.system_functions_errors.light_error = ((bytes[3] >> 4) & 0x01) ? 1 : 0;
    data.system_functions_errors.charging_status = (bytes[3] >> 5) & 0x07;
    data.lat = ((bytes[4] << 16) >>> 0) + ((bytes[5] << 8) >>> 0) + bytes[6];
    data.lon = ((bytes[7] << 16) >>> 0) + ((bytes[8] << 8) >>> 0) + bytes[9];
    if(data.lat!==0 && data.lon!==0){
      data.lat = (data.lat / 16777215.0 * 180) - 90;
      data.lon = (data.lon / 16777215.0 * 360) - 180;
      data.lat = Math.round(data.lat*100000)/100000;
      data.lon = Math.round(data.lon*100000)/100000;
    }
    data.gps_resend = bytes[10];
    data.accelx = get_num(bytes[11], -2000, 2000, 8, 1);
    data.accely = get_num(bytes[12], -2000, 2000, 8, 1);
    data.accelz = get_num(bytes[13], -2000, 2000, 8, 1);
    data.battery_low = (bytes[15] << 8) | bytes[14];; // result in mV
    data.gps_on_time_total = (bytes[17] << 8) | bytes[16];
    data.gps_time = bytes[18] | (bytes[19] << 8) | (bytes[20] << 16) | (bytes[21] << 24);
    var d= new Date(data.gps_time*1000);
    data.gps_time_data = d.toLocaleString();
    data.pulse_counter = bytes[22];
    data.pulse_energy = (bytes[23]<<4) | (bytes[24] | (bytes[25] << 8)>>12);
    data.pulse_voltage = (bytes[24] | (bytes[25] << 8)) & 0x0fff;
    data.voltage_fence_v = data.pulse_voltage * 8;
    data.downlink_counter = (bytes[26] | (bytes[27] << 8));
  }
  else if (port === 1) {
    data.lat = ((bytes[cnt++] << 16) >>> 0) + ((bytes[cnt++] << 8) >>> 0) + bytes[cnt++];
    data.lon = ((bytes[cnt++] << 16) >>> 0) + ((bytes[cnt++] << 8) >>> 0) + bytes[cnt++];
    if(data.lat!==0 && data.lon!==0){
      data.lat = (data.lat / 16777215.0 * 180) - 90;
      data.lon = (data.lon / 16777215.0 * 360) - 180;
      data.lat = Math.round(data.lat*100000)/100000;
      data.lon = Math.round(data.lon*100000)/100000;
    }
    data.alt = bytes[cnt++] | (bytes[cnt++] << 8);
    data.satellites = (bytes[cnt] >> 4);
    data.hdop = (bytes[cnt++] & 0x0f);
    data.time_to_fix = bytes[cnt++];
    data.epe = bytes[cnt++];
    data.snr = bytes[cnt++];
    data.lux = bytes[cnt++];
    data.motion = bytes[cnt++];
    data.gps_time = bytes[cnt++] | (bytes[cnt++] << 8) | (bytes[cnt++] << 16) | (bytes[cnt++] << 24);
    var d= new Date(data.gps_time*1000);
    data.gps_time_data = d.toLocaleString();
  }
  else if (port === 11) {
    var locations=[];
    for(i = 0; i < 20; i++){
      var location={}
      location.lat = ((bytes[cnt++] << 16) >>> 0) + ((bytes[cnt++] << 8) >>> 0) + bytes[cnt++];
      location.lon = ((bytes[cnt++] << 16) >>> 0) + ((bytes[cnt++] << 8) >>> 0) + bytes[cnt++];
      location.gps_time = ((bytes[cnt++] << 16) >>> 0) + ((bytes[cnt++] << 8) >>> 0) + bytes[cnt++];
      location.gps_time = location.gps_time * 60 + 1600000000;
      var d= new Date(location.gps_time*1000);
      location.gps_time_data = d.toLocaleString();
      var fix_stats= bytes[cnt++];
      location.motion = fix_stats>>7;
      location.epe = ((fix_stats>>4)&0x07)*12;
      location.ttf = (fix_stats&0x0f)*5;
      if(location.lat!==0 && location.lon!==0){
        location.lat = (location.lat / 16777215.0 * 180) - 90;
        location.lon = (location.lon / 16777215.0 * 360) - 180;
        location.lat = Math.round(location.lat*100000)/100000;
        location.lon = Math.round(location.lon*100000)/100000;
        // push only valid locations
        locations.push(location);
      }
    }
    data.locations=JSON.stringify(locations);
  }
  else if (port === 30) {
    var vswr=[];
    for(i = 0; i < bytes.length; i++){
      var value=(bytes[i]);
      vswr.push(value);
    }
    data.vswr=vswr;
  }

  return data;
}

```

Legacy encoders (`smartparks-toolset/assets/Encoders`): `e_opencollar_tracker_v1.js` and `e_opencollar_rhino_tracker_legacy.js` build the 34 byte (or 20 byte) settings block for port 3, an 18 byte VSWR sweep request for port 30 and single byte commands for port 99 (0xAB reset, 0xDE LoRa rejoin, 0xAA send settings). `assets/Encoders/predefinedSettings/*.json` are example settings objects for that generation. There is no encoder for Edge devices in any public repository; the Edge downlink is the simple TLV described in section 4.

`e_opencollar_tracker_v1.js`, https://raw.githubusercontent.com/SmartParksOrg/smartparks-toolset/main/assets/Encoders/e_opencollar_tracker_v1.js (commit bb98fb8):

```javascript
// TTN encoder function, using the ChripStack encoder
function Encoder(object, port) {
  return Encode(port, object);
}

// ChirpStack encode function
function Encode(fPort, object) {
  var bytes = [];
  //settings
  if (fPort === 3) {
    bytes[0] = (object.system_status_interval) & 0xFF;
    bytes[1] = (object.system_status_interval) >> 8 & 0xFF;

    bytes[2] |= object.system_functions.accelerometer_enabled ? 1 << 3 : 0;
    bytes[2] |= object.system_functions.light_enabled ? 1 << 4 : 0;
    bytes[2] |= object.system_functions.temperature_enabled ? 1 << 5 : 0;
    bytes[2] |= object.system_functions.humidity_enabled ? 1 << 6 : 0;
    bytes[2] |= object.system_functions.charging_enabled ? 1 << 7 : 0;

    bytes[3] |= (object.lorawan_datarate_adr.datarate) & 0x0F;
    bytes[3] |= object.lorawan_datarate_adr.confirmed_uplink ? 1 << 6 : 0;
    bytes[3] |= object.lorawan_datarate_adr.adr ? 1 << 7 : 0;

    bytes[4] = (object.gps_periodic_interval) & 0xFF;
    bytes[5] = (object.gps_periodic_interval) >> 8 & 0xFF;

    bytes[6] = (object.gps_triggered_interval) & 0xFF;
    bytes[7] = (object.gps_triggered_interval) >> 8 & 0xFF;

    bytes[8] = (object.gps_triggered_threshold) & 0xFF;

    bytes[9] = (object.gps_triggered_duration) & 0xFF;

    bytes[10] = (object.gps_cold_fix_timeout) & 0xFF;
    bytes[11] = (object.gps_cold_fix_timeout) >> 8 & 0xFF;

    bytes[12] = (object.gps_hot_fix_timeout) & 0xFF;
    bytes[13] = (object.gps_hot_fix_timeout) >> 8 & 0xFF;

    bytes[14] = (object.gps_min_fix_time) & 0xFF;

    bytes[15] = (object.gps_min_ehpe) & 0xFF;

    bytes[16] = (object.gps_hot_fix_retry) & 0xFF;

    bytes[17] = (object.gps_cold_fix_retry) & 0xFF;

    bytes[18] = (object.gps_fail_retry) & 0xFF;

    bytes[19] = object.gps_settings.d3_fix ? 1 << 0 : 0;
    bytes[19] |= object.gps_settings.fail_backoff ? 1 << 1 : 0;
    bytes[19] |= object.gps_settings.hot_fix ? 1 << 2 : 0;
    bytes[19] |= object.gps_settings.fully_resolved ? 1 << 3 : 0;
    bytes[20] = (object.system_voltage_interval) & 0xFF;
    bytes[21] = ((object.gps_charge_min - 2500) / 10) & 0xFF;
    bytes[22] = ((object.system_charge_min - 2500) / 10) & 0xFF;
    bytes[23] = ((object.system_charge_max - 2500) / 10) & 0xFF;
    bytes[24] = (object.system_input_charge_min) & 0xFF;
    bytes[25] = (object.system_input_charge_min) >> 8 & 0xFF;
    bytes[26] = (object.pulse_threshold) & 0xFF;
    bytes[27] = (object.pulse_on_timeout) & 0xFF

    bytes[28] = (object.pulse_min_interval) & 0xFF;
    bytes[29] = (object.pulse_min_interval) >> 8 & 0xFF;

    bytes[30] = (object.gps_accel_z_threshold + 2000) & 0xFF;
    bytes[31] = (object.gps_accel_z_threshold + 2000) >> 8 & 0xFF;

    bytes[32] = 0;
    bytes[33] = 0;
  } else if (fPort === 30) {
    bytes[0] = (object.freq_start) & 0xFF;
    bytes[1] = (object.freq_start) >> 8 & 0xFF;
    bytes[2] = (object.freq_start) >> 16 & 0xFF;
    bytes[3] = (object.freq_start) >> 24 & 0xFF;

    bytes[4] = (object.freq_stop) & 0xFF;
    bytes[5] = (object.freq_stop) >> 8 & 0xFF;
    bytes[6] = (object.freq_stop) >> 16 & 0xFF;
    bytes[7] = (object.freq_stop) >> 24 & 0xFF;

    bytes[8] = (object.samples) & 0xFF;
    bytes[9] = (object.samples) >> 8 & 0xFF;
    bytes[10] = (object.samples) >> 16 & 0xFF;
    bytes[11] = (object.samples) >> 24 & 0xFF;

    bytes[12] = (object.power) & 0xFF;
    bytes[13] = (object.power) >> 8 & 0xFF;

    bytes[14] = (object.time) & 0xFF;
    bytes[15] = (object.time) >> 8 & 0xFF;

    bytes[16] = (object.type) & 0xFF;
    bytes[17] = (object.type) >> 8 & 0xFF;
  }
  //command
  else if (fPort === 99) {
    if (object.command.reset) {
      bytes[0] = 0xab;
    } else if (object.command.lora_rejoin) {
      bytes[0] = 0xde;
    } else if (object.command.send_settings) {
      bytes[0] = 0xaa;
    }
  }
  return bytes;
}

```

### 5.7 field-meta.json (units used by raw_logs_decoder for the decoder output)

Source: https://raw.githubusercontent.com/SmartParksOrg/raw_logs_decoder/main/field-meta.json (commit 9b10e02). Units as the tool labels them; note `sog` is labelled m/s although the decoder outputs km/h, and `cmdq_hrv` is labelled ms^2 although the decoder already takes the square root.

```json
{
  "latitude": { "group": "gnss", "unit": { "label": "Degrees", "symbol": "deg" }, "precision": 6 },
  "longitude": { "group": "gnss", "unit": { "label": "Degrees", "symbol": "deg" }, "precision": 6 },
  "altitude": { "group": "gnss", "unit": { "label": "Meters", "symbol": "m" }, "precision": 1 },
  "h_acc_est": { "group": "gnss", "unit": { "label": "Horizontal accuracy", "symbol": "m" }, "precision": 0, "isInteger": true },
  "pDOP": { "group": "gnss", "unit": { "label": "Dilution of precision", "symbol": null }, "precision": 1 },
  "fixType": { "group": "gnss", "isInteger": true },
  "SIV": { "group": "gnss", "unit": { "label": "Satellites in view", "symbol": "count" }, "isInteger": true },
  "cog": { "group": "gnss", "unit": { "label": "Course over ground", "symbol": "deg" }, "precision": 1 },
  "sog": { "group": "gnss", "unit": { "label": "Speed over ground", "symbol": "m/s" }, "precision": 1 },
  "success": { "group": "gnss", "isInteger": true },
  "hot_retry": { "group": "gnss", "unit": { "label": "Retry count", "symbol": "count" }, "isInteger": true },
  "cold_retry": { "group": "gnss", "unit": { "label": "Retry count", "symbol": "count" }, "isInteger": true },
  "ttf": { "group": "gnss", "unit": { "label": "Time to fix", "symbol": "s" }, "isInteger": true },
  "active_t": { "group": "gnss", "unit": { "label": "Active time", "symbol": "s" }, "isInteger": true },
  "nav_payload": { "group": "gnss" },
  "fix_timestamp": { "group": "gnss", "unit": { "label": "Unix time", "symbol": "s" }, "isInteger": true },
  "fix_time": { "group": "gnss", "unit": { "label": "Unix time", "symbol": "s" }, "isInteger": true },

  "reset": { "group": "status", "isInteger": true },
  "bat": { "group": "status", "unit": { "label": "Millivolt", "symbol": "mV" }, "precision": 0, "isInteger": true },
  "chg": { "group": "status", "isInteger": true },
  "temp": { "group": "status", "unit": { "label": "Celsius", "symbol": "C" }, "precision": 1 },
  "uptime": { "group": "status", "unit": { "label": "Uptime", "symbol": "days" }, "isInteger": true },
  "locked": { "group": "status", "isInteger": true },
  "msg": { "group": "status", "isInteger": true },
  "acc_x": { "group": "status", "unit": { "label": "Acceleration", "symbol": "m/s^2" }, "precision": 2 },
  "acc_y": { "group": "status", "unit": { "label": "Acceleration", "symbol": "m/s^2" }, "precision": 2 },
  "acc_z": { "group": "status", "unit": { "label": "Acceleration", "symbol": "m/s^2" }, "precision": 2 },
  "lr_sat": { "group": "status", "unit": { "label": "Satellites", "symbol": "count" }, "isInteger": true },
  "err_lr": { "group": "status", "isInteger": true },
  "err_lr_join": { "group": "status", "isInteger": true },
  "err_ble": { "group": "status", "isInteger": true },
  "err_ublox": { "group": "status", "isInteger": true },
  "err_acc": { "group": "status", "isInteger": true },
  "err_bat": { "group": "status", "isInteger": true },
  "err_ublox_fix": { "group": "status", "isInteger": true },
  "err_flash": { "group": "status", "isInteger": true },
  "ver_fw_major": { "group": "status", "isInteger": true },
  "ver_fw_minor": { "group": "status", "isInteger": true },
  "ver_hw_major": { "group": "status", "isInteger": true },
  "ver_hw_minor": { "group": "status", "isInteger": true },
  "ver_hw_type": { "group": "status", "isInteger": true },
  "ver_fw_type": { "group": "status", "isInteger": true },
  "sat_support": { "group": "status", "isInteger": true },
  "sat_try": { "group": "status", "isInteger": true },
  "rf_scan": { "group": "status", "isInteger": true },
  "fence": { "group": "status", "isInteger": true },
  "percentage": { "group": "flash_status", "unit": { "label": "Percentage", "symbol": "%" }, "precision": 0, "isInteger": true },
  "n_msg": { "group": "flash_status", "unit": { "label": "Buffered messages", "symbol": "count" }, "isInteger": true },

  "activity": { "group": "external_switch", "description": "External switch state", "isInteger": true },
  "duration_ms": { "group": "external_switch", "unit": { "label": "Duration", "symbol": "ms" }, "isInteger": true },
  "impulse_count": { "group": "external_switch", "unit": { "label": "Impulse count", "symbol": "count" }, "isInteger": true },
  "num_of_active_detections": { "group": "external_switch", "unit": { "label": "Active detections", "symbol": "count" }, "isInteger": true },
  "timestamp": { "group": "timestamp_message", "unit": { "label": "Unix time", "symbol": "s" }, "isInteger": true },

  "cmdq_timestamp": { "group": "cmdq", "isInteger": true },
  "cmdq_rr_median": {
    "group": "cmdq",
    "unit": { "label": "R-R interval (×10 ms)", "symbol": "10ms" },
    "isInteger": true,
    "description": "Median time between cardiac R peaks in tens of milliseconds"
  },
  "cmdq_rr_median_modesum": { "group": "cmdq", "isInteger": true },
  "cmdq_activity_average": { "group": "cmdq", "isInteger": true },
  "cmdq_activity_max": { "group": "cmdq", "isInteger": true },
  "cmdq_active_min_in_last_hour": { "group": "cmdq", "isInteger": true },
  "cmdq_temp": { "group": "cmdq", "unit": { "label": "Celsius", "symbol": "C" }, "precision": 1 },
  "cmdq_raw_temp": {
    "group": "cmdq",
    "isInteger": true,
    "description": "Raw sensor value used to derive cmdq_temp"
  },
  "cmdq_h_impedance": { "group": "cmdq", "isInteger": true },
  "cmdq_hrv": {
    "group": "cmdq",
    "precision": 2,
    "unit": { "label": "RMSSD basis (ms²)", "symbol": "ms^2" },
    "description": "Mean of squared successive R-R differences; take square root to obtain RMSSD in ms"
  },
  "cmdq_hrv_raw": { "group": "cmdq", "isInteger": true },
  "cmdq_success": { "group": "cmdq", "isInteger": true },

  "N": { "group": "fence", "unit": { "label": "Pulse count", "symbol": "count" }, "isInteger": true },
  "N_sat": { "group": "counts", "unit": { "label": "Count", "symbol": "count" }, "isInteger": true },
  "N_reported": { "group": "counts", "unit": { "label": "Count", "symbol": "count" }, "isInteger": true },
  "N_wifi_res": { "group": "counts", "unit": { "label": "Count", "symbol": "count" }, "isInteger": true },
  "N_BT_res": { "group": "counts", "unit": { "label": "Count", "symbol": "count" }, "isInteger": true },
  "t": { "group": "scan", "unit": { "label": "Unix time", "symbol": "s" }, "isInteger": true },

  "lr_sats_json": { "group": "jsons" },
  "ublox_sats_json": { "group": "jsons" },
  "wifi_scan_json": { "group": "jsons" },
  "bt_scan_json": { "group": "jsons" },
  "last_scan_json": { "group": "jsons" },
  "rf_scan_json": { "group": "jsons" },
  "fence_json": { "group": "jsons" },
  "opensky_json": { "group": "jsons" },
  "device_msg_hex": { "group": "jsons" },
  "memfault_msg_hex": { "group": "jsons" },

  "device_len": { "group": "meta", "unit": { "label": "Bytes", "symbol": "B" }, "isInteger": true },
  "device_msg_len": { "group": "meta", "unit": { "label": "Bytes", "symbol": "B" }, "isInteger": true },
  "device_seq": { "group": "meta", "isInteger": true },
  "device_retry": { "group": "meta", "isInteger": true },
  "memfault_len": { "group": "meta", "unit": { "label": "Bytes", "symbol": "B" }, "isInteger": true },
  "len": { "group": "device_message", "unit": { "label": "Bytes", "symbol": "B" }, "isInteger": true },
  "msg_len": { "group": "device_message", "unit": { "label": "Bytes", "symbol": "B" }, "isInteger": true },
  "seq": { "group": "device_message", "isInteger": true },
  "retry": { "group": "device_message", "isInteger": true },

  "voltage": { "group": "fence", "unit": { "label": "Voltage", "symbol": "V" }, "precision": 0, "isInteger": true },
  "energy": { "group": "fence", "unit": { "label": "Energy", "symbol": "arb" }, "isInteger": true },

  "version": { "group": "rf_scan", "isInteger": true },
  "should_alert": { "group": "rf_scan", "isInteger": true },
  "start": { "group": "rf_scan", "unit": { "label": "Frequency", "symbol": "MHz" }, "precision": 1 },
  "stop": { "group": "rf_scan", "unit": { "label": "Frequency", "symbol": "MHz" }, "precision": 1 },
  "peak_count": { "group": "rf_scan", "unit": { "label": "Count", "symbol": "count" }, "isInteger": true },
  "average_rssi": { "group": "opensky", "unit": { "label": "Signal level", "symbol": "dBm" }, "precision": 1 },
  "max_rssi": { "group": "opensky", "unit": { "label": "Signal level", "symbol": "dBm" }, "precision": 1 }
}

```

## 6. Example payloads

Every example found, with its source. Hex is the FRMPayload after LoRaWAN decryption unless labelled otherwise.

### 6.1 Uplink examples with decoded output (Smart Parks wiki, https://wiki.smartparks.org/devices/opencollar/lorawan_messages, fetched 2026-09-03; device RangerEdge hw 1.4, fw 4.4, Utrecht area, 2023-11-30)

| FPort | Hex | Base64 | Expected decoded output |
| --- | --- | --- | --- |
| 1 | `f1020008` | `8QIACA==` | `{"nav_payload": "08"}` |
| 2 | `f21e0100001000e6a40d1f97100e03a0cb000003082f00048c61686500000000` | `8h4BAAAQAOakDR+XEA4DoMsAAAMILwAEjGFoZQAAAAA=` | `{"latitude": 52.0987878, "longitude": 5.1253399, "altitude": 52.128, "success": 1, "hot_retry": 0, "cold_retry": 0, "ttf": 16, "fixType": 3, "SIV": 8, "h_acc_est": 47, "pDOP": 4, "fix_time": 1701339532, "active_t": 0}` (v6.5+ decoders name the time `fix_timestamp`) |
| 4 | `f40e0400a00095007f7f721444550000` | `9A4EAKAAlQB/f3IURFUAAA==` | `{"reset": 4, "bat": 4100, "chg": 0, "temp": 16.862745098039213, "uptime": 0, "locked": 0, "msg": 0, "acc_x": -0.39215686274509665, "acc_y": -0.39215686274509665, "acc_z": -10.588235294117652, "lr_sat": 0, "err_lr": 0, "err_lr_join": 0, "err_ble": 0, "err_ublox": 0, "err_acc": 0, "err_bat": 0, "err_ublox_fix": 0, "err_flash": 0, "ver_fw_major": 4, "ver_fw_minor": 4, "ver_hw_major": 1, "ver_hw_minor": 4, "ver_hw_type": 5, "ver_fw_type": 5, "sat_support": 0, "sat_try": 0, "rf_scan": 0, "fence": 0}` |
| 5 | `f50100` | `9QEA` | `{"N_sat": 0, "N_reported": 0}` |
| 6 | `f71c0668ff7b390141626865001daa3201416268656032b1290141626865` | `9xwGaP97OQFBYmhlAB2qMgFBYmhlYDKxKQFBYmh` (wiki value, truncated) | `{"1": {"rssi": -71, "count": 1, "mac": "7b:ff:68", "t": 1701339713}, "2": {"rssi": -78, "count": 1, "mac": "aa:1d:0", "t": 1701339713}, "3": {"rssi": -87, "count": 1, "mac": "b1:32:60", "t": 1701339713}, "N_wifi_res": 6}` |
| 7 | `f92e1481ed0c4401af646865b255094301af6468658e6a093e01af646865647a203c01ae646865945cba3801af646865` | `+S4Uge0MRAGvZGhlslUJQwGvZGhljmoJPgGvZGhlZHogPAGuZGhllFy6OAGvZGhl` | `{"1": {"rssi": -60, "count": 1, "mac": "c:ed:81", "t": 1701340335}, "2": {"rssi": -61, "count": 1, "mac": "9:55:b2", "t": 1701340335}, "3": {"rssi": -66, "count": 1, "mac": "9:6a:8e", "t": 1701340335}, "4": {"rssi": -68, "count": 1, "mac": "20:7a:64", "t": 1701340334}, "5": {"rssi": -72, "count": 1, "mac": "ba:5c:94", "t": 1701340335}, "N_BT_res": 20}` |
| 8 (legacy) | `fb0e0100be23602200ff0861ca5d00ff` | `+w4BAL4jYCIA/whhyl0A/w==` | `{"version": 1, "should_alert": 0, "band_8": {"start": 915, "stop": 880, "peak_count": 0, "max_rssi": -255}, "band_wifi_bt": {"start": 2484, "stop": 2401, "peak_count": 0, "max_rssi": -255}}` |
| 9 | `f63d0a091206660001081c053c000107252c3f00015113040201024d1607c300024c2331ad00024b22373700024a14071c0002431410320102421243450102` | `9j0KCRIGZgABCBwFPAABByUsPwABURMEAgECTRYHwwACTCMxrQACSyI3NwACShQHHAACQxQQMgECQhJDRQEC` | 10 satellites, e.g. `"1": {"id": 9, "cn0": 18, "ele": 6, "azi": 102, "con": "GPS"}`, `"4": {"id": 81, "cn0": 19, "ele": 4, "azi": 258, "con": "GLONASS"}`, `"N_sat": 10, "N_reported": 10` |
| 10 | `f8370668ff7b390141626865001daa3201416268656032b1290141626865b215a2310141626865fa92bf2b0141626865f492bf2d0141626865` | `+DcGaP97OQFBYmhlAB2qMgFBYmhlYDKxKQFBYmhlshWiMQFBYmhl+pK/KwFBYmhl9JK/LQFBYmhl` | six records, `"1": {"rssi": -71, "count": 1, "mac": "7b:ff:68", "t": 1701339713}` ... `"6": {"rssi": -83, "count": 1, "mac": "bf:92:f4", "t": 1701339713}, "N_wifi_res": 6` |
| 11 | `fa55af6468651481ed0c44b25509438e6a093e647a203c945cba38fc56d0381bfcc6348c12193385da3f3238395431e43bdf317eabc631d0749d2b566f762b70de5d2b8413d02a2582b52aa5fa6a28dae11627f14bff27` | `+lWvZGhlFIHtDESyVQlDjmoJPmR6IDyUXLo4/FbQOBv8xjSMEhkzhdo/Mjg5VDHkO98xfqvGMdB0nStWb3YrcN5dK4QT0ColgrUqpfpqKNrhFifxS/8n` | 20 records `"1": {"rssi": -60, "mac": "c:ed:81"}` ... `"20": {"rssi": -89, "mac": "ff:4b:f1"}, "N_BT_res": 20, "t": 1701340335` |
| 12 | `9206000000000000` | `kgYAAAAAAAA=` | `{"success": 0, "N": 0, "voltage": 0, "energy": 0}` |
| 13 | `930ef9636865aba50d1f8e090e031500` | `kw75Y2hlq6UNH44JDgMVAA==` | `{"fix_timestamp": 1701340153, "latitude": 52.0988075, "longitude": 5.1251598, "h_acc_est": 21}` |
| 14 | `94050010000000` | `lAUAEAAAAA==` | `{"percentage": 0, "n_msg": 16}` |
| 15 (13 byte records, fw 6.1 to 6.8) | `fc1c56f5b965000000000006480ff00bf6b965000000000006480ff0` | `/BxW9bllAAAAAAAGSA/wC/a5ZQAAAAAABkgP8A==` | two records: `"0": {"cmdq_timestamp": 1706685782, "cmdq_rr_median": 0, "cmdq_rr_median_modesum": 0, "cmdq_activity_average": 0, "cmdq_activity_max": 0, "cmdq_active_min_in_last_hour": 0, "cmdq_raw_temp": 1608, "cmdq_temp": 21.7884, "cmdq_h_impedance": 4080}`, `"1": {... "cmdq_timestamp": 1706685963 ...}` |
| 28 | `900d0a736d6172747061726b730101` | `kA0Kc21hcnRwYXJrcwEB` | `{"len": 13, "msg_len": 10, "msg": [115,109,97,114,116,112,97,114,107,115] ("smartparks"), "seq": 1, "retry": 1}` |
| 29 | `0D930E3C636865FCA10D1F7D160E030C00436368650D930EF9636865ABA50D1F8E090E031500006468650D930EBA64686536A30D1F0D140E031300C26468650D930E7865686561A50D1FE0140E031600816568650D930E37666865C3A40D1FF5120E0311003F6668650D930EF466686599A30D1F81120E031100FC6668650D930EB1676865DFA30D1FCC120E030E00B76768650D930E6D686865DFA40D1F9B110E031000746868650D930E2A69686576A60D1FA20F0E030E00316968650D930EE6696865CEA40D1F8B100E031000ED696865` | `DZMOPGNoZfyhDR99Fg4DDABDY2hlDZMO+WNoZaulDR+OCQ4DFQAAZGhlDZMOumRoZTajDR8NFA4DEwDCZGhlDZMOeGVoZWGlDR/gFA4DFgCBZWhlDZMON2ZoZcOkDR/1Eg4DEQA/ZmhlDZMO9GZoZZmjDR+BEg4DEQD8ZmhlDZMOsWdoZd+jDR/MEg4DDgC3Z2hlDZMObWhoZd+kDR+bEQ4DEAB0aGhlDZMOKmloZXamDR+iDw4DDgAxaWhlDZMO5mloZc6kDR+LEA4DEADtaWhl` | 10 records of port 13: `"1": {"data": {"fix_timestamp": 1701339964, "latitude": 52.0987132, "longitude": 5.1254909, "h_acc_est": 12}, "fPort": 13, "timestamp": 1701339971}` ... `"10": {"data": {"fix_timestamp": 1701341670, "latitude": 52.0987854, "longitude": 5.1253387, "h_acc_est": 16}, "fPort": 13, "timestamp": 1701341677}` (TTN decoder names the port key `port`) |

### 6.2 Uplink examples from firmware documentation

* CMDQ, one detection (`app/src/bt_module/bt_cmdq/README.md`, BLE framing with port byte): `0F FC 0D 58F3CD65000000000006BC0FF0`; payload `58F3CD65` timestamp 1707995992, important data `000000000006BC0FF0` gives rr_median 0, rr_median_modesum 0, activity_average 0, activity_max 0, active_min_in_last_hour 0, raw_temp 1724, h_impedance 4080. Two detections: `0F FC 1a 58F3CD65000000000006BC0FF070F4CD65000000000006BC0FF0`. Empty: `0F FC 00`.
* Flash status format (`app/src/flash/README.md`): `94 05 <pct> <n_msg u32>`.
* GNSS NAV payloads used with the LoRa Cloud solver (`scripts/update_almanac/cmd_nav_locator.py`): `010106D9430816a202a82aeb61df9b2d5031d5367d072aa05209c0c7ae7651d5b8e7203c09a3caba8ea4bf8c8c16558652c17787636a776c44f9294cd5a54356ff4900` and `01763C430816622AA915764B45040B541B0C08CE182A0D0AB042849AFAD0B862C501721516322C8908` (these are NAV messages as posted to `https://mgs.loracloud.com/api/v3/solve/gnss`, i.e. the bytes after the port 1 header).

### 6.3 Downlink examples (wiki settings-and-commands page unless stated)

Settings (FPort 3):

| Purpose | Hex | Base64 |
| --- | --- | --- |
| `lr_adr` DR0 (EU868 SF12) | `0E 01 00` | `DgEA` |
| `lr_adr` DR1 | `0E 01 01` | `DgEB` |
| `lr_adr` DR2 | `0E 01 02` | `DgEC` |
| `lr_adr` DR3 | `0E 01 03` | `DgED` |
| `lr_adr` DR4 | `0E 01 04` | `DgEE` |
| `lr_adr` DR5 (EU868 SF7) | `0E 01 05` | `DgEF` |
| status interval 1 min | `03 04 3C 00 00 00` | `AwQ8AAAA` |
| status interval 15 min | `03 04 84 03 00 00` | `AwSEAwAA` |
| status interval 30 min | `03 04 08 07 00 00` | `AwQIBwAA` |
| status interval 60 min | `03 04 10 0E 00 00` | `AwQQDgAA` |
| u-blox interval 1 = 15 min | `02 04 84 03 00 00` | `AgSEAwAA` |
| u-blox interval 1 = 60 min | `02 04 10 0E 00 00` | `AgQQDgAA` |
| u-blox interval 1 = 2 h | `02 04 20 1C 00 00` (wiki hex has a typo `10 1c`; base64 is correct) | `AgQgHAAA` |
| u-blox interval 1 = 12 h | `02 04 C0 A8 00 00` | `AgTAqAAA` |
| u-blox interval 2 = 15 min | `26 04 84 03 00 00` | `JgSEAwAA` |
| u-blox interval 1 off | `02 04 00 00 00 00` | `AgQAAAAA` |
| cold fix timeout 200 s | `16 02 C8 00` | `FgLIAA==` |
| cold fix retries 20 | `14 01 14` | `FAEU` |
| hot fix timeout 45 s | `17 02 2D 00` | `FwItAA==` |
| hot fix retries 4 | `15 01 04` | `FQEE` |
| backoff factor 1.4 (wiki says 1.5) | `25 01 0E` | `JQEO` |
| interval 1 start 11 h UTC | `27 01 0B` | `JwEL` |
| enable two u-blox intervals | `29 01 01` | `KQEB` |
| horizontal accuracy 50 m | `13 04 32 00 00 00` | `EwQyAAAA` |
| horizontal accuracy 25 m | `13 04 19 00 00 00` | `EwQZAAAA` |
| `lr_send_flag` default (old) 0xFC00066F | `0C 04 6F 06 00 FC` | |
| `lr_send_flag` without port 10 (0xFC00046F) | `0C 04 6F 04 00 FC` | |
| `lr_send_flag` without port 11 (0xFC00026F) | `0C 04 6F 02 00 FC` | |
| `flash_store_flag` default (old) 0x0400066F | `0D 04 6F 06 00 04` | |
| ADR profile network controlled (KPN/Actility) | `57 01 00` | `VwEA` |
| enable fence (firmware fence README) | `3F 01 01` | |
| debug u-blox satellite data on / off (GPS README) | `0A 01 01` / `0A 01 00` | |
| VHF frequency 150000 kHz (wiki features) | `6A 04 F0 49 02 00` | |
| S-band send interval 300 s over BLE (wiki features, decimal with port) | `3 32 4 44 1 0 0` | |
| LP0 send flag for ports 3, 8, 21 (lp0 README) | value 1048708 = `88 04 84 00 10 00` | |

Commands (FPort 32):

| Purpose | Hex | Base64 |
| --- | --- | --- |
| reset device | `A1 00` | `oQA=` |
| reset u-blox | `A6 00` | `pgA=` |
| reset LR1110 | `B9 00` | `uQA=` |
| u-blox fix now | `B8 00` | `uAA=` |
| last known position (reply 0xFE on FPort 31) | `A5 00` | `pQA=` |
| all flash records port 2 / 4 / 13 / 15 | `BB 01 02` / `BB 01 04` / `BB 01 0D` / `BB 01 0F` | `uwEC` / `uwEE` / `uwEN` / `uwEP` |
| last 100 port 2 records | `BC 0C 02 00 00 00 00 00 00 00 64 00 00 00` | `vAwCAAAAAAAAAGQAAAA=` |
| last 1000 port 13 records | `BC 0C 0D 00 00 00 00 00 00 00 E8 03 00 00` (wiki hex shows `03 E8`, big-endian typo; base64 `vAwNAAAAAAAAAAPoAAA=` also encodes `03 E8`, so as published it requests 59395 records; correct little-endian is `E8 03`) | |
| last 1500 port 13 records | wiki `BC 0C 0D 00 00 00 00 00 00 00 05 DC 00 00` (same byte order caveat; correct `DC 05`) | `vAwNAAAAAAAAAAXcAAA=` |
| last 2000 port 13 records | wiki `BC 0C 0D 00 00 00 00 00 00 00 07 D0 00 00` (correct `D0 07`) | `vAwNAAAAAAAAAAfQAAA=` |
| last 100 / 1000 port 11 records | `BC 0C 0B 00 00 00 00 00 00 00 64 00 00 00` / wiki `... 03 E8 00 00` | `vAwLAAAAAAAAAGQAAAA=` / `vAwLAAAAAAAAAAPoAAA=` |
| last 100 / 1000 port 15 records | `BC 0C 0F 00 00 00 00 00 00 00 64 00 00 00` / wiki `... 03 E8 00 00` | `vAwPAAAAAAAAAGQAAAA=` / `vAwPAAAAAAAAAAPoAAA=` |
| clear flash | `BA 00` | `ugA=` |
| all settings | `A7 00` | `pwA=` |
| single setting, e.g. `lr_gps_interval` | `A8 01 01` | `qAEB` |
| single setting `ublox_send_interval` | `A8 01 02` | |
| hibernation (wiki features) | `C3 00` | `wwA=` |
| S-band single send (wiki, BLE decimal) | `32 189 0` | |
| CollarEdge drop-off (wiki) | `CD 00` | |

RockBLOCK mobile terminated (wiki satellite page, port byte in front): `03 02 04 08 07 00 00` (GPS interval 1800 s), `03 04 04 10 0E 00 00` (satellite interval 3600 s).

### 6.4 Raw log files and LoRaWAN capture formats

* BLE web app raw logs (`raw_logs-<type>-<device>_<time>.txt`): one base64 line per BLE notification frame, `[port][msg_id][len][data]`; flash downloads produce `[0x1D][records]` lines. `raw_logs_decoder` splits lines, decodes base64, uses byte 0 as port and passes the remainder to `Decoder`.
* LP0 replay/platform tools consume Semtech UDP JSONL: `{"gatewayEui": "0102030405060708", "rxpk": {"time": ..., "data": "<base64 PHYPayload>"}}`; the PHYPayload must be decrypted with ABP session keys before the application decoder runs (test vectors in `make_test_log.py` use DevAddr 26011BDA, NwkSKey 000102030405060708090A0B0C0D0E0F, AppSKey F0E0D0C0B0A090807060504030201000, payload 0102030405060708 on FPort 1).

## 7. Firmware and decoder version conventions

### 7.1 Firmware

* Semantic versions `MAJOR.MINOR.PATCH`, CHANGELOG in Keep a Changelog format. Public history: 2.3.0 (2022-05-17) to 2.15.0 (2023-02-15), 4.0.0 (2023-03-31, NCS 2.2 port) to 4.4.3 (2023-11-15), 5.0.0/5.0.1 (2024-03, a non functional migration image required between 4.x and 6.x to update internal drivers), 6.1.0 (2024-02-07) to 6.16.3 (2025-09-23), 7.1.0 (2026-02-10), 7.2.0 (2026-03-05), 7.3.0 (2026-04-09). The wiki firmware page (fetched 2026-09-03) still lists 6.15.1 as latest stable and 7.2.0 as beta.
* Release artifacts are built per hardware board and revision group with `east release`; file names look like `rhinoedge_tracker-app-rhinoedge_nrf52840-hv1.3.0-v2.3.0.hex` (`<tracker type>-<image>-<board>-hv<hw version>-v<fw version>[-dbg|-prov|-log]`). Four build types: production, debug (`-dbg`), log (`-log`, RTT logging), provisioning (`-prov`). Since 6.8.x the release also renames `settings.json` and `ttn_decoder.js` to include the release version (CHANGELOG 6.8.0/6.8.1), which is where `ttn_decoder-v6.15.1.js` style names come from.
* On the air the firmware version is only visible as major.minor nibbles in status byte 12 (patch not transmitted; minor wraps at 16). Hardware version is in byte 11 as major.minor nibbles; the revision groups the firmware distinguishes are collaredge 1.0.0/1.1.0/1.4.0/1.5.0, freeedge 1.0.0/1.3.0/1.6.0, rangeredge 1.4.0/1.6.0/1.7.0/1.8.0 (1.8.0 covers boards 1.8.0 to 1.13.0), rhinoedge 1.4.0, rhinopuck 1.3.0, rhinopuck35 1.2.0.
* Settings are defined once in `scripts/settings/settings.json` and turned into C headers by `scripts/settings/py2h.py`; the same JSON is what the BLE app and connect-web read (`settings_template_<fw>.json`, `settings-v<fw>.json`). The `ports`, `messages`, `commands`, `values` and `settings` clusters of that file are the protocol definition.

### 7.2 Hardware and firmware (tracker) type codes (status byte 13)

Hardware type (low nibble): 1 rhinoedge_nrf52840, 2 elephantedge_nrf52840 (obsolete), 3 wisentedge_nrf52840 (obsolete), 4 cattracker_nrf52840 (obsolete), 5 rangeredge_nrf52840, 6 rhinopuck_nrf52840 (Puck50), 7 rhinopuck35_nrf52840, 8 collaredge_nrf52840, 9 freeedge_nrf52840.

Firmware / tracker type (high nibble, setting `tracker_type` 0x00, 0 = hardware default): 0 default, 1 rhinoedge, 2 elephantedge, 3 wisentedge, 4 cattracker, 5 rangeredge, 6 rhinopuck, 7 scanneredge, 8 collaredge, 9 freeedge, 10 fenceedge, 11 horseedge, 12 collaredgepico, 13 collaredgenano, 14 baboonedge, 15 pangolinedge. Valid combinations: rhinoedge hardware may run 1, 11, 14, 15, 12, 13; rangeredge hardware 5, 10, 7, 2, 3; rhinopuck and rhinopuck35 6; collaredge 8; freeedge 9.

### 7.3 Decoders

* The canonical decoder is `scripts/ttn_decoder.js` in the firmware repository ("Effort should be made that decoder on TTN is up to date with the one in scripts folder"). A copy is released with each firmware as `ttn_decoder-v<fw version>.js`. Copies in other repositories carry the firmware version they were taken from, not their own version: `raw_logs_decoder` (v6.11.2, v6.14.0, v6.15.1, v7.2.0), lp0 tools (v6.15.3), toolset (`CSv4_Decoder_OpenCollar_Edge_v4.4.3/6.1.2/6.5.0.js`, ChirpStack v4 flavour). Files with different version names can be byte identical (6.11.2 = 6.14.0, 6.15.1 = 6.15.3, 7.2.0 = firmware 7.3.0 script).
* `raw_logs_decoder` has its own app version (`version.txt`, v1.43 at commit 9b10e02) bumped by a GitHub workflow on every push; it is unrelated to decoder versions.
* Decoder changes tied to firmware releases (from CHANGELOG): 4.4.0 flash status and short u-blox message; 6.1.0 CMDQ (13 byte records); 6.2.0 CMDQ `cmdq_success`, `gps resend` port 16; 6.9.0 CMDQ HRV (15 byte records), `cmd_send_timestamp`/port 18; 6.13.0 unsigned `>>> 0` fix and `fix_timestamp` fix, external switch ports 19/20; 7.1.0 RF scan and open sky removed; 7.2.0 (decoder) air quality port 21 and `version` string.

## 8. What could not be found, and whom to ask

1. IRNAS GitBook "OpenCollar" (`https://github.com/IRNAS/gitbook-opencollar`, `https://app.gitbook.com/@irnas/s/opencollar/technology/firmware`) is private (404/401). The firmware README calls it "the main documentation". Ask Smart Parks or IRNAS for read access or an export; it most likely contains the formal message and settings guidelines the wiki paraphrases.
2. The upstream firmware repository `IRNAS/smartparks-opencollar-edge-fw` (private) holds the release assets (`ttn_decoder-v*.js`, `settings-v*.json`, DFU zips) and GitHub issue #389 that defines the CMDQ "important data" bytes. The public mirror has no releases and no tags. Ask for the release asset bundle per firmware version, or at least the decoder and settings.json for 6.1.x through 6.16.x.
3. `smartparks-connect-app` (mobile app) and `smartparks-provisioning-software` are private; they are the reference for BLE framing and for downlink composition in the field.
4. No Node-RED flows or EarthRanger integration flows are public except `scripts/ublox_lr1110_comparison.flow` (InfluxDB comparison of LR1110 and u-blox data) and the empty `node-red-contrib-earthranger`/`node-red-contrib-chirpstack` packages. Ask for the production ChirpStack to EarthRanger flow if the target is EarthRanger.
5. `lorawan-device-profiles` contains no OpenCollar profile and `lorawan-devices` only the 2021 first generation entry (ABP). There is no published TTN/ChirpStack device profile for Edge devices; assume LoRaWAN 1.0.x class A OTAA and confirm regional parameters with the maintainer.
6. `lr_region` numeric mapping (1 to 13) is not documented; only "1 = EU868" and the ordered plan list on the wiki are known.
7. Exact behaviour of `cmd_send_all_settings` over LoRaWAN (does it send more than one FPort 3 uplink) and the `0xF0` timestamped messaging variant are not documented.
8. The LR11xx NAV payload (FPort 1) needs Semtech LoRa Cloud (or a compatible solver) to become a position; the solver contract is outside these repositories.
9. Accelerometer FIFO/motion summary uplink: not implemented in public firmware; the `opencollar-acc-calculator` layout is a design study. Ask whether a motion summary port is planned before reserving one.
10. Air quality message length semantics (whether `len` includes the header) should be confirmed against `air_quality.c` in a release that ships the AirQ build; the decoder thresholds are documented in 3.16.
11. Two decoder versus firmware discrepancies should be confirmed with IRNAS: FPort 2 course over ground byte order (firmware writes little-endian, decoder reads big-endian) and FPort 31 msg 0xFE longitude/latitude order (firmware writes longitude first, decoder reads latitude first).
12. The wiki flash read examples encode the count big-endian (`03 E8`); the firmware reads little-endian. Worth reporting so the wiki is corrected.
