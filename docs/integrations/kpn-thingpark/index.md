# KPN LoRa (ThingPark)

KPN's LoRa network runs on Actility ThingPark. Smart Parks Protect receives its events as HTTP pushes from a ThingPark application server and sends downlinks through the ThingPark downlink API (decisions D53 and D95). The adapter is built from the ThingPark tunnel interface documentation and Actility's published examples; two published pushes with their keys are golden fixtures (`tests/fixtures/payloads/kpn_thingpark/README.md`). Live verification against Smart Parks' KPN account is the open item.

## How authentication works

ThingPark signs every push itself. The URL it posts to carries `LrnDevEui`, `LrnFPort`, `LrnInfos`, `AS_ID`, `Time` and a `Token`: the SHA-256 of body elements that depend on the report (for an uplink `CustomerID`, `DevEUI`, `FPort`, `FCntUp` and `payload_hex`), the query parameters in that order, and the tunnel interface authentication key you enter in ThingPark. Store that key on the data source as the `as_key` credential and the webhook verifies the token; nothing else needs to be configured on the KPN side for authentication. The same key signs downlinks.

Where the portal offers custom headers, `Authorization: Bearer <webhook token>` works as well; the webhook accepts either.

## Setup

1. Server admin, Data sources, New data source, adapter KPN LoRa (ThingPark). Copy the webhook URL (the bearer token is shown once; you need it only for the header alternative).
2. Generate a tunnel interface authentication key: 32 hexadecimal characters, for example with `python3 -c "import secrets; print(secrets.token_hex(16))"`. ThingPark checks its entropy, so do not type a pattern.
3. In the KPN ThingPark Device Manager, create an application server of type HTTP for the application that holds the collars: destination the webhook URL, content type JSON. Under the uplink/downlink security of the application server choose Activate and enter an AS ID (any identifier, for example `smartparks-protect`) and the key from step 2. Leave the optional maximum timestamp deviation at its default. Do not enable forwarding of the AppSKey; the raw payload stays encrypted end to end without it and the key would land in the stored source events.
4. Give the collars an AS routing profile that includes this application server, so their uplinks reach it. ThingPark posts uplinks (`DevEUI_uplink`) and downlink sent reports (`DevEUI_downlink_Sent`); location and notification reports are accepted as well.
5. Back in Protect, edit the data source: credential `as_key` the key from step 2, `as_id` the AS ID from step 3, `downlink_url` `https://api.kpn-lora.com/thingpark/lrc/rest/downlink`, `auth_mode` `token`, `web_url` the portal address so "Open in KPN" points at the device.
6. Register the collar's DevEUI as an external identity on the source, or accept it from Needs attention when the first uplink arrives. Server admin, Data sources, Traffic shows every message the source receives while you connect.

Capabilities are set per source: a public KPN account has no gateway management, no statistics and no join events; edit the capabilities on the source when the account offers more.

## Uplink flow

`DevEUI_uplink` becomes a source event of type `uplink`. `payload_hex` and `FPort` are passed to the driver as the LoRaWAN frame; every LRR in `Lrrs` becomes a gateway reception with RSSI and SNR, and the coordinates ThingPark gives for the best LRR (`LrrLAT`, `LrrLON`) place that gateway on the map; `Time` is the network receive time (`network_received_at`), never the canonical time of a record. `CustomerID`, `DevAddr` and `ModelCfg` are merged into the external identity. Older ThingPark versions send every field as a string, newer ones as numbers; both are read.

## Downlink flow

A command becomes `POST {downlink_url}?DevEUI=&FPort=&Payload=` plus `AS_ID`, `Time` (ISO 8601 with milliseconds and offset), a `CorrelationID` (the first 64 bits of the command id in hex, as ThingPark requires) and the `Token` (SHA-256 of the query in that order followed by the AS key); in bearer mode the `Authorization` header replaces `AS_ID`, `Time` and `Token`. The command is `accepted_by_network` on a 2xx answer; the `DevEUI_downlink_Sent` report echoes the CorrelationID and moves it to `transmitted`. ThingPark reports no acknowledgement for unconfirmed downlinks; the device's answer (a status uplink for a status request) confirms it.

## Timestamps

`Time` is ISO 8601 with an offset (`2026-09-04T10:12:03.421+02:00`). It is stored as `network_received_at`; the device time comes from the OpenCollar frame. The `+` of the offset is part of ThingPark's token, so the webhook reads the query string as it was sent instead of letting the framework turn `+` into a space.

## Troubleshooting

- 401 with "the platform's own token did not verify": the `as_key` on the source differs from the key entered in ThingPark, or the push carries no `Token` because security is not activated on the application server. The API log has a warning with the report type and DevEUI. Nothing is stored for a refused push; the nginx access log on the server shows the attempt.
- 401 without that suffix on a source without `as_key`: only the bearer header is accepted then; store the key or add the header in the portal.
- Events arrive but Needs attention shows unknown DevEUIs: create the devices or link the identities.
- `CONNECTIVITY_AUTH_FAILED` on a command: `as_key` or `api_token` is wrong, or `as_id` does not match the AS ID entered in the application server's security settings ("Security Check. bad AS_ID" in ThingPark's answer).
- `COMMAND_REJECTED` with a ThingPark message: the payload is too long for the data rate, or the device is not routed to this application server.
- Trace Explorer: search by DevEUI; the uplink trace shows source event stored, identity resolved, driver selected, payload decoded, canonical rows written.
