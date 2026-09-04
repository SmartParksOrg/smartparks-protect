# OpenCollar over Web Bluetooth

A collar next to you can be read and configured from the device page without any network:
the browser talks to it over Bluetooth Low Energy, and everything it reads is handed to the
server as deliveries on the WebBLE channel (architecture 25.4, decisions D76 and D79).

Built from the protocol research (`[port][msg_id][len][data]` frames, research sections 1.1,
3.3, 3.20, 3.22, 4.1, 4.2 and 4.5) with the public Smart Parks BLE settings app as the
behavioural reference. That app is GPL-3.0; this repository is MIT, so nothing was copied
from it. Verification against a physical collar waits for one (see the plan's inputs).

## Requirements

- Chrome or Edge, on a computer or an Android phone. Safari and Firefox do not offer Web
  Bluetooth. The page must be served over HTTPS (or `localhost` for development).
- The collar advertises with the Smart Parks manufacturer id `0x0A61` and the Nordic UART
  service `6e400001-b5a3-f393-e0a9-e50e24dcca9e`; the browser's chooser filters on both. PIN
  protected collars (`device_pin`, status bit `locked`) answer nothing until unlocked; unlocking
  is not offered yet.
- The device control permission in the device's project (project admin) to connect, sync,
  change settings or erase logs. Viewers see the card but cannot connect.

## What the card does

Open the device page of an OpenCollar and use the card "Nearby over Bluetooth".

| Action | Frames | What happens with the answer |
| --- | --- | --- |
| Connect | the chooser, then `cmd_send_status` (`20 A4 00`) and `cmd_get_flash_status` (`20 B3 00`) | Battery, temperature, versions, errors and the stored message count are shown; the frames are synced |
| Status | the same two commands | Refreshes the card |
| Settings | `cmd_send_all_settings` (`20 A7 00`); the device answers with several port 3 frames and a confirmation | Every setting of the protocol catalogue (research 4.4, firmware 7.3.0) with the device's current value; keys and the PIN are masked |
| Write a setting | `[03][id][len][value]`, little-endian per the catalogue type | The confirmation on port 31 when the firmware sends one; the settings are read again |
| Logs | `cmd_flash_get_all` port 0 (`20 BB 01 00`); the device streams port 29 frames and confirms | The frames become a log file of channel `webble` on the server (see [raw log files](raw-log-files.md)); the card shows the counts when the decoder is done |
| Erase | `cmd_flash_clear` (`20 BA 00`) after a confirmation dialog | The flash count is read again |
| Disconnect | | Frames not synced yet are synced first |

Every frame the collar sends during a session is kept and synced: a status message read over
BLE is the same status record a LoRaWAN uplink would carry, with `ble_synced_at` as provenance
and the sync time as its canonical time (status messages carry no clock, research 3.4).

## Commands over the WebBLE route

Control actions are not sent from the card. In the Control card, choose an action; while the
collar is connected in this browser the route "this browser (WebBLE)" is offered and
preselected. The backend creates and encodes the command as for any route (audit, trace,
lifecycle), the browser writes `[port][payload]` to the collar and reports `transmitted`, and
the collar's answer (a status message, a position, a command confirmation) arrives through the
synced frames and confirms the command the way an uplink would (decision D79). A command over
the WebBLE route that no browser executes expires like any other.

## Raw log files

The public BLE app writes raw logs as one base64 frame per line. Files made that way (or with
this application's own sync, which stores the same format) can be uploaded on the device
page; see [raw log files](raw-log-files.md).

## Where the code is

- `services/frontend/src/lib/opencollar-ble.ts`: the protocol (frames, settings encoding,
  status decoding, requests with answers, log streaming) over an injected transport, tested
  in `opencollar-ble.test.ts` without hardware.
- `services/frontend/src/stores/webble.ts` and `hooks/useWebBle.ts`: one session per device in
  the tab, the sync.
- `services/frontend/src/components/devices/WebBleCard.tsx`: the card.
- `shared/device_drivers/opencollar/catalog.json`: the settings, commands and values of the
  protocol, generated from the research document, served by `GET /devices/{id}/driver-catalog`.
