# Cloudloop (Iridium)

[Cloudloop](https://knowledge.cloudloop.com) by Ground Control is the platform behind
RockBLOCK Iridium modems. An OpenCollar with a RockBLOCK sends its satellite buffer over
Iridium Short Burst Data; Cloudloop delivers every message to a webhook and relays commands
back (architecture 25.9, decision D78).

Built from the Cloudloop knowledge base and its public Postman collection (fetched
2026-09-04). Live verification waits for a Cloudloop account with an enrolled RockBLOCK.

## Setup

1. Under Server admin, Data sources: New data source, adapter Cloudloop (Iridium). Config:
   `allowed_source_ips` (Cloudloop posts from `35.178.100.117` and `52.56.155.169`; leave the
   list empty to accept any address), `web_url` for deep links. Credentials: `token`, the
   account's API token (requested from Ground Control support, regenerated with
   `User/DoGenerateToken`), needed for commands and the thing list only.
2. Copy the webhook URL shown once after saving. It carries the source's token as
   `?token=...` because Cloudloop sends no authentication header.
3. In Cloudloop Data, add an HTTP Webhook destination with that URL and format JSON (Lingo),
   the recommended one. Cloudloop expects HTTP 200 within five seconds and retries with
   exponential backoff for about twelve hours.
4. The IMEI of the RockBLOCK is the device identity (type `imei`). Link it to the collar, or
   accept it from Needs attention when the first message arrives. The Cloudloop thing id
   arrives as an identity attribute with the first message; the deep link and commands use it.

## Inbound SBD

A LingoMO message becomes one source event on the Iridium channel:

| Lingo field | Smart Parks Protect |
| --- | --- |
| `identity.hardware.imei`, `sbd.imei` | identity `imei` |
| `identity.thingId`, `identity.subscriber.*`, `identity.hardware.*` | identity attributes (`thing_id`, `subscriber_id`, `hardware_type`, `serial`) |
| `message` (base64) | `data_hex` for the device driver, untouched |
| `sbd.sessionAt` | `satellite_delivered_at`, provenance only |
| `receivedAt` | `network_received_at` |
| `sbd.momsn`, `sbd.mtmsn`, `sbd.cdrReference`, `sbd.status`, `sbd.location` (Iridium geolocation with `cep`) | provider metadata |
| a message without payload | event type `sbd_session`, kept raw, nothing decoded |

The deprecated Core and form shapes (`imei`, `momsn`, `transmit_time`, `data` in hex) are
accepted too. The OpenCollar driver reads the payload as stacked stored records
(`[port][msg_id][len][data][timestamp]`, the flash storage format the satellite buffer uses),
so the record's own timestamp stays canonical and a fix that also came over LoRaWAN is one
position with two deliveries.

## Outbound MT

Commands over an Iridium route call `POST Data/DoSendSbdMessage` with the thing id and the
frame `[port][msg_id][len][data]` in hex, at most 270 bytes, the framing the collar's
satellite receive path expects (wiki satellite page). The command reaches `queued`; Cloudloop
hands it to the collar at its next satellite session. Delivery statuses are not polled: the
collar's answer arrives as a later message and confirms the command through the action's
interpreter.

A route needs the thing id: from the first message's identity attributes, or from the
management sync (`Data/GetThings`, identities of type `cloudloop_thing`) linked to the device.

## Identity mapping

- `imei` (15 digits): the hardware, from every message. Preferred identity.
- `cloudloop_thing` (32 characters, case sensitive): Cloudloop's device object. Listed by the
  management sync; usable as a route once linked.

## Timestamps

`sbd.sessionAt` is when the satellite session ran, `receivedAt` when Cloudloop received the
message; both are provenance. The canonical time comes from the record inside the payload
(research 25.3): a fix delivered days later over satellite keeps its fix time.

## Troubleshooting

- 401 on the webhook: the URL lost its `?token=`; copy it again from the data source (rotate
  the token if it leaked).
- 403 `Address ... may not post`: the request came from an address outside
  `allowed_source_ips`, or the proxy does not pass `X-Forwarded-For`.
- The identity is known but commands fail with `no Cloudloop thing id`: no message arrived yet
  and the thing identity is not linked; run the management sync and link the thing.
- `Cloudloop refused the token`: the API token is wrong or was regenerated.
- The deep link path (`{web_url}/things/{thing_id}`) is a guess until seen live and can be
  overridden on the data source.
