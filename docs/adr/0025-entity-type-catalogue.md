# 0025. Entity types with sub-types and a standard catalogue

Date: 2026-09-11

Status: accepted

## Context

An entity's kind is its entity type, a server-level catalogue that only server admins edit (ADR 0007, decision D6). New servers started with an empty catalogue and the dev server had two hand-made types, so a project could say "Animal" and nothing more specific, and every new site had to build its own list before the first entity. EarthRanger, which the icons now come from (decision D165), models the same thing as a subject type (wildlife, person, vehicle) with a subject subtype (elephant, ranger, 4x4), and its outbound connectors already send an entity type key as the subject subtype.

## Decision

Entity types get one level of sub-types on the same table: `entity_types.parent_id` names the type a row sits under, and an entity references the most specific row (decision D166). A migration seeds every server with the standard catalogue: six types (Wildlife, People, Vehicles, Infrastructure, Environmental sensors, Equipment) and a sub-type per vendored icon, about 240 rows with stable keys, so a new site starts complete; hand-made rows under the same key stay (decision D167). A project hides what it does not need in its settings (`hidden_entity_type_ids`); hiding a type takes its sub-types along, and the entity dialog, the bulk dialogs and the settings page read that set (decision D168). The entity dialog offers the type, then a searchable sub-type with its icon, and an optional icon override for one entity (decision D169). The EarthRanger connectors send the mapped sub-type, else the mapped type, else the type's own key as the subject type and the sub-type as the subject subtype.

## Alternatives considered

- A separate sub-type table: every reader of the entity type (lists, map, exports, integrations, MCP) would learn a second column, for the same information.
- A button that adds the catalogue on request: one more step for every new site, and the seed is code either way.
- Disabling per server instead of per project: one server with parks on two continents could not serve both.
- Letting project admins create types: a permission change with no need yet; a project picks from the catalogue and hides the rest.

## Consequences

A new server offers Elephant, Ranger, 4x4 and Gate on day one, and a project trims the list once. Integrations that map entity type keys to EarthRanger subject types keep working and gain a sensible default for the catalogue's keys. The catalogue grows through the icon import and a migration per addition; a downgrade drops the parent column and leaves the rows as plain types. Sub-types stay one level deep until a real need for more appears.
