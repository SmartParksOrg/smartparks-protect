# Cloudloop fixtures

Lingo documents of Cloudloop's HTTP webhook destination (format JSON Lingo). Keep the origin of
every file here.

- `lingo_destination_test_live.json`: the body Cloudloop posted to the dev server on 2026-09-10
  when `Data/DoTestDestination` was called for thing 220757 (IMEI 301434061403790) on the
  destination "Smart Parks Protect dev (JSON Lingo)", stored as source event 37850. The real
  shape of a live delivery: `identity` carries `thingGroup` (a list), the hardware `esn` and
  `key`, no `sbd` section for a platform test, and the message is a text (not an OpenCollar
  frame), so the decoder fails it on purpose.
- `lingo_220757_replayed.json`: the Lingo shape rebuilt on 2026-09-10 around a real 42 byte
  satellite message of collar 220757 (message record `rLzVjdQqPgkanllXARyonpRyKbJZONAG`, sent
  2026-04-29 16:15:45 UTC, read with `Data/GetMessageRecordsForThing`, whose `snippet` holds
  the first 128 bytes of a message; this one is complete). The identity ids are the account's
  real thing, subscriber and hardware ids; `sbd.momsn`, `cdrReference` and `location` are not
  in the record read and are null. Replayed through the dev server's webhook as source event
  37849: a GNSS fix at 2026-04-29 15:17:09 UTC and the status message before it.
