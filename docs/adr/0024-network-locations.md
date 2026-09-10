# ADR 0024: network health apart from device health, and the locations a network provides

Date: 2026-09-10. Status: accepted. Decisions D161 to D164. Phase 23.

## Context

Architecture 20 says network health and device health must be distinct: a collar can be
healthy but poorly connected, or connected well while reporting faults. ADR 0023 had put the
last satellite session as a line in the health card, the only visible place at the time, and
that mixed the two. The same look raised the locations a network provides: an Iridium session's
estimate, ThingPark's `DevEUI_location` (network geolocation, which some KPN collars get), The
Things Stack's `location_solved`. They are useful as an alternative location for a collar whose
GNSS fails, and misleading on the main map without anyone asking: a 64 km circle next to a
good fix on the first live Rock7 delivery.

## Decision

- **A Connectivity tab** on the device page and on the entity page (for the device tracking
  it), one card per data source the device has an identity on, from `GET
  /devices/{id}/connectivity`: the connection state and the last uplink, join and downlink,
  then for LoRaWAN the gateways heard in the period with the best one and its share, the mean
  signal and the frame counter gaps, and for Iridium the last session with its outcome, the
  counter, missed sessions, sessions, bytes and redeliveries in the period. The health card is
  the device's own status again.
- **Network locations are positions of record type `network`.** Adapters put a
  `NetworkLocation` on the inbound message (or the ingest derives one from a satellite session
  the network stands by); the decoder writes it next to the driver's records with the radius as
  accuracy and the method in the attributes; the canonical key keeps it apart from a device fix
  at the same moment. One table, one curation, one export.
- **Every reader takes device fixes by default.** `device_fix()` and `sources_filter()` in
  `shared/curation/effective.py`; the positions list, the tracks, the records read, the rules'
  replay and the integrations exclude network positions unless `sources=network` or `all` (an
  integration needs `include_network_positions` in its settings); the heatmap and the coverage
  read device fixes only; exports keep every row with its record type. The map draws the
  network locations as circles of their radius on the Coverage tab's "Network locations"
  layer, from `GET /projects/{id}/map/network-locations`.
- **The location source is a setting per entity and per device.** `location_source` is
  `device` (default), `network`, or `device_else_network` with `location_fallback_hours`. The
  decoder applies it when it sets the current position: a device fix newer than the newest fix
  known always takes the position; a network location counts only when the setting is
  `network` (newest wins) or `device_else_network` and no device fix arrived within the fallback
  period before it. Both current states keep `latest_position_kind` and `latest_fix_time`; the
  map's features carry `position_kind` and the panels say "network estimate". Live rules see a
  network position only for an entity that opted in.

## Consequences

- Migration 0024 adds the two setting columns to entities and devices and the two state
  columns to both current-state tables.
- Positions written before this release are all device fixes; nothing changes for them.
- The satellite sessions layer of ADR 0023 is replaced by the network locations layer, which
  covers LoRaWAN geolocation as well.
- A live ThingPark location report is still to be recorded; the parser follows the documented
  fields of the LRC-AS tunnel changelog.
