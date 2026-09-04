# Netmore LoRaWAN

Netmore runs LoRaWAN networks in Sweden and other countries on two platforms that share one export format: the LoRaWAN Portal (`portal.blink.services`, API at `api.blink.services`) and the newer Netmore Connect. Smart Parks Protect receives the export format over HTTP push or from the Netmore MQTT broker and sends downlinks through the API of the platform set on the data source (decisions D57 and D58). The adapter follows the published documentation ([export format](https://docs.connect.netmoregroup.com/docs/export-format), [HTTP push](https://docs.connect.netmoregroup.com/docs/http-push), [MQTT](https://docs.connect.netmoregroup.com/docs/mqtt-netmore), [downlink using MQTT](https://docs.connect.netmoregroup.com/docs/downlink-using-mqtt), the Netmore Connect [REST API](https://docs.connect.netmoregroup.com/netmore-connect/docs/rest-api-user-guide) and its OpenAPI document); live verification against a Netmore account is pending and the fixtures are the documentation's examples, see `tests/fixtures/payloads/netmore/README.md`.

## Setup, HTTP push

1. Server admin, Data sources, New data source, adapter Netmore LoRaWAN. The response shows the webhook URL and a bearer token once.
2. In the Netmore portal (LoRaWAN Portal: Export Configs on the service provider; Netmore Connect: Export Configs on the customer), create an HTTP Push export config with the webhook URL and a header `Authorization` with value `Bearer <token>`. Choose a raw export format: "Default (All)" or "Connect (All)". The decoded "Decoding v2" formats carry no raw payload and are refused with an explanation.
3. Select the export config on the devices (or the export config group).
4. For downlinks, set `platform`: `lorawan_portal` (the default) uses the portal login stored as `username` and `password`; `connect` uses an API key created in Netmore Connect, stored as `api_key`. `api_url` defaults to `https://api.blink.services/rest` or `https://api.connect.netmoregroup.com/api/v1` per platform.

## Setup, MQTT

Set `mqtt_host` to `mq.netmoregroup.com` (port 8883, TLS); the portal login (`username`, `password`) authenticates. The ingest service subscribes to `sensor/+/+/payload` and `sensor/+/+/downlink-response` (override with `topics`). Client ids follow Netmore's `<username>-<suffix>` rule.

## Uplink flow

Each export element becomes an `uplink` source event: `payload` and `fPort` are the LoRaWAN frame for the driver, `fCntUp`, `spreadingFactor`, `dr`, `freq`, `rssi`, `snr`, `batteryLevel` and `ack` are provider metadata, every entry of `gateways` is a gateway reception (the single `gatewayIdentifier` when the format has no gateway list), `timestamp` is the network receive time. `sensorType`, the Connect device and group ids and the tags are merged into the external identity.

## Downlink flow

LoRaWAN Portal: the connector logs in with `POST /core/login/{username}` (the token is cached and renewed on a 401), then `POST /net/sensors/{devEui}/downlink` with `fPort`, `payloadHex`, `confirmed`, `validity` (`validity_seconds`, 3600 by default) and `requestId` set to the command id. The device page reads the queue from `GET /net/sensors/{devEui}/downlink` (with `deliveryStatus`) and flushes it with `POST .../downlink/clear`. On the MQTT path a `downlink-response` with `DOWNLINK_SENT` for the command's `requestId` moves it to `transmitted`.

Netmore Connect: `POST /devices/LoRaWAN/{devEui}/LoRaWAN/downlink` with `payloadHex`, `fPort`, `confirmed` and `validity` and the `api-key` header; the numeric answer is the platform reference; `clearDownlink` flushes. Netmore reports no transmission event through the export format on this platform.

Either way the device's answer confirms a status or position request.

## Timestamps

`timestamp` is ISO 8601 UTC with microseconds; stored as `network_received_at`. The device time comes from the OpenCollar frame.

## Troubleshooting

- 401 on the webhook: the `Authorization` header in the export config does not carry the current bearer token.
- `PAYLOAD_DECODE_FAILED` "decoded format": switch the export config to a raw format.
- `CONNECTIVITY_AUTH_FAILED` on a command: the portal login or the API key is wrong, or the account does not cover the device. Log in on the portal once when the login keeps failing (Netmore's own advice for the MQTT broker).
- `DEVICE_NOT_FOUND` on a command: the DevEUI is not a device of the API key's customer.
