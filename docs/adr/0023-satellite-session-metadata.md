# ADR 0023: the satellite session behind an Iridium delivery

Date: 2026-09-10. Status: accepted. Decisions D158 to D160.

## Context

An Iridium delivery (Cloudloop, Rock7) carries more than the collar's bytes: the outcome of
the satellite session, the modem's session counter (MOMSN), the sequence number of the message
the modem received in that session (MTMSN, Cloudloop only), the size, and the network's own
estimate of where the modem was with a circular error probable in kilometres. Until now the
adapters kept all of it as provider metadata and nothing read it. The first live Rock7 delivery
showed why it matters: session status 2 (a poor location estimate) with a 64 km circle next to
a perfectly good GNSS fix in the payload.

## Decision

- **One shape.** `shared/connectivity/satellite.py` defines `SatelliteSession` (status in one
  vocabulary mapped from Iridium's codes and Cloudloop's names, sequence, MT sequence, estimate,
  CEP, bytes, session time). Adapters fill `InboundMessage.satellite_session`; the ingest stores
  it as `provider_metadata["satellite_session"]` on the source event, where the traffic view,
  the source event dialog, the decoder and the map read it.
- **The estimate is provenance, never a position.** It is shown as a circle of its CEP on the
  live map ("Satellite sessions" in the layers panel, `GET /projects/{id}/map/satellite-sessions`,
  bounded), on the traffic row and in the source event dialog, and only when the session status
  stands by it (`ok`, `mt_too_large`). A decoded fix more than three CEP radii from the
  estimate gets a note on the trace's "payload decoded" step.
- **Status on trace and health.** Every satellite delivery gets an ingest step "satellite
  session" with the status, counters, size and estimate. The decoder keeps the last session on
  the connectivity state of the device and source (`attributes["satellite"]`), and the device
  health gains a line "Satellite session": a failed session warns, a barred modem is critical,
  sessions missing before the last one warn.
- **Counters.** A delivery with the same sequence and payload as one in the last seven days is
  the platform's retry: stored with status `duplicate`, traced, not processed again. A jump in
  the counter is counted as missed sessions on the delivery and in the identity's attributes.
  An MTMSN above zero means the session carried one queued message to the modem: the oldest
  command pending on that route, submitted before the session, moves to `transmitted`. Rock7
  deliveries carry no MTMSN, so there the collar's answer alone confirms a command.

## Consequences

- No migration: the session lives in the source event's metadata, the identity's attributes and
  the connectivity state's attributes, all JSONB.
- Cost (bytes and sessions per device and month) is not built; the bytes are on every session
  for when it is.
- Rock7's `iridium_session_status` is undocumented; the code follows the Iridium DirectIP
  session codes, which the first live delivery matched.
