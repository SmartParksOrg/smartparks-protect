# Rock7 RockBLOCK (Iridium)

[Rock 7 Core](https://rockblock.rock7.com) is Ground Control's older RockBLOCK platform,
the one before [Cloudloop](../cloudloop/index.md). Some Iridium modems are still registered
there. The adapter receives their messages through a delivery group's HTTP endpoint and sends
commands through the MT web service (decision D156). New modems belong in Cloudloop; this
adapter is for the ones that stay.

Built from the RockBLOCK web services documentation (docs.groundcontrol.com, fetched
2026-09-09). Live verification waits for a modem in a delivery group pointed at the server.

## Setup

1. Under Server admin, Data sources: New data source, adapter Rock7 RockBLOCK (Iridium).
   Config: `allowed_source_ips` (Rock7 documents no addresses; leave the list empty), `web_url`
   for links. Credentials: `username` and `password`, the portal login, needed for commands
   only.
2. Copy the webhook URL shown once after saving. It carries the source's token as
   `?token=...` because Rock7 sends no authentication.
3. In the RockBLOCK management system, make a delivery group with the modems and add the
   webhook URL as its endpoint, type `HTTP_POST` (a form) or `HTTP_JSON`. Rock7 expects HTTP
   200 within three seconds and retries with a doubling backoff for fourteen attempts, almost
   six days.
4. The IMEI of the modem is the device identity (type `imei`). Link it to the collar, or
   accept it from Needs attention when the first message arrives. There is no device list to
   sync: Rock7 has no API for it.

## Inbound

A delivery becomes one source event on the Iridium channel:

| Rock7 field | Smart Parks Protect |
| --- | --- |
| `imei` | identity `imei` |
| `serial` | identity attribute |
| `data` (hex) | `data_hex` for the device driver, untouched |
| `transmit_time` (`YY-MM-DD HH:MM:SS`, UTC) | `satellite_delivered_at`, provenance only |
| `momsn`, `iridium_latitude`, `iridium_longitude`, `iridium_cep` (km) | provider metadata |
| a message without payload | event type `sbd_session`, kept raw, nothing decoded |

The OpenCollar driver reads the payload as stacked stored records, as over Cloudloop, so the
record's own timestamp stays canonical.

## Outbound MT

Commands over a Rock7 route call `POST https://rockblock.rock7.com/rockblock/MT` with the
IMEI, the portal login and the frame `[port][msg_id][len][data]` in hex, at most 270 bytes.
The answer `OK,<id>` reaches `queued`; the modem downloads the message at its next session,
and a ring alert wakes a powered modem in coverage. `FAILED,<code>,<description>` is read by
code: 10 is a wrong login (an authentication failure), 99 a Rock7 outage (retried), the rest
(no such IMEI on the account, no line rental, no credit, bad hex, too long, empty) a rejected
command with the reason. A command option `flush` clears the modem's queue first.

## Connection test

Rock7 has no ping. The test sends an empty message to a placeholder IMEI and reads the
failure code: 10 means the login is wrong, any other code means the login was accepted. That
Rock7 checks the login before the message is an assumption from the documented codes, to
confirm live.

## Troubleshooting

- 401 on the webhook: the URL lost its `?token=`; copy it again from the data source.
- 422 `Body is not valid JSON`: the endpoint type is neither `HTTP_POST` nor `HTTP_JSON`.
- `Rock7 refused the login`: the portal username or password is wrong or changed.
- `insufficient credit`: top up the account; the command was not queued.
