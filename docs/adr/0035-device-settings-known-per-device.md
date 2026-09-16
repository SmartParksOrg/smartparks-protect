# 0035. Device settings known per device, from the type's catalogue

Date: 2026-09-16

Status: accepted

## Context

A device's behaviour follows its settings: how often it fixes and reports, what it logs, which network it joins. Protect knew them only as raw hex TLVs in the state history when a collar happened to send a settings frame, and as one command, the GNSS interval. The device performance analysis (phase 28) needed the expected fix interval and had to learn it from the data (decisions D225 to D227) because the settings were not at hand. The OpenCollar firmware publishes its whole settings table per release, so the catalogue of a device type is known; what was missing is the value per device, with where it came from.

## Decision

The driver's catalogue is the device type's settings catalogue (D231): OpenCollar's `catalog.json` carries every setting with its id, type, length, default, range, group, unit, the firmware it appeared in (from the BLE settings app's per-release files) and a description where the firmware research says something. A new table `device_settings` (D228) keeps one row per device and setting: the newest value decoded by the catalogue, its source (`frame`: the device reported it; `ble`: read over Web Bluetooth, which arrives as a delivery on the WebBLE channel; `command`: Protect sent it; `manual`: a person recorded it), its status (`observed`, or `sent` until a frame confirms a command), the time and the delivery or command it came from (D229). The decoder fills it from every settings frame, the command pipeline from every setting it encodes, the API from a person's entry. The device page has a Settings tab (D230) listing the whole catalogue with the known values, "Request all settings" (`cmd_send_all_settings`) and "Set" for any setting, encoded by its type and range and sent through the command pipeline with the high-impact permission and its confirmation; "Record as known" keeps a value without sending. The expected reporting interval reads the known settings first.

## Alternatives considered

- A JSON document on the device's current state: no table, but one document rewritten on every frame, no per-setting time or source without shaping it into the same rows anyway.
- Frames only as a source: simple, but a fleet whose settings were set over Bluetooth or by Protect's own commands would stay unknown until the collar happens to report.
- A settings action per setting in the driver: one hundred and twenty-three actions; one generic action over the catalogue does the same with one code path.

## Consequences

The catalogue must be maintained per firmware release; its `versions` list and `since_firmware` say which release added a setting, and a device's reported firmware stands beside it. OpenCollar Edge firmware 8 changes the settings structure in an important way (Tim, 2026-09-16); the catalogue will have to become version-dependent, keyed by the device's reported firmware, when that release and its documentation are there. The value for `string` and `byte_array` settings is kept as text and hex; keys (`app_key`) are shown as the collar sends them, which a person may find sensitive: the tab is read by the people who may read the device, and set through the same permission as commands. The raw TLVs stay in the state history, so a catalogue correction can be replayed.
