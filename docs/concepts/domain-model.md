# Domain model

The concepts every screen and every service is built on. Table names are in `docs/architecture/data-model.md`.

## Device versus entity

A **device** is hardware: an OpenCollar, a gate sensor, a weather station. It exists at server level and has no project column. An **entity** is the real-world object you care about: an animal, a vehicle, a gate, a weather station as a place. Entities belong to a project and have a type (`entity_types`) that carries the icon and an attribute schema, so administrators add new kinds of entities without a code change.

The two are linked by **assignments** with a validity range:

- `device_project_assignments`: which project owned the device from when until when.
- `device_entity_assignments`: which entity the device monitored from when until when.

Both use a half-open range `[start, end)` and a database exclusion constraint, so a device can never be in two projects or on two entities at the same moment. A device may carry no assignment while it sits in inventory or repair.

## Attribution uses canonical time

Every canonical record (position, measurement, state, event) is attributed to the project and entity that were assigned to the device **at the device-origin time of the record**, not at the moment the record arrived. A raw log uploaded on 20 August that contains a GPS fix from 15 July belongs to the project that owned the device on 15 July. The single function that answers this is `shared.domain.assignments.resolve_attribution`. The resolved ids are stored on the record for fast queries; the assignment tables stay the source of truth for audits and recomputation.

## Handover

Moving a device to another project is a handover, not an edit: the current project assignment closes at the effective time, the entity assignment closes at the same time, a new project assignment opens. History is never rewritten. Members of the old project keep access to the records that were attributed to their project; they do not see the new project's data.

## Data sources and external identities

A **data source** is an external platform account: a ChirpStack instance, a KPN ThingPark account, a Traccar server. It carries the adapter that talks to it, its capabilities, encrypted credentials and deep link templates. A data source may be scoped to one or more projects, which is a configuration aid and never an assumption.

An **external identity** maps `(data source, external id)`, such as a DevEUI, to a device. Incoming data is resolved through this pair. An unknown identity is kept with its source events and shown in Needs Attention; it is never guessed.

## Four data levels

| Level | Where | What |
| --- | --- | --- |
| Raw | `source_events` | The inbound message exactly as received, immutable |
| Decoded | driver output | Provider or device specific interpretation |
| Normalized | `positions`, `measurements`, `device_state_history`, `events` | Canonical rows with stable schemas |
| Aggregated | server-side buckets | Time buckets and statistics for charts and dashboards |

Maps, charts, rules and exports use the normalized level. Provenance always leads back to the raw level.

## Processing traces

Every flow through the system (an inbound message, a command, an import, a delivery, an export) has a processing trace with ordered steps. A step that fails records a structured application error with a stable code, a severity, and whether a retry or an administrator can fix it. Routine successful telemetry writes compact traces.

## Roles and permissions

Three tiers: server admin (an account flag), project admin and project viewer (a membership row per project). Fine-grained permission keys such as `devices:control` are defined in code and mapped from the role. See [permissions](../administration/permissions.md).
