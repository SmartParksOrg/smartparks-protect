# Dashboards

A dashboard is a shared grid per project (decision D86): tiles with a size (small, medium,
large) and an order, nothing free-form. Analyze, Dashboards.

Tiles:

| Tile | Shows |
| --- | --- |
| A metric: graph, table or number | Any metric the project measures (decision D309), see below |
| Saved view (chart) | A Data Explorer view saved in the project, drawn with the view's metrics, entities, range, bucket, aggregates and chart type; a link opens it in the explorer |
| Latest positions map | The project's entities at their latest position, clustered, on the chosen basemap |
| Open alerts | The newest open alerts with severity and age; each links to the alert |
| Recent events | The newest events; each links to the event |
| Entity status counts | Entities with a position, entities with open alerts, and counts per status |

Project admins create, edit and delete dashboards; viewers see them. A new dashboard starts
with the map, open alerts and recent events. Saved views come from the Data Explorer ("Save
this view"). Tiles refresh every thirty to sixty seconds.

## A metric as a tile

Edit, Add tile, "A metric: graph, table or number" opens the tile's settings; the settings
button on a metric tile opens them again.

| Setting | Meaning |
| --- | --- |
| Show as | A line graph, a bar graph, a table with a row per subject, or the latest value as a number |
| Metrics | Up to four metrics with values in the project in the last year, grouped by category; one for a number. Metrics of one unit read best together |
| A line or a row per | Entity or device |
| Entities or devices | Up to twenty by name. Empty takes the first of the project by name that fit the tile, and the tile says how many of how many it shows |
| Period | The last 24 hours, 7, 30 or 90 days, or the last year. The period ends now and moves with the clock |
| Value per step of time | For a graph: the mean, lowest, highest, median, sum, count, first or last value per step. The step follows the period |
| Title | Empty names the tile after its metrics |

- The **table** has a row per subject and metric: the latest value with its unit, when it was
  measured, and the mean, the lowest and the highest over the period.
- The **number** shows the latest value per subject, large, with its age; six at most, a table
  shows more.
- A speed is read in km/h, as everywhere.
- "open in Data Explorer" opens the same selection there, where the period can be any range
  and the rows behind a value can be read.

A tile reads the series the Data Explorer reads, so its bounds hold (twenty series for a
request, the finest step that fits) and a member with a scope sees on a tile what the scope
allows and nothing else.

## API

`/api/v1/projects/{project_id}/dashboards` (list, create, get, patch, delete) with `tiles` as
an ordered list of `{id, kind, size, title, saved_view_id, options}`. A tile of kind `metric`
carries its settings in `options`: `metrics`, `entity_ids`, `device_ids`, `group_by` (`entity`
or `device`), `range` (`24h`, `7d`, `30d`, `90d`, `1y`), `aggregate` and `display` (`line`,
`bar`, `table`, `number`). The server checks them when the dashboard is saved: a metric the
registry does not know or cannot aggregate, an entity of another project, subjects of the
other kind and a number with more than one metric are refused with a 422 that names the tile.
