# KPN LoRa (ThingPark)

KPN's LoRa network runs on Actility ThingPark. Smart Parks Protect receives its events as HTTP pushes and sends downlinks through the ThingPark downlink API (decision D53). Live verification against a KPN account is pending; the adapter is built from the ThingPark documentation and its fixtures are invented, see the origin note in `tests/fixtures/payloads/kpn_thingpark/README.md`.

## Setup

1. Server admin, Data sources, New data source, adapter KPN LoRa (ThingPark). The response shows the webhook URL and a bearer token once.
2. In ThingPark (or the KPN developer portal), create an HTTP application server for the application that holds the collars, with the webhook URL as destination and `Authorization: Bearer <token>` as a custom header. Select the uplink and downlink sent events.
3. Fill the data source configuration for downlinks: `downlink_url` (the ThingPark downlink endpoint of the account), `auth_mode` `token` with `as_id` and the `as_key` credential, or `bearer` with an `api_token` credential.
4. Register the devices' DevEUIs as external identities on the source, or accept them from Needs Attention when the first uplinks arrive.

Capabilities are set per source: a public KPN account has no gateway management, no statistics and no join events; edit the capabilities on the source when the account offers more.

## Uplink flow

`DevEUI_uplink` becomes a source event of type `uplink`. `payload_hex` and `FPort` are passed to the driver as the LoRaWAN frame; every LRR in `Lrrs` becomes a gateway reception with RSSI and SNR; `Time` is the network receive time (`network_received_at`), never the canonical time of a record. `CustomerID`, `DevAddr` and `ModelCfg` are merged into the external identity.

## Downlink flow

A command becomes `POST {downlink_url}?DevEUI=&FPort=&Payload=` plus, in token mode, `AS_ID`, `Time` and `Token` (SHA-256 of the query in that order followed by the AS key). The command is `accepted_by_network` on a 2xx answer; `DevEUI_downlink_Sent` with the same correlation id moves it to `transmitted`. ThingPark reports no acknowledgement for unconfirmed downlinks; the device's answer (a status uplink for a status request) confirms it.

## Timestamps

`Time` is ISO 8601 with an offset (`2026-09-04T10:12:03.421+02:00`). It is stored as `network_received_at`; the device time comes from the OpenCollar frame.

## Troubleshooting

- 401 on the webhook: the bearer token in the application server header is wrong or was rotated on the source.
- Events arrive but Needs Attention shows unknown DevEUIs: create the devices or link the identities.
- `CONNECTIVITY_AUTH_FAILED` on a command: `as_key` or `api_token` is wrong, or `as_id` does not match the application server.
- `COMMAND_REJECTED` with a ThingPark message: the payload is too long for the data rate, or the device is not in the application.
- Trace Explorer: search by DevEUI; the uplink trace shows source event stored, identity resolved, driver selected, payload decoded, canonical rows written.
