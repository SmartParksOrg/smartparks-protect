# 0020. Entity groups as nested folders

Date: 2026-09-06

Status: accepted, amended on 2026-09-06 (any depth instead of two levels)

## Context

A project with eighty collars needs a way to say "the northern herd", "the ranger team" or
"the eastern region" without reading names. The first live days asked for it three times: the
lists want a filter, the map wants to show and hide parts, and bulk onboarding wants to put
new animals somewhere. Groups and subgroups were requested for entities and for devices.

Two shapes were possible: folders (every entity in at most one group, groups nested) or tags
(any entity in any number of labelled sets). Folders are what people draw on a whiteboard and
what a map layer panel can render as a tree with counts; tags answer ad hoc questions better
but make "hide the north" ambiguous when an entity carries two tags.

## Decision

Groups are folders per project, nested as deep as the project needs (decision D98, amended
the same day after Tim tried the two-level version against EarthRanger's subject groups):
`entity_groups` with a name, an optional parent, a sort order, a colour for the map and an
optional icon and description. The only rule is that the tree stays a tree: a group cannot
move into itself or below itself. Filters and deletions walk the tree with a recursive query. An entity sits in at most one group (`entities.group_id`,
set to null when the group goes). Devices are not grouped on their own: a device belongs to
the group of the entity it tracks today, which every device read carries, so the devices list
filters by group without a second model. Filtering by a parent includes its subgroups. Bulk
onboarding can put its new entities into a group. The live map reads the group of each
feature and shows or hides per group.

## Alternatives considered

- Tags: kept possible for later, on top of folders, for ad hoc filtering; not first because
  the map panel and the counts need one place per entity.
- Two levels only: the first version. Simpler consumers, but the first live use asked for
  a region holding a herd holding a family, which is how EarthRanger's groups nest too.
- Grouping devices directly: a collar moves between animals; a device group would drift
  from the animal group it was meant to mirror.

## Consequences

Lists and the map gain one filter dimension that is cheap to query (one indexed column).
Deleting a group ungroups its entities and removes its subgroups, recorded in the audit
log with the counts. Tags later mean a new decision, not a rewrite: the column and the
table stay.
