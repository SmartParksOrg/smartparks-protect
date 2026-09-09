# Data explorer

The Data explorer answers two questions. The Records tab answers the simplest one first: everything an entity or a device produced between two moments, one row per moment with the position and every value of that moment (phase 20, decisions D142 to D146). The Analysis tab is the metric-first side (architecture 12): pick metrics, entities or devices and a time range, and get series, tables and statistics aggregated in the API. Neither tab ever asks the browser to hold more than it needs: every request is bounded (architecture 13.10), and a bound answers with a page or a coarser bucket, never with a refusal (decision D143).

## Records

`GET /api/v1/projects/{project_id}/records` and `GET /api/v1/projects/{project_id}/records/count`

| Parameter | Meaning |
| --- | --- |
| `entity_id`, `device_id` (repeatable, at least one) | Whose records. At most 500 of each. |
| `from`, `to` | The window on the effective device time, ISO 8601 with offset. Default: the last 30 days. |
| `include_invalid` | Also the rows curation marked invalid. |
| `limit`, `cursor` | Page size up to 1,000; the cursor of the previous page. |

A record is one moment of one device: the effective time, the position of that moment if there is one (latitude, longitude, altitude, speed, heading, accuracy, satellites, the curated fields), the measurements by metric key with their effective values, the state fields reported then, the entity and project the moment is attributed to, and the source event and trace behind it. The moments come from a union of the position and measurement times of the selection, newest first, paged on a `time, device` cursor; the count is a separate call for the progress bar. The reserved project id `all` works for server admins.

In the app, the Records tab opens with the object picker (entities and devices, several at once, a group as a shortcut), the period (the presets, a custom range, or since the device was assigned when one entity is chosen) and the timezone. The rows load page after page with a progress bar against the count and a Stop button, into a virtualized table that scrolls a year of a collar as one list. The columns are every metric and state field with data in the selection, all on, with a column picker kept per user. "Charts and map" adds a small chart per numeric column (click to enlarge) and the loaded track on a small map; the first look is the table alone. A row opens its source event. "Export" hands the selection to the export dialog (see [Export](export.md)), and "Analyse these" carries it into the Analysis tab.

Links land here from the rest of the app (decision D145): "All records" on the Data tab of an entity or a device, "Every record at this time" on the map's track point panel, and the Data button on the entity and device hits of the search palette. A link with a moment (`?at=`) opens the twelve hours around it with that row marked and scrolled into view.

## Analysis

### Series

`GET /api/v1/projects/{project_id}/analytics/series`

| Parameter | Meaning |
| --- | --- |
| `metric` (repeatable, required) | Metric keys from the registry. Only numeric and boolean metrics can be aggregated; booleans count as 0 and 1, so `mean` is the fraction true. |
| `entity_id`, `device_id` (repeatable) | Restrict to these entities or devices. |
| `data_source_id` | Restrict to rows that came through one data source. |
| `from`, `to` | Time range, ISO 8601 with offset. Default: the last 24 hours. |
| `bucket` | `1s`, `10s`, `1m`, `5m`, `15m`, `1h`, `6h`, `1d`, `7d`, or `all` for one bucket over the whole range (the statistics view). Empty means automatic. |
| `agg` (repeatable) | `mean`, `min`, `max`, `median`, `sum`, `count`, `first`, `last`. Default `mean`, `min`, `max`, `count`. |
| `group_by` | `entity` (default) or `device`. One series per metric and entity or device. |
| `layout` | `series` (default, arrays per series for charts), `long` (one row per bucket and series) or `wide` (one row per bucket, one column per series and aggregate, named `metric|owner|aggregate`). |

Automatic resolution picks the smallest bucket from the ladder that keeps a series at or under 5,000 points over the range. An explicit bucket that would exceed that bound is answered with the finest bucket that fits, and `notes` says so (decision D148). A request covers at most 20 series: the given entities or devices, else every entity of the project or every device assigned to it today; when more would exceed the bound the first that fit by name are answered, `owners_shown` and `owners_total` carry the numbers and `notes` says to pick entities or a group for the rest.

Empty buckets are not filled in. A chart that needs gaps shown draws them from the missing points.

### Drill-down

`GET /api/v1/projects/{project_id}/analytics/rows?metric=...&entity_id=...&from=...&to=...`

The normalized measurement rows behind a bucket, paginated with a cursor; the app loads the next page on "Load more" (decision D149). Each row carries `source_event_id` and `trace_id`, so the next step down is the source event detail (`/api/v1/source-events/{id}`) and the processing trace.

### Metrics with data

`GET /api/v1/projects/{project_id}/analytics/metrics?from=...&to=...`

The metrics that have measurements in the project within the range (default 30 days), with count, first and last time, label, unit and value type. The filter builder starts from this list.

### Saved views

`/api/v1/projects/{project_id}/analytics/saved-views` stores explorer configurations per project (decision D42). A view is a name plus a JSON document with a `schema_version`; the frontend owns the shape, and the document carries the tab (`mode`) so a saved view opens where it was made. Every member can create and list views; the creator or a project admin can change or delete one. Names are unique per project.

## Limits in one place

| Bound | Value | When it is reached |
| --- | --- | --- |
| Records per page | 1,000 | The next page follows; the app loads them in sequence with progress. |
| Entities or devices per records request | 500 each | 422. |
| Points per series | 5,000 | The finest bucket that fits answers, with a note. |
| Series per request | 20 | The first owners that fit by name answer, with a note and the counts. |
| Drill-down page | 500 rows | "Load more". |
| Direct export | 100,000 rows | 413; the app starts a job by itself. |
| Statement timeout of the API | 120 s | The query stops in the database as well (decision D147). |

These are constants in `shared/analytics.py`, `routers/records.py` and `shared/exports/__init__.py`. Continuous aggregates for hourly and daily buckets are added when the benchmark shows repeated expensive queries (`docs/operations/benchmarks.md`).
