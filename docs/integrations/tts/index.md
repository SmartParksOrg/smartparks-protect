# The Things Stack

[The Things Stack](https://www.thethingsindustries.com/docs/) (Community and Cloud editions)
as a LoRaWAN source: uplinks, joins and downlink events over its webhook integration,
downlinks through its application API, gateways from its gateway API (decision D84). Built
from the documentation; live verification waits for an application on a cluster.

## Setup

1. Under Server admin, Data sources: New data source, adapter The Things Stack. Config:
   `api_url` (the cluster, for example `https://eu1.cloud.thethings.network`), `application_id`,
   `web_url` (the Console, for deep links). Credentials: `api_key`, an application API key
   with traffic writing rights (downlinks) and device reading rights; add gateway rights on a
   user or organisation key if the gateway sync should see them.
2. Copy the webhook URL and its bearer token shown once after saving.
3. In the Console, Integrations, Webhooks: add a custom webhook with format JSON, the webhook
   URL as base URL, an additional header `Authorization: Bearer <token>`, and every message
   type enabled with an empty path (uplink message, join accept, downlink ack, nack, sent,
   failed, queued, location solved).
4. The DevEUI is the device identity (upper case). The TTS device id and application id come
   with the first uplink as identity attributes, or from the device sync.

## Events

| The Things Stack | Smart Parks Protect |
| --- | --- |
| `uplink_message` (`frm_payload`, `f_port`, `f_cnt`, `rx_metadata`, `settings`) | source event `uplink`; the frame and port for the driver; one gateway reception per `rx_metadata` entry with rssi, snr, channel and the gateway's location; spreading factor, frequency and airtime in the provider metadata |
| `join_accept` | `join` |
| `downlink_queued`, `downlink_sent`, `downlink_ack`, `downlink_nack` | `downlink_queued`, `downlink_transmitted`, `downlink_ack` (nack: not acknowledged); the command is found through the correlation id the downlink carried |
| `downlink_failed` | `log` with the error, which fails the command |
| `location_solved` | `location` with the solved coordinates in the metadata |

`received_at` is the network receive time; the device's own time in the payload stays
canonical.

## Commands

A command becomes `POST /api/v3/as/applications/{application_id}/devices/{device_id}/down/push`
with the payload in base64, the port, priority `NORMAL`, the confirmed flag and a correlation
id `smartparks-protect:<command id>`, which the downlink events echo. The command reaches
`queued`; the events move it to transmitted, acknowledged or failed.

## Gateways and devices

"Sync gateways" reads `GET /api/v3/gateways` (name, antenna location) and, per gateway, the
Gateway Server's connection stats (connected, last uplink, counts) into the registry; a
gateway the key may not read is listed without status. The device sync reads the application's
devices with their DevEUI and device id.

## Links

`OPEN_DEVICE` opens the device in the Console, `OPEN_APPLICATION` the application,
`OPEN_GATEWAY` the gateway.

## Troubleshooting

- 401 on the webhook: the additional header is missing or the token was rotated.
- `no The Things Stack device id is known`: no uplink arrived yet; run the device sync, or
  wait for the first uplink.
- `refused the API key`: the key lacks the right for that call (downlinks need traffic writing
  rights; gateways need gateway rights on a key that may see them).
