# 0008. Device timestamp deduplication

Date: 2026-09-03

Status: accepted

## Context

The same OpenCollar record can arrive over LoRaWAN, WebBLE, a raw log file and Iridium (architecture 25). No identifier may be added to the radio protocol for deduplication. Delivery times differ per path and say nothing about when the record was generated.

## Decision

Canonical time is the device-origin time defined by the driver per record type, including timestamps embedded in log records that travel inside a later uplink. The canonical key of a position or measurement is `device EUI + canonical time + record type`, plus a stable payload fingerprint where the driver needs it. Every canonical table has a unique index on the canonical key and time. Every source delivery is kept as its own immutable source event; deduplication happens when the canonical row is written, and additional deliveries link to the existing row (phase 2). Network receive time, satellite delivery time, BLE sync time, file upload time and ingest time are stored on the source event as provenance and are never part of the key. Every datetime in the codebase is timezone-aware; a naive datetime raises.

## Alternatives considered

- Deduplicate on network receive time: the same record delivered twice has two receive times.
- Deduplicate on payload hash alone: two identical readings at different moments would collapse.
- Drop later deliveries: loses the provenance the architecture requires.

## Consequences

Drivers must declare timestamp semantics per record type. The unique index makes double processing impossible at the database level. Late data (log uploads, satellite backlog) lands at its true time and is attributed to the project of that time (0010).
