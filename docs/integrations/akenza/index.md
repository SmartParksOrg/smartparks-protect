# akenza.io

akenza is an IoT platform that sits between LoRaWAN networks (LORIOT, TTN, Swisscom, ChirpStack and others) and applications. Smart Parks Protect receives akenza samples through a Webhook output connector and sends downlinks through the akenza REST API (decision D59). The adapter follows the published documentation ([webhook connector](https://docs.akenza.io/akenza.io/get-started/your-data-flow/connectors/streaming/webhook), [uplink event structure](https://docs.akenza.io/akenza.io/get-started/your-data-flow/device-type/device-type/uplink), [downlink object](https://docs.akenza.io/akenza.io/get-started/your-data-flow/device-type/device-type/downlink), [REST API](https://docs.akenza.io/akenza.io/get-started/reference/api-documentation) and the published API collection at docs.api.akenza.io); live verification against a workspace is pending and the fixture is the documentation's example, see `tests/fixtures/payloads/akenza/README.md`.

## Setup

1. Server admin, Data sources, New data source, adapter akenza.io. The response shows the webhook URL and a bearer token once. Put the workspace id in `workspace_id` for deep links.
2. In akenza, the device type of the collars must keep the raw frame: a custom device type whose uplink script emits `port` and `payloadHex` unchanged (for example `emit('sample', { data: { port: event.data.port, payloadHex: event.data.payloadHex }, topic: 'default' })`). Decoded samples carry no frame and are refused with an explanation.
3. On the data flow, add a Webhook output connector with the webhook URL, method POST, and a header `Authorization` with value `Bearer <token>`.
4. Create an organization API key with device downlink permission and store it as the `api_key` credential.
5. Devices are identified by their akenza device id (`device.id` in the sample), which downlinks need. The LoRaWAN DevEUI (`device.deviceId`) is kept as an identity attribute; link the identity to the device from Needs Attention when the first sample arrives, or create it with the akenza id.

## Uplink flow

The webhook body is the whole sample: `data.port` and `data.payloadHex` form the LoRaWAN frame for the driver; `uplinkMetrics` gives frame counters, RSSI, SNR, spreading factor, transmit power, gateway count, ESP and SQI (no per-gateway list); `uplinkMetrics.timestamp` (the gateway time) is the network receive time. The device name, description and custom fields are merged into the external identity.

## Downlink flow

A command becomes `POST /v3/devices/{akenzaDeviceId}/downlink` with the `x-api-key` header and `{"raw": true, "loraDownlink": {"port", "payloadHex", "confirmed"}}`, the collection's raw LoRa downlink. The command is `accepted_by_network`; akenza exposes no queue or transmission event, so the device's answer confirms a status or position request and other actions end there.

## Troubleshooting

- 401 on the webhook: the `Authorization` header on the output connector does not carry the current bearer token.
- `PAYLOAD_DECODE_FAILED` "no data.payloadHex": the device type decodes the frame; use a passthrough device type for the collars.
- `CONNECTIVITY_AUTH_FAILED` on a command: the API key is wrong or lacks the downlink permission.
- `DEVICE_NOT_FOUND` on a command: the external identity is not the akenza device id; check the identity attributes on the device page.
