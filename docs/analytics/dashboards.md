# Dashboards

A dashboard is a shared grid per project (decision D86): tiles with a size (small, medium,
large) and an order, nothing free-form. Analyze, Dashboards.

Tiles:

| Tile | Shows |
| --- | --- |
| Saved view (chart) | A Data Explorer view saved in the project, drawn with the view's metrics, entities, range, bucket, aggregates and chart type; a link opens it in the explorer |
| Latest positions map | The project's entities at their latest position, clustered, on the chosen basemap |
| Open alerts | The newest open alerts with severity and age; each links to the alert |
| Recent events | The newest events; each links to the event |
| Entity status counts | Entities with a position, entities with open alerts, and counts per status |

Project admins create, edit and delete dashboards; viewers see them. A new dashboard starts
with the map, open alerts and recent events. Saved views come from the Data Explorer ("Save
this view"). Tiles refresh every thirty to sixty seconds.

API: `/api/v1/projects/{project_id}/dashboards` (list, create, get, patch, delete) with
`tiles` as an ordered list of `{id, kind, size, title, saved_view_id, options}`.
