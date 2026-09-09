# Data explorer

Explore is one selection looked at three ways (phase 21, decisions D150 to D155). A person picks entities and devices, a period and a timezone in the strip at the top, and the canvas below shows everything they produced as a table, a chart or a map, switched with one control. The strip folds to one summary line (on a phone it starts folded once a selection exists), so the canvas gets the room. The rows load page after page whatever the mode, and under the chart or the map they sit in a drawer at the bottom, pulled up by its handle to the height a person likes. One marked moment links the views: hovering a point on the chart, a row in the drawer or a point on the map marks the same moment everywhere, and a click pins it into the link (`?at=`). Every request is bounded (architecture 13.10), and a bound answers with a page or a coarser bucket, never with a refusal (decision D143).

## The records read

`GET /api/v1/projects/{project_id}/records` and `GET /api/v1/projects/{project_id}/records/count`

| Parameter | Meaning |
| --- | --- |
| `entity_id`, `device_id` (repeatable, at least one) | Whose records. At most 500 of each. |
| `from`, `to` | The window on the effective device time, ISO 8601 with offset. Default: the last 30 days. |
| `include_invalid` | Also the rows curation marked invalid. |
| `limit`, `cursor` | Page size up to 1,000; the cursor of the previous page. |

A record is one moment of one device: the effective time, the position of that moment if there is one (latitude, longitude, altitude, speed, heading, accuracy, satellites, the curated fields), the measurements by metric key with their effective values, the state fields reported then, the entity and project the moment is attributed to, and the source event and trace behind it. The moments come from a union of the position and measurement times of the selection, newest first, paged on a `time, device` cursor; the count is a separate call for the progress bar. The reserved project id `all` works for server admins.

## The three modes

**Table.** The virtualized table of the loaded rows, one row per moment, that scrolls a year of a collar as one list. The columns are every metric and state field with data in the selection, all on, with a column picker kept per user. A row opens its source event.

**Chart.** One graph with a thin line per metric and entity or device over a shared time axis, so two collars compare on one canvas. The metrics on the chart are the loaded columns with a picker (the first four numeric ones by default). The axes follow the units: the first metric's unit takes the left axis, every other unit the right one, so a temperature sits next to a voltage without a setting. Chips above the graph toggle lines, a crosshair follows the pointer with one card listing every line's value at that moment, and every moment carries a small point (a line above a thousand points shows them under the pointer only). The kind switches between line, scatter (one metric against another, per owner), bar, histogram (of the first metric) and state timeline. Above 50,000 records the chart draws from the aggregate series read (below) with the finest bucket that fits and says so; the drawer keeps loading the rows.

**Map.** The tracks of the selection over the period with the project's features, and a time slider that moves the marked moment along the tracks, the point of every track at that moment ringed. Above 50,000 records the tracks come from the track read, decimated to 5,000 points each.

"Export" hands the selection to the export dialog (see [Export](export.md)). Saved views keep the selection, the period, the mode and the chart (decision D42); a dashboard's saved view tile opens the explorer on it, and views saved with the Analysis tab of v2.4.0 open in chart mode.

Links land here from the rest of the app (decision D145): "All records" on the Data tab of an entity or a device, "Every record at this time" on the live map's track point panel, and the Data button on the entity and device hits of the search palette. A link with a moment opens the twelve hours around it with that row marked and scrolled into view.

## The aggregate reads

The chart above the canvas bound, the dashboards' saved view tiles and the aggregates export read these.

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

The normalized measurement rows behind a bucket, paginated with a cursor. In the app the rows behind the chart are the drawer; this read serves other clients. Each row carries `source_event_id` and `trace_id`, so the next step down is the source event detail (`/api/v1/source-events/{id}`) and the processing trace.

### Metrics with data

`GET /api/v1/projects/{project_id}/analytics/metrics?from=...&to=...`

The metrics that have measurements in the project within the range (default 30 days), with count, first and last time, label, unit and value type. The filter builder starts from this list.

### Saved views

`/api/v1/projects/{project_id}/analytics/saved-views` stores explorer configurations per project (decision D42). A view is a name plus a JSON document with a `schema_version`; the frontend owns the shape, and the document carries the tab (`mode`) so a saved view opens where it was made. Every member can create and list views; the creator or a project admin can change or delete one. Names are unique per project.

## Limits in one place

| Bound | Value | When it is reached |
| --- | --- | --- |
| Records per page | 1,000 | The next page follows; the app loads them in sequence with progress. |
| Rows drawn on the canvas | 50,000 | The chart reads buckets and the map the decimated tracks, with a note. |
| Entities or devices per records request | 500 each | 422. |
| Points per series | 5,000 | The finest bucket that fits answers, with a note. |
| Series per request | 20 | The first owners that fit by name answer, with a note and the counts. |
| Drill-down page | 500 rows | "Load more". |
| Direct export | 100,000 rows | 413; the app starts a job by itself. |
| Statement timeout of the API | 120 s | The query stops in the database as well (decision D147). |

These are constants in `shared/analytics.py`, `routers/records.py` and `shared/exports/__init__.py`. Continuous aggregates for hourly and daily buckets are added when the benchmark shows repeated expensive queries (`docs/operations/benchmarks.md`).
