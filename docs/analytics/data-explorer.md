# Data Explorer

The Data Explorer is the analysis side of the platform (architecture 12): pick a project, entities or devices, metrics and a time range, and get tables, charts and statistics. All the work happens in the API. The browser never receives more than a few thousand points per series (architecture 13.5, decision D41).

## Series

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

Automatic resolution picks the smallest bucket from the ladder that keeps a series at or under 5,000 points over the range. An explicit bucket that would exceed that bound is refused with 422, and so is a request that could produce more than 20 series. When no entity or device filter is given the number of entities in the project decides whether the request is allowed; pick entities when the project is large.

Empty buckets are not filled in. A chart that needs gaps shown draws them from the missing points.

## Drill-down

`GET /api/v1/projects/{project_id}/analytics/rows?metric=...&entity_id=...&from=...&to=...`

The normalized measurement rows behind a bucket, paginated. Each row carries `source_event_id` and `trace_id`, so the next step down is the source event detail (`/api/v1/source-events/{id}`) and the processing trace.

## Metrics with data

`GET /api/v1/projects/{project_id}/analytics/metrics?from=...&to=...`

The metrics that have measurements in the project within the range (default 30 days), with count, first and last time, label, unit and value type. The filter builder starts from this list.

## Saved views

`/api/v1/projects/{project_id}/analytics/saved-views` stores Data Explorer configurations per project (decision D42). A view is a name plus a JSON document with a `schema_version`; the frontend owns the shape. Every member can create and list views; the creator or a project admin can change or delete one. Names are unique per project.

## Limits in one place

| Bound | Value |
| --- | --- |
| Points per series | 5,000 |
| Series per request | 20 |
| Drill-down page | 500 rows |
| Metrics listing range | 30 days by default |

These are constants in `shared/analytics.py`. Continuous aggregates for hourly and daily buckets are added when the benchmark shows repeated expensive queries (`docs/operations/benchmarks.md`).
