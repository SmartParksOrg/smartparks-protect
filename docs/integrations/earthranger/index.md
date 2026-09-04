# EarthRanger (direct API)

The second way to reach EarthRanger next to [Gundi](../earthranger-gundi/index.md): the
site's own API (decision D84). Positions become observations of a generic sensor source,
events become EarthRanger events, and a corrected event is updated in place (architecture
28.10). Also the route to WildlifeNL, whose platform is EarthRanger based.

Built from the EarthRanger API primer and the public client library; live verification waits
for a site and a token.

## Setup

1. On the site create an OAuth2 access token (admin, OAuth2 provider) for a user with the
   right to post observations and events, and a source provider with key
   `smartparks_protect` (or another key given in the config).
2. Under Integrate, Integrations: New integration, connector EarthRanger (direct API). Config:
   `base_url` (`https://<site>.pamdas.org`), `provider_key`, `default_subject_type` and
   `subject_types` (entity type key to EarthRanger subject type), `default_event_type` and
   `event_types` (Smart Parks event type to the site's event type slug). Credentials: `token`.
3. On the site create the event type `smartparks_protect_event` with the `smartparks_protect_*`
   keys as its schema, or map every Smart Parks event type to an existing slug.
4. Send a test event from the integration page.

## Mapping

| Smart Parks Protect | EarthRanger |
| --- | --- |
| position of an entity | `POST /api/v1.0/sensors/generic/{provider_key}/status`: `manufacturer_id` (the entity id, so a track survives a collar change), `subject_name`, `subject_type`, `subject_subtype` (the entity type key), `recorded_at`, `location` (`lat`, `lon`), `additional` (device, data source, altitude, speed, heading, accuracy, satellites, curation version) |
| event | `POST /api/v1.0/activity/events`: `event_type`, `time`, `priority` (info 100, warning 200, critical 300), `title`, `location` (`latitude`, `longitude`), `event_details` with the `smartparks_protect_*` keys |
| corrected event (curation) | `PATCH /api/v1.0/activity/event/{id}` with the id the site returned for the earlier delivery |
| corrected position | a new observation; EarthRanger keeps both |

Positions without an entity are skipped: EarthRanger tracks subjects. Requests carry
`Authorization: Bearer <token>`; 5xx and 429 answers are retried on the delivery schedule,
4xx answers are permanent failures with the site's message.

## Troubleshooting

- `earthranger answered 401`: the token expired or lacks rights.
- `earthranger answered 400` on events: the event type slug does not exist on the site, or
  `event_details` does not match its schema.
- Observations arrive but no subject shows: the source provider key is unknown on the site.
