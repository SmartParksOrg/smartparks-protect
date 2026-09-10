# Cloudloop (Iridium)

[Cloudloop](https://knowledge.cloudloop.com) by Ground Control is the platform behind
RockBLOCK Iridium modems. An OpenCollar with a RockBLOCK sends its satellite buffer over
Iridium Short Burst Data; Cloudloop delivers every message to a webhook and relays commands
back (architecture 25.9, decision D78).

Built from the Cloudloop knowledge base and its public Postman collection (fetched
2026-09-04); the API calls were confirmed against Smart Parks' account on 2026-09-09 (ping,
things, subscribers, hardware, groups and destinations). On 2026-09-10 the webhook path was
proven live: a destination created through the API (`Data/CreateHttpDestination`, format
`CONTENT_TYPE_HTTP_LINGO`, added to the All Things group with `Data/DoAddDestination`),
Cloudloop's own `Data/DoTestDestination` delivered to the dev server through the address
allow-list, and a real 42 byte collar message replayed through the webhook decoded into a
GNSS fix and a status message (fixtures under `tests/fixtures/payloads/cloudloop/`). A message
from a collar in the field and a command wait for a collar to wake.

## Setup

1. Under Server admin, Data sources: New data source, adapter Cloudloop (Iridium). Config:
   `allowed_source_ips` (Cloudloop posts from `35.178.100.117` and `52.56.155.169`, confirmed
   live on 2026-09-10; leave the list empty to accept any address; the check uses the address
   the reverse proxy saw, so a caller cannot forge it), `web_url` for deep links. Credentials: `token`, the
   account's API token (requested from Ground Control support, regenerated with
   `User/DoGenerateToken`), needed for commands and the thing list only.
2. Copy the webhook URL shown once after saving. It carries the source's token as
   `?token=...` because Cloudloop sends no authentication header.
3. In Cloudloop Data, add an HTTP Webhook destination with that URL and format JSON (Lingo),
   the recommended one, and add it to a thing group (a group can post to several destinations,
   so an existing pipeline keeps its own). The destination shows grey until its first delivery
   and green after; "Send test message" on it (or `Data/DoTestDestination` with a thing) posts
   a text payload, which arrives as a failed source event of that thing's device, the proof
   that the URL, the token and the address list work. Cloudloop expects HTTP 200 within five
   seconds and retries with exponential backoff for about twelve hours.
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
| `sbd.momsn`, `sbd.mtmsn`, `sbd.status`, `sbd.location` (Iridium geolocation with `cep`) | the satellite session (ADR 0023); `sbd.cdrReference` stays provider metadata |
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
hands it to the collar at its next satellite session. Delivery statuses are not polled: an
MTMSN above zero in a later session says the modem received one queued message, which moves
the oldest pending command to transmitted, and the collar's answer confirms it through the
action's interpreter.

A route needs the thing id: from the first message's identity attributes, or from the
management sync linked to the device.

## Identity mapping

- `imei` (15 digits): the hardware, from every message. Preferred identity.
- `cloudloop_thing` (32 characters, case sensitive): Cloudloop's device object, listed by the
  management sync only for a thing without hardware.

The management sync (Sync devices on the data source) joins `Data/GetThings` with
`Sbd/GetSubscribers` (the name and description shown in Cloudloop, the last seen time) and
`Hardware/GetHardwares` (the IMEI): a thing with a known IMEI is listed as the `imei` identity
its messages use, named after its subscriber, with the thing id as an attribute, so linking it
once serves the inbound path and commands before any message arrives.

## Past messages

`Data/GetMessageRecordsForThing` (times as `YYYY-MM-DD HH:MM:SS`) lists a thing's messages
with their direction, size and a `snippet` of the first 128 bytes in hex; longer messages are
not available in full through the API, so a replay of past data is limited to messages of at
most 128 bytes. `Data/GetPulseRecordsForDestination` shows every delivery attempt with its
status.

## Timestamps

`sbd.sessionAt` is when the satellite session ran, `receivedAt` when Cloudloop received the
message; both are provenance. The canonical time comes from the record inside the payload
(research 25.3): a fix delivered days later over satellite keeps its fix time.

## What the session tells you

Every delivery carries the satellite session (ADR 0023): its outcome, the modem's session
counter (MOMSN), the size, and the network's estimate of where the modem was with its error
radius (CEP, in km). The traffic view shows them on the row, the source event dialog under
Provenance, and the device's health card keeps the last session as a line that warns when a
session failed or sessions went missing. The estimates the network stands by draw as circles on
the live map ("Satellite sessions" in the Coverage tab); an estimate the network calls poor is
kept but not drawn. A retry of a delivery the server did not acknowledge is stored as a
duplicate, not processed twice. A fix far outside the estimate's circle is noted on the trace.

## Troubleshooting

- 401 on the webhook: the URL lost its `?token=`; copy it again from the data source (rotate
  the token if it leaked).
- 403 `Address ... may not post`: the request came from an address outside
  `allowed_source_ips`, or the proxy does not pass `X-Forwarded-For`.
- The identity is known but commands fail with `no Cloudloop thing id`: no message arrived yet
  and the thing identity is not linked; run the management sync and link the thing.
- `Cloudloop refused the token`: the API token is wrong or was regenerated.
- The deep link path (`{web_url}/things/{thing_id}`) is a guess until seen live and can be
  overridden on the data source; the console lives at `https://console.cloudloop.com`.
