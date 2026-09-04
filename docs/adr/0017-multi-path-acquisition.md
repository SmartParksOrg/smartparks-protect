# ADR 0017: frames as deliveries, built-in channel sources, the browser as a route

- Status: accepted
- Date: 2026-09-04
- Decisions: D76, D77, D78, D79

## Context

Architecture 25 requires the same OpenCollar record to arrive over LoRaWAN, over Web Bluetooth,
in a raw log file and over Iridium, every delivery retained, the record shown once. The
deduplication model of phase 2 (canonical keys, `source_deliveries`) covers the record side;
this phase adds the acquisition paths and has to decide what a delivery is on each of them,
where the data source of a browser or a file is, and how a command travels when the route is
the browser.

## Decision

**A frame is a delivery.** Every line of a raw log file and every BLE notification frame is
one source event with the frame as `data_hex`, on the channel `log_file` or `webble`. The
device driver decodes it through the pipeline that decodes a LoRaWAN uplink: the port byte in
front selects the message, port 29 carries stored records with their own timestamps. Provenance
is per frame, duplicate detection is the existing one, and the Traffic and Trace pages show
frames like any other event.

**Built-in data sources per channel.** "Browser (WebBLE)" and "Log file upload" are data
sources created by migration with fixed ids, adapters `webble` and `log_file` in the registry.
The device's identity on them is its own id, created when a browser connects or a file is
uploaded. Source events keep their data source, route selection sees the channel, and the
sources cannot be deleted.

**The file is the unit of work.** `device_log_files` holds the file (in the
`device-log-files` bucket), its status, counts and period. A browser sync is stored as a file
of channel `webble` in the same one-frame-per-line format the public BLE app exports, so
upload and sync share one worker (the decoder service), one status model, one re-decode and
one download. Frames are decoded in batches of one transaction each.

**Cloudloop over a webhook with the token in the URL.** Cloudloop cannot set a header, so the
ingest endpoint accepts `?token=` for adapters that declare it, and a source may restrict the
caller addresses. The IMEI is the identity, the thing id an attribute. Commands use the
platform's SBD endpoint with the collar's satellite framing.

**The browser is a route, never the default.** The WebBLE source has a command connector that
only queues the command; the API creates and encodes it like any other, the browser writes
the frame and reports the result, and the device's answer arrives through the synced frames
and confirms the command through the action's interpreter. Route selection skips routes that
need a connected client unless the caller chose one; the control dialog offers every route
with the most recently seen network route preselected.

## Consequences

- One pipeline, one provenance model and one trace model for four acquisition paths; a fix
  delivered three times is one position with three deliveries, verified by a test.
- Large flash dumps become many source events (a 4 MB flash is about seventeen thousand
  frames). Compact traces and the routine trace retention keep that bounded.
- The frontend carries a protocol implementation (BLE) that no test can exercise against a
  real device here; the protocol is written from the research document and tested against a
  scripted transport, and waits for a collar.
- The Cloudloop token in a URL is a secret in logs of intermediaries; rotation is one click,
  and the address allow-list limits who can post.
