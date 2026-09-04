# Processing pipeline

How a message from an external platform becomes canonical data (phase 2).

```
platform  ->  adapter (ingest service or API webhook)  ->  source_events + trace
          ->  bus: source_event.received
          ->  decoder: driver selected, decoded, canonical key, dedup, attribution
          ->  positions / measurements / device_state_history / events + source_deliveries
          ->  current state tables
          ->  bus: position.created, measurement.created, device.state_changed, event.created
```

## Ingest

`shared/ingest.py` is used by every entry point. The API endpoint `POST /api/v1/ingest/http/{data_source_id}` accepts pushes with the source's bearer token (decision D34; adapters whose platform cannot set a header, Cloudloop, take it as `?token=` and may restrict caller addresses) and hands the body to the adapter's `parse_webhook`. The ingest service runs the event connector of every enabled data source whose adapter has one and re-reads the data sources every minute. The file processing worker in the decoder service stores the frames of a raw log file or a browser sync the same way, on the built-in data source of the channel, with the device known up front (architecture 25, ADR 0017).

For every `InboundMessage`:

1. The external identity `(data source, external id)` is looked up or created with `device_id` null (or the device the caller named, for frames from a browser or a file). First and last seen and the event count are updated.
2. The source event is stored. Payloads up to 64 KB are JSONB; bigger ones go to MinIO and the row keeps the object key, size and SHA-256 (decision D32).
3. A compact processing trace is started with the steps "source event stored" and "identity resolved".
4. After the commit, `source_event.received` is published, or `needs_attention.created` when the identity is unknown or ignored. The source event status is `received`, `unassigned` or `ignored`.

## Decoder

`services/decoder/protect_decoder/pipeline.py`, one consumer group on `source_event.received`.

1. Driver selected from the device type. No driver, no device: `ApplicationError`, not retried.
2. Decoded by the driver into positions, measurements, states and events, each with its canonical time (ADR 0008). LoRaWAN uplinks reach the driver as the application frame on its port; frames from Web Bluetooth, raw log files and Iridium as the raw bytes with the channel, which the driver reads accordingly.
3. For every record the canonical key is computed. An existing row with the same key means a repeat delivery: a `source_deliveries` link is added and nothing else. Otherwise the project and entity are resolved at the record's time and the row is written with them.
4. Current state is updated in the same transaction: `device_current_state`, `connectivity_state`, and `entity_current_state` when the record is attributed to an entity.
5. The source event becomes `processed`, `duplicate` (only links added) or `failed` with an error code. The trace is finished. After the commit the domain events are published.

Metrics unknown to the registry are registered automatically with category `uncategorized` and a warning; administrators set the unit and category afterwards.

## Failures

A step that raises `ApplicationError` records the error on the trace and marks the source event failed. The bus dead-letters the message when the error is not retryable or the attempts are exhausted; retryable errors are re-delivered with a doubling backoff (ADR 0004). Dead letters are listed, retried and resolved under `/api/v1/attention/dead-letters`.

## Needs Attention

`/api/v1/attention/*` (server admin): unknown identities with counts and first and last seen, failed and unassigned source events, dead letters per topic, worker heartbeats and stale workers. Actions: create a device for an identity (with an optional project assignment from first seen), link an identity to an existing device, ignore, reprocess. Linking or creating puts the retained source events of that identity back on the bus, so nothing received while the device was unknown is lost.

## Late data

`ingested_at` sits next to `time` on every canonical row and the bus messages carry `age_seconds`, so rules and automations (phase 5) can tell a fresh observation from a backfilled one (architecture 25.8).
