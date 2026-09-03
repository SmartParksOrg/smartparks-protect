# Export

Export is a backend capability (architecture 14): an export is reproducible from explicit parameters, generated on the server, and never asks the browser to hold the data. Small exports download at once, large ones run as jobs in the export service (decision D39) and land in MinIO.

## Parameters

Both paths take the same parameters, as a JSON body for jobs and as query parameters for direct downloads.

| Parameter | Meaning |
| --- | --- |
| `dataset` | `positions`, `measurements` (normalized), `source_events` (raw inbound messages with payload) or `aggregates` (the Data Explorer series). |
| `format` | `csv`, `xlsx`, `json`; positions also `geojson` and `gpx`. |
| `time_from`, `time_to` | Required, with offset. Source events are selected on `ingested_at`, everything else on the device time. |
| `entity_ids`, `device_ids`, `metric_keys`, `data_source_id` | Filters. Source events are per device and refuse `entity_ids`. |
| `timezone` | IANA name, default `UTC`. Times in the file are written in this zone with their offset. |
| `include_names` | Adds entity, device and metric names and units as columns (default on). |
| `bucket`, `aggregates`, `group_by`, `layout` | Aggregates only; same meaning as in the Data Explorer, layout `long` or `wide`. |

## Direct download

`GET /api/v1/projects/{project_id}/exports/direct?dataset=positions&format=gpx&time_from=...&time_to=...`

Streams the file. The row count is checked first; above 100,000 rows the answer is 413 with the advice to create a job (architecture 13.8). XLSX is assembled in a temporary file because the format is complete only at the end; every other format streams as it is written.

## Jobs

| Call | Purpose |
| --- | --- |
| `POST /api/v1/projects/{project_id}/exports` | Queue a job (permission `exports:create`). Returns the job with status `queued`. |
| `GET .../exports` | List jobs of the project. |
| `GET .../exports/{job_id}` | Status, progress in rows, and when done: row count, size, SHA-256 and metadata. |
| `GET .../exports/{job_id}/download` | The file, streamed from MinIO through the API. 409 while the job is not done. |
| `POST .../exports/{job_id}/reproduce` | A new job with the same parameters, linked through `source_job_id`. |

The export service consumes `export.requested`, reads rows with a server-side cursor in batches of 2,000, writes them through a streaming writer into a temporary file, uploads the file to the `exports` bucket and records size and hash. Progress is written every 10,000 rows. A failure is stored on the job with its message; it is not retried, the same parameters would fail again.

Files are kept for seven days (`expires_at`). Cleanup of expired objects is a later operations task.

## Formats

- **CSV**: UTF-8, header row, nested values (attributes, payloads) as JSON strings.
- **XLSX**: one sheet `data`; when a sheet would pass the Excel limit of 1,048,576 rows the next rows continue on `data_2`, `data_3` and so on. Nothing is cut off silently (decision D40).
- **JSON**: `{"metadata": {...}, "columns": [...], "rows": [...]}`.
- **GeoJSON**: a FeatureCollection of points, the other columns as properties.
- **GPX**: one track per entity (per device when unassigned), points in time order with elevation and UTC time.

## Reproducibility

Every job stores its parameters and, when done, a metadata snapshot: generator version, timezone, the metric definitions with units, row count, size and SHA-256. JSON exports carry the same metadata inside the file. Reproducing a job later can give a different result when late data arrived; the two jobs' metadata show the difference (architecture 28.13).
