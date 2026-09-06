# KPN LoRa (ThingPark)

KPN's LoRa network runs on Actility ThingPark. Smart Parks Protect receives its events as HTTP pushes from a ThingPark application server and sends downlinks through the ThingPark downlink API (decisions D53 and D95). The adapter is built from the ThingPark tunnel interface documentation and Actility's published examples; two published pushes with their keys are golden fixtures (`tests/fixtures/payloads/kpn_thingpark/README.md`). Live verification against Smart Parks' KPN account is the open item.

## How authentication works

ThingPark signs every push itself. The URL it posts to carries `LrnDevEui`, `LrnFPort`, `LrnInfos`, `AS_ID`, `Time` and a `Token`: the SHA-256 of body elements that depend on the report (for an uplink `CustomerID`, `DevEUI`, `FPort`, `FCntUp` and `payload_hex`), the query parameters in that order, and the tunnel interface authentication key you enter in ThingPark. Store that key on the data source as the `as_key` credential and the webhook verifies the token; nothing else needs to be configured on the KPN side for authentication. The same key signs downlinks.

Where the portal offers custom headers, `Authorization: Bearer <webhook token>` works as well; the webhook accepts either.

ThingPark's `DevEUI_notification` report is a `join` event when its `Type` is join, so a collar that joins the network shows as such in the traffic view and in the device's connectivity; other notification types stay platform log lines.

## Setup

1. In the KPN ThingPark Device Manager (`kpn-lora.com/deviceManager`), open Application servers. Smart Parks has one HTTP application server per subscriber already, with its uplink/downlink security active: note the AS ID shown there and have its tunnel interface authentication key at hand. A new application server gets the same: type HTTP, content type JSON, then Activate under uplink/downlink security with an AS ID and a 32-character hexadecimal key (`python3 -c "import secrets; print(secrets.token_hex(16))"`; ThingPark checks its entropy). Do not enable forwarding of the AppSKey; the payload stays encrypted end to end without it and the key would land in the stored source events.
2. Server admin, Data sources, New data source, adapter KPN LoRa (ThingPark): credential `as_key` the key, `as_id` the AS ID, `web_url` the portal address so "Open in KPN" points at the device. The downlink URL is KPN's by default. Copy the webhook URL from the result (the bearer token shown once is only for the header alternative).
3. In the application server's route, add the webhook URL as a destination. With more than one destination set the routing strategy to Blast: Sequential is a failover list and posts only to the first destination that answers.
4. The collars reach the application server through their AS routing profile. ThingPark posts uplinks (`DevEUI_uplink`) and downlink sent reports (`DevEUI_downlink_Sent`); location and notification reports are accepted as well.
5. Register the collars' DevEUIs as external identities on the source, or accept them from Needs attention when the first uplinks arrive: every device routed to the application server posts to Protect, so expect the whole application there. Select the ones you run here and "Create devices" makes them in one go, named as ThingPark names them, with an entity each if you pick an entity type; "Ignore" the rest. Server admin, Data sources, Traffic shows every message the source receives while you connect.

Capabilities are set per source: a public KPN account has no gateway management, no statistics and no join events; edit the capabilities on the source when the account offers more.

## Uplink flow

`DevEUI_uplink` becomes a source event of type `uplink`. `payload_hex` and `FPort` are passed to the driver as the LoRaWAN frame; every LRR in `Lrrs` becomes a gateway reception with RSSI and SNR, and the coordinates ThingPark gives for the best LRR (`LrrLAT`, `LrrLON`) place that gateway on the map; `Time` is the network receive time (`network_received_at`), never the canonical time of a record. `CustomerID`, `DevAddr` and `ModelCfg` are merged into the external identity. Older ThingPark versions send every field as a string, newer ones as numbers; both are read.

## Downlink flow

A command becomes `POST {downlink_url}?DevEUI=&FPort=&Payload=` plus `AS_ID`, `Time` (ISO 8601 with milliseconds and offset), a `CorrelationID` (the first 64 bits of the command id in hex, as ThingPark requires) and the `Token` (SHA-256 of the query in that order followed by the same AS key). The command is `accepted_by_network` on a 2xx answer. ThingPark queues it until the collar's next uplink, then posts a `DevEUI_downlink_Sent` report with the CorrelationID: `DeliveryStatus` 1 means an LRR sent it and the command becomes `transmitted`; 0 means it was not sent and the command fails with the causes ThingPark gives per slot (`DeliveryFailedCause1` for RX1, `2` for RX2, `3` for the ping slot), translated on the command timeline (`C0: LRC selected RX2` on RX1 next to a sent report only says the second slot was used). ThingPark reports no acknowledgement for unconfirmed downlinks; the device's answer (a status uplink for a status request) confirms it. Live on 2026-09-06: a Set GNSS interval was accepted, and 39 seconds later the collar's uplink collected it and the report moved the command to transmitted.

## Timestamps

`Time` is ISO 8601 with an offset (`2026-09-04T10:12:03.421+02:00`). It is stored as `network_received_at`; the device time comes from the OpenCollar frame. The `+` of the offset is part of ThingPark's token, so the webhook reads the query string as it was sent instead of letting the framework turn `+` into a space.

## Troubleshooting

- 401 with "the platform's own token did not verify": the `as_key` on the source differs from the key entered in ThingPark, or the push carries no `Token` because security is not activated on the application server. The API log has a warning with the report type and DevEUI. Nothing is stored for a refused push; the nginx access log on the server shows the attempt.
- 401 without that suffix on a source without `as_key`: only the bearer header is accepted then; store the key or add the header in the portal.
- Events arrive but Needs attention shows unknown DevEUIs: create the devices or link the identities. An application server posts every device routed to it, so a shared KPN application fills Needs attention with every collar of the subscriber; link the ones you run here and ignore the rest.
- An uplink on port 199 (or 8, 17) decodes into nothing: these are legacy messages of firmware before 7.1 (the Modem-E info message on 199); the trace notes it and the source event stays. A port 0 uplink is a MAC-only frame without application payload; it updates the connectivity state and nothing else.
- Status of the downlink channel: "ready" until the first downlink through this source, then the outcome of the last one; ThingPark has no call to test the credentials without sending.
- `CONNECTIVITY_AUTH_FAILED` on a command: `as_key` is wrong, or `as_id` does not match the AS ID entered in the application server's security settings ("Security Check. bad AS_ID" in ThingPark's answer).
- `COMMAND_REJECTED` with a ThingPark message: the payload is too long for the data rate, or the device is not routed to this application server.
- Trace Explorer: search by DevEUI; the uplink trace shows source event stored, identity resolved, driver selected, payload decoded, canonical rows written.
