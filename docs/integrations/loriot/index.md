# LORIOT

LORIOT is the international LoRaWAN network of the first Smart Parks deployments. Smart Parks Protect connects to the application's websocket output and sends downlinks over the same connection (decision D54). Live verification against a LORIOT application is pending; the adapter is built from the LORIOT documentation and its fixtures are invented, see `tests/fixtures/payloads/loriot/README.md`.

## Setup

1. In LORIOT, open the application and add an output of type Websocket; copy its token.
2. Server admin, Data sources, New data source, adapter LORIOT: `server` (for example `eu1.loriot.io`), `app_id` and `web_url` for deep links, credential `token`.
3. The ingest service connects within a minute (`connector started` in its log) and reconnects after a drop.
4. Register the DevEUIs as external identities, or accept them from Needs Attention.

LORIOT's HTTP output is accepted as well: point it at the source's webhook URL with the bearer token; the frames are the same JSON.

## Uplink flow

`rx` frames become `uplink` source events with `data` and `port` as the LoRaWAN frame, `fcnt`, data rate, RSSI and SNR as provider metadata; `gw` frames become `gateway_receptions` events holding every gateway that received the uplink. `ts` (milliseconds) is the network receive time.

## Downlink flow

A command opens a short-lived websocket to the application output, sends `{"cmd":"tx","EUI","port","confirmed","data"}` and reads LORIOT's `tx` answer: `success` with a sequence number moves the command to `queued`, an error fails it. `txd` with the same sequence number moves it to `transmitted`. The device's answer confirms it when the action has an interpreter.

## Timestamps

`ts` is milliseconds since the epoch, stored as `network_received_at`. Device time comes from the OpenCollar frame.

## Troubleshooting

- The ingest log shows `websocket lost, reconnecting` in a loop: the token is wrong or the output was deleted in LORIOT.
- No `gw` frames: enable gateway information on the LORIOT output.
- `CONNECTIVITY_UNAVAILABLE` on a command: LORIOT did not answer the `tx` frame within 15 seconds; the bus retries the command action for automations, a person retries from the device page.
