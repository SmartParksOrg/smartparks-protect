# CRA IoT (České Radiokomunikace)

The Czech national LoRaWAN network of České Radiokomunikace and its IoT platform
(portal.iot.cra.cz) as a source (decision D90): uplinks over the platform's HTTP endpoint,
downlinks and the device list through its REST API. The platform's message is the LORIOT
format inside an integration envelope.

Built from the platform's public documentation (github.com/cra-iot/documentation: the HTTP
output, the message structure, the API guide) and its Swagger document at
`https://api.iot.cra.cz/cxf/api/v1/swagger.json`. Live verification waits for an account
with a LoRa device.

## Setup

1. Under Server admin, Data sources: New data source, adapter CRA IoT. Config: `api_url`
   (the REST API, default `https://api.iot.cra.cz/cxf/api/v1`), `uplink_cmd` (`gw` by
   default, see below), `web_url` (the portal, for the application link). Credentials:
   `username` and `password` of a portal account (the API takes a token from the CRA single
   sign-on with them; the documented `client_secret` of the `iot-api-client` is built in and
   can be overridden).
2. Copy the webhook URL and its bearer token shown once after saving.
3. In the portal, under outputs, create an HTTP endpoint with that URL and an
   `Authorization: Bearer <token>` header, create a data flow (device group) with the
   collars and assign it to the endpoint. The platform posts from 84.244.71.160.
4. The DevEUI is the device identity (upper case). "Sync devices" reads the account's LoRa
   devices from the API.

## Messages

The endpoint posts `{"type": "D", "data": "<message as a JSON string>", "tech": "L",
"tags": [...]}`. The message has LORIOT's shape: `cmd`, `EUI`, `ts` (server receive time in
milliseconds), `fcnt`, `port`, `freq`, `dr`, `ack`, `gws` (the gateways that received it with
`gweui`, `rssi`, `snr`), `bat` (the LoRaWAN DevStatus battery byte: 0 external power, 255
unknown, 1 to 254 as 0 to 100 %), `data` (the decrypted frame in hex, when the AppSKey is on
the platform) or `encdata`, and `_id`.

| `cmd` | Smart Parks Protect |
| --- | --- |
| `gw` (the deduplicated message with every gateway) | `uplink` with the frame and port, one gateway reception per `gws` entry, battery, data rate and frequency in the provider metadata |
| `rx` (the first gateway's copy) | ignored, unless `uplink_cmd` is `rx` on a platform that sends only those; then `gw` is ignored |
| `geo` (network geolocation, no longer offered) | `location` with the coordinates in the metadata |
| a message with `encdata` and no `data` | refused: the platform has no AppSKey for the device |

Messages posted bare (without the envelope) or as a list are accepted as well, so the REST
and MQTT shapes work through the same webhook.

## Commands

A command becomes `POST /lora/devices/{EUI}/down/messages` with
`{"cmd": "tx", "EUI", "port", "data" (hex), "confirmed", "clear": false}` and reaches
`queued`; the platform reports no transmission, so the device's answer confirms it where the
action has an interpreter. Tokens from the single sign-on (password grant) are cached until
they expire.

## Devices

"Sync devices" pages through `GET /lora/devices` (`deviceId` is the DevEUI, `custDeviceName`
the name, `status` and `enabled` as attributes).

## Troubleshooting

- 401 on the webhook: the header on the platform's endpoint is missing or the token was
  rotated.
- `CRA IoT refused the login`: the username or password is wrong, or the account has no API
  access.
- `encrypted payload`: assign the AppSKey to the device on the platform or decrypt on the
  application side.
- A device seen twice per uplink: the platform sends both `rx` and `gw`; keep `uplink_cmd`
  at `gw`.
