# Outbound integrations

An integration forwards a project's canonical objects to one target: positions, events and,
where the target can take them, measurements. Targets are connectors in
`shared/integrations/connectors/`, registered in `shared/integrations/registry.py`:

| Connector | Sends | Notes |
| --- | --- | --- |
| EarthRanger via Gundi | positions as observations, events as events | see [EarthRanger via Gundi](earthranger-gundi/index.md) |
| Webhook | positions, events, measurements | JSON POST, signed with a secret |
| MQTT | positions, events, measurements | one message per object on a templated topic |

The Integrate section of a project lists its integrations and the delivery log. Creating one
takes the connector, its configuration and credentials (encrypted at rest, never shown again),
what to forward, and filters: entities, event types, minimum severity, metric keys, and the
freshness bound for live objects.

## Deliveries

Every matching object becomes one delivery row (ADR 0014): status queued, sent, failed or
skipped; attempts; the rendered request and the target's response; the target's id for the
object when it returns one; a processing trace. The row is unique per (integration, object type,
object id, object version), so an object reaches a target once however often it is replayed,
re-delivered or backfilled.

The integration service consumes `position.created`, `event.created` and
`measurement.created`, writes rows and acknowledges. A separate loop attempts due rows every
two seconds. A transient failure (network error, 5xx, 429) schedules the next attempt with
exponential backoff, 30 s doubling to a cap of 6 h, up to 30 attempts; a permanent failure
(4xx, an object the target cannot represent) ends the delivery as failed. Failed deliveries can
be retried from the delivery log; the retry is immediate and keeps the attempt count.

Live objects older than the integration's freshness bound (default one day) are not forwarded;
a stale event is recorded as skipped so the log says why. Backfill ignores the bound.

An event without a point of its own is sent with the entity's last known position and a note
saying so; an event without any location is skipped for targets that need one.

## Backfill

Backfill queues every matching object in a date range that has no delivery yet, in batches of
a thousand, and shows progress on the integration (scanned, queued, status). A backfill can be
repeated at any time; existing deliveries are skipped. The range is bounded to 400 days.

## Test

Test sends one visible test object to the target: a test event on the EarthRanger map, a
`type: test` POST for a webhook, a message on `<prefix>/test` for MQTT. The coordinates default
to the latest entity position of the project.

## Webhook payload

```json
{
  "type": "position",
  "version": 1,
  "object": {"id": "42", "time": "2026-09-04T09:15:00+00:00", "latitude": -24.9, "longitude": 31.5, "speed_mps": 1.5},
  "project": {"id": "…", "name": "Demo park", "slug": "demo-park"},
  "entity": {"id": "…", "name": "Rhino 14", "type": "rhino"},
  "device": {"id": "…", "name": "SP05", "serial_number": null},
  "data_source": "Local ChirpStack",
  "link": "https://protect.example.org/projects/…/devices/…",
  "delivery_id": "…"
}
```

Headers: `X-Protect-Delivery` (the delivery id, for deduplication on the receiver's side) and,
when a secret is stored, `X-Protect-Signature: sha256=<HMAC-SHA256 of the body>`. Extra
request headers can be configured, for example an `Authorization` header.

## MQTT

Config: `host`, `port`, `tls`, `qos` (default 1), `topic_prefix` (default
`smartparks-protect`) and `topic_template` (default
`{prefix}/{project_slug}/{object_type}/{subject}`, where subject is the entity id or, without
an entity, the device id). The message body is the webhook payload. Messages are not retained.

## Adding a connector

A connector is a class with `key`, `label`, `description`, `supports` (object types),
`config_schema`, `config_example`, `credentials_schema`, `setup_hint`, and three methods:
`render(integration, item)` (pure, returns the payload), `deliver(integration, item, payload)`
(sends it, returns `DeliveryResult`), and `test(integration, location)`. Raise
`TransientFailure`, `PermanentFailure` or `Skipped` from `shared.integrations.base`. Register
it in `CONNECTORS`; the frontend learns about it from `GET /projects/{id}/integrations/connectors`.
