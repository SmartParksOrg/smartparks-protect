# Raw log files

A raw log file is a file retrieved from a device, usually the flash log of an OpenCollar read
over Bluetooth with the public BLE app or with this application. It is a managed asset
(architecture 25.6, decision D77): stored as uploaded, associated with the device, decoded
through the normal pipeline, and kept with its status and counts so a file uploaded twice or
a record that was already received over LoRaWAN is recognised and never duplicated.

## Format

One frame per line, base64 encoded (the BLE app's export) or hex; blank lines and lines
starting with `#` are skipped. A frame is what the device sends over Bluetooth:
`[port][msg_id][len][data]`, on port 29 the port byte followed by the stored records
`[port][msg_id][len][data][store timestamp]` (research 3.20). Unreadable lines are counted as
malformed frames and do not fail the file; a file without any frame fails with
`FILE_PARSE_FAILED`.

## Upload and decoding

On the device page, card "Log files", "Upload raw log". The API stores the file in the
`device-log-files` bucket (`MINIO_BUCKET_LOG_FILES`), refuses the same bytes for the same device
with 409 (SHA-256), records the row with status `queued` and publishes `log_file.uploaded`.
The decoder service is the file processing worker: it splits the file, stores every frame as a
source event on the built-in data source "Log file upload" (channel `log_file`, ingestion
`file_upload`, the device known up front, `file_uploaded_at` as provenance) and decodes it
through the same pipeline as a LoRaWAN uplink, in batches of `LOG_FILE_BATCH_SIZE` frames per
transaction. A browser sync is stored the same way under the source "Browser (WebBLE)"
(channel `webble`, ingestion `browser_sync`, `ble_synced_at`).

The row shows:

| Field | Meaning |
| --- | --- |
| status | `queued`, `processing`, `complete`, `failed` |
| frames | lines that held a frame, and how many were malformed |
| records found, new, known | canonical records decoded; new rows created; rows that existed already through another path (linked as repeat deliveries) |
| period | earliest and latest canonical device time in the file |
| firmware, decoder | the firmware version from a status record in the file, the decoder version used |
| trace | the file's processing trace; every frame has its own compact trace |

"Decode again" reprocesses the stored frames, for example after a decoder update; records
already known are recognised by their canonical keys. "Original" downloads the file byte for
byte. Files up to `LOG_FILE_MAX_BYTES` (64 MB by default) are accepted.

## Provenance

A position delivered over LoRaWAN, from a file and over WebBLE is one position with three
deliveries. On the device page, "deliveries" next to a position lists them with the channel
filter; the source event dialog shows the same for the events of a delivery (architecture
25.7). The Traffic page lists frames like any other source event.

## Late data

Records from a file can be years old. They are attributed to the project and entity of their
own time, rules evaluate them for completeness, and automations skip events older than their
maximum event age (architecture 25.8), so a historical backfill never raises stale alerts.

## API

- `POST /api/v1/devices/{device_id}/log-files` (multipart `file`), `POST .../log-files/ble-sync`
  (JSON frames in hex), `GET .../log-files`, `GET /api/v1/log-files/{id}`, `GET .../download`,
  `POST .../redecode`, `GET /api/v1/deliveries?canonical_type=position&canonical_id=`.
- Uploading, syncing and re-decoding need `devices:control` in the device's project.
