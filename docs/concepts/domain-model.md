# Domain model

The concepts every screen and every service is built on. Table names are in `docs/architecture/data-model.md`.

## Device versus entity

A **device** is hardware: an OpenCollar, a gate sensor, a weather station. It exists at server level and has no project column. An **entity** is the real-world object you care about: an animal, a vehicle, a gate, a weather station as a place. Entities belong to a project and have a type (`entity_types`) that carries the icon and an attribute schema, so administrators add new kinds of entities without a code change. Types hold sub-types one level deep (ADR 0025): Wildlife holds Elephant, Vehicles holds 4x4, and an entity references the most specific row, so the icon and the EarthRanger subject subtype follow. Every server is seeded with the standard catalogue of six types and a sub-type per icon; a project hides what it does not need under Project admin, Settings, and an entity may override its type's icon.

The two are linked by **assignments** with a validity range:

- `device_project_assignments`: which project owned the device from when until when.
- `device_entity_assignments`: which entity the device monitored from when until when.

Both use a half-open range `[start, end)` and a database exclusion constraint, so a device can never be in two projects or on two entities at the same moment. A device may carry no assignment while it sits in inventory or repair.

## Attribution uses canonical time

Every canonical record (position, measurement, state, event) is attributed to the project and entity that were assigned to the device **at the device-origin time of the record**, not at the moment the record arrived. A raw log uploaded on 20 August that contains a GPS fix from 15 July belongs to the project that owned the device on 15 July. The single function that answers this is `shared.domain.assignments.resolve_attribution`. The resolved ids are stored on the record for fast queries; the assignment tables stay the source of truth for audits and recomputation.

### Assignment dates and records before an assignment

An assignment starts at a moment you choose. The dialogs offer the moments the system knows: the device's first data (its earliest record, sighting or raw log), the day it joined the project, now, or a date; a date means the start of that day in the project's timezone. Records that arrived before the device's earliest assignment have no project or entity and stay invisible to the project (a raw log downloaded weeks after the collar went out is the usual case). The device page says how many such records exist and offers to move the assignment start back to the first data; that rewrites the attribution of the records in between and recomputes the current state. The same repair exists for entity assignments once the project assignment covers the period. Creating an assignment, or handing a device over, attributes the records already inside the new range the same way, so choosing "since the device's first data" at creation needs no repair afterwards.

The entity is where most people start, so the entity page carries the device side too: the device tracking it today with its health, the history of every device that tracked it, "Assign device" for project admins (the candidates are the project's devices that track nothing at that moment, `GET /devices?project_id=&unassigned=true`) with the same start choices, and "Release device", which ends the current assignment now. A device already on another entity is released there first; the platform never moves a device between entities silently.

## Groups

Groups are folders of entities inside a project, nested as deep as needed (decision D98, ADR 0020): a region, a herd inside it, a family inside that. An entity sits in at most one group; a device belongs to the group of the entity it tracks today, so the devices list filters by group as the entities list does, and filtering by a group includes everything below it. Project admins organize them under Project admin, Groups: the tree on the left, the entities on the right with search and a type filter, a selection moved with "Move to" (which can create the target group on the spot) or dragged onto a group; the Entities list moves a selection the same way. A group has a colour for the map; the entity dialog and the bulk onboarding from Needs attention place entities in a group. Deleting a group leaves its entities in place and ungrouped. On the live map the layers panel has five tabs, Entities, Devices (the device layer, off by default, with or without an entity and a dashed track), Features, Events and Coverage (the gateways with a position, the heard positions and the network locations). Entities lists the groups however deep with the number of entities on the map, each entity with its icon and how long ago it was seen, a search box, a sort by name or last update and a grouped or flat view; every group and entity shows or hides, "only" keeps one group, one toggle per tab shows or hides everything on it beside Fold all, and a row's locate button flies to it. Features and Events do the same per feature type and feature, and per event type, for the last 24 hours; Coverage shows the gateways with a position, the heard positions and the network locations; a track button next to an entity shows its track over the length set on the Tracks card (24 hours by default), the same button the object's panel carries, and a heatmap button beside it does the same for a heatmap; the choices are kept per user and project (`users.preferences`), so another browser opens the same view.

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

## Positions and where they come from

A position has a record type. The device's own fixes carry the driver's type (`gnss` for an
OpenCollar). A location a network provides about the device, an Iridium session's estimate or
a LoRaWAN network's geolocation, is a position of type `network` with the network's radius as
its accuracy (ADR 0024). Every map, chart, list, rule and export shows the device's own fixes
unless a person asks for the network's locations, and the current position of an entity or a
device follows its location source setting: the device's fixes, the network's locations, or
the device with the network standing in after a period without a fix. Network locations draw
on the live map's Coverage tab as circles of their radius.

