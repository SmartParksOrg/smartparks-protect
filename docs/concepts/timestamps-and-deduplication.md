# Timestamps and deduplication

## Which time is which

| Time | Where | Meaning |
| --- | --- | --- |
| `time` on positions, measurements, states, events | canonical rows | Device-origin time as the driver defines it per record type. The time that matters for maps, charts, rules, attribution and deduplication. |
| `network_received_at` | source events | When the platform (LoRaWAN network server, broker) received the message |
| `satellite_delivered_at`, `ble_synced_at`, `file_uploaded_at` | source events | Delivery times of the other paths |
| `ingested_at` | source events and canonical rows | When Smart Parks Protect accepted it |

A driver declares per record type whether the canonical time is the device time embedded in the payload or, for devices without a clock, the network receive time. Every time column is `TIMESTAMPTZ` in UTC. A naive datetime anywhere raises.

## Why deduplicate

The same device record can arrive over LoRaWAN, WebBLE, a raw log file and Iridium. Each arrival is a source event and is kept. Only one canonical row exists for the record; every source event that delivered it is linked in `source_deliveries`, the first one flagged.

## The canonical key

`device id + canonical time + record type`, plus the metric key for measurements and a payload fingerprint when the driver needs it (ADR 0008). A unique index on `(canonical_key, time)` guarantees at the database level that a record is written once.

## Attribution

Project and entity are resolved at the canonical time of the record, so a record generated in July and delivered in August belongs to July's project (ADR 0010). Records generated while the device had no project are stored with `project_id` null and are visible to server admins until attributed.

## A device clock ahead of time

A device time is canonical, but a clock can be wrong. A record whose device time runs more than an hour ahead of the moment it was delivered (the network's receive time, or the ingest time) cannot be right: nothing is delivered before it happens. Such a record is stored with its device time and marked invalid, so it stays off the map, the lists, the rules and the exports and does not move the device's current state or its last seen; the processing trace says by how much the clock runs ahead. Needs attention lists the devices concerned and the device page warns. The fix is a bulk curation job with a time offset (reason Device clock error) on the device's project: the records move to their real times, and the correction stays on record. Records from the past are never a problem: flash logs and satellite deliveries arrive after the fact by design.
