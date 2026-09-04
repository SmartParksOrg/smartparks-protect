# EarthRanger via Gundi

Smart Parks Protect sends positions and events to EarthRanger through Gundi (decision D15),
the same route AddaxAI Connect uses. Gundi retries delivery to the site; Smart Parks Protect
retries delivery to Gundi (ADR 0014).

Built from the Gundi Sensors API v2 documentation
(https://support.earthranger.com/developer_docs/gundi-api). Live verification waits for a
Gundi connection and an EarthRanger test site.

## Setup

1. In the Gundi portal, create a connection from a source of your Smart Parks Protect server to
   the EarthRanger site and copy the connection's API key.
2. On the EarthRanger site, create the event type `smartparks_protect_event` (or map every
   Smart Parks event type to an existing slug) with a schema whose keys are the
   `smartparks_protect_*` fields below.
3. In Protect, Integrate, Integrations: New integration, target EarthRanger via Gundi, paste
   the API key as `api_key`, map entity types to EarthRanger subject types, choose what to
   forward, and Test. The test event appears on the EarthRanger map.

## Mapping

Positions become observations: `POST /observations/` with

| Gundi field | Value |
| --- | --- |
| `source` | the Smart Parks entity id (decision D62) |
| `source_name` | the entity name |
| `subject_type` | `subject_types[entity type key]`, else `default_subject_type` (default `wildlife`) |
| `recorded_at` | the canonical position time with offset |
| `location` | `{lat, lon}` |
| `additional` | device id and name, data source, project, entity type, altitude, speed, heading, accuracy, satellites |

Using the entity as the source keeps the EarthRanger track continuous when a collar is
replaced. Positions without an entity are skipped.

Events become EarthRanger events: `POST /events/` with `source` (entity id), `title`,
`event_type` (`event_types[Smart Parks type]`, else `default_event_type`), `recorded_at`,
`location` and `event_details`:

| Key | Value |
| --- | --- |
| `smartparks_protect_event_type` | the Smart Parks event type, for example `GEOFENCE_EXIT` |
| `smartparks_protect_severity` | info, warning, critical |
| `smartparks_protect_entity`, `_device`, `_project` | names |
| `smartparks_protect_description` | the event description when present |
| `smartparks_protect_event_id` | the Smart Parks event id |
| `smartparks_protect_link` | the event in Protect |
| `smartparks_protect_location_note` | present when the entity's last position stood in for a missing point |

Measurements are not sent to Gundi.

## Troubleshooting

- Test fails with 401 or 403: the API key is wrong or the connection is disabled in Gundi.
- Events arrive but show no details: the event type on the site lacks the schema keys.
- Deliveries queued with "gundi answered 5xx": Gundi is down; they retry on the schedule.
- Events skipped "has no location": the event has no point and the entity no known position.
