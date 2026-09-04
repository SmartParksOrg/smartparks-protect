# Traccar

[Traccar](https://www.traccar.org) is the non-LoRaWAN tracking source: vehicles, motorbikes
and personal trackers reporting over cellular networks. The adapter proves the connectivity
abstraction is generic (architecture 7.2); a Traccar-fed entity shares the map, rules, exports
and integrations with the collars.

Built from the Traccar OpenAPI document and API overview (decision D65). Live verification
waits for a Traccar instance or account.

## Setup

1. In Traccar, create a user that sees the devices to import, or generate an API token for one.
2. Under Server admin, Data sources: New data source, adapter Traccar. Config: `url` (for
   example `https://tracks.example.org`), optionally `web_url`. Credentials: `email` and
   `password`, or `token`.
3. Each Traccar device becomes an identity of type `traccar_device_id` (the numeric Traccar id)
   with the device name, `uniqueId` (IMEI), model and category as attributes. Create a device
   with the Generic JSON driver and link it, or accept it from Needs attention, then assign it
   to a vehicle or person entity.

## Events

The ingest service logs in (`POST /api/session`, session cookie), reads every device
(`GET /api/devices`) and the latest positions (`GET /api/positions`), then keeps the
`/api/socket` websocket open and reconnects after five seconds when it drops:

| Traccar | Smart Parks Protect |
| --- | --- |
| position (`fixTime`, `latitude`, `longitude`, `altitude`, `speed` in knots, `course`, `accuracy`, `attributes`) | source event `position` with the generic JSON shape: `time`, `lat`, `lon`, `altitude`, `speed` in m/s, `heading`, `accuracy`, `satellites`, measurements `battery_level`, `battery_voltage`, `external_voltage`, `odometer_m`, `total_distance_m`, state `ignition`, `motion`; the Traccar record under `raw` |
| position with `valid: false` | source event `position_invalid`, kept raw, no position record |
| event (`geofenceEnter`, `alarm`, `deviceOffline`, ...) | source event `event` with one event `GEOFENCE_ENTER`, `ALARM`, `DEVICE_OFFLINE` (camel case to upper snake case); alarms, offline and geofence exit are warnings |
| device status change (online, offline, unknown) | source event `state` with `connection` in the device state |

`serverTime` is the network receive time; `fixTime` is canonical.

Traccar's own forwarding (position and event forwarding to a URL) is accepted on the data
source's webhook as well: bodies of the form `{"position": ..., "device": ...}` or
`{"event": ..., "device": ..., "position": ...}`.

## Commands

The Generic JSON driver declares one control action, `PLATFORM_COMMAND`, with a command
`type` and `attributes`. Through a Traccar route it becomes `POST /api/commands/send` with
`{deviceId, type, attributes}`; 200 means Traccar sent it, 202 that it is queued until the
device connects. `GET /api/commands/types?deviceId=` lists the types the device's protocol
supports. This is the proof of concept of the abstract control path over a non-LoRaWAN network.

## Links

`OPEN_DEVICE` points at the Traccar web app's device settings page; the path is a guess until
seen live and can be overridden on the data source.

## Troubleshooting

- `refused the credentials`: wrong email or password, or the token was revoked.
- The websocket keeps reconnecting: the Traccar server closes idle sockets behind some proxies;
  every reconnect re-reads the latest positions so nothing is lost.
- Positions arrive with speed zero although the vehicle moves: some protocols report speed only
  with motion events; check `raw`.
