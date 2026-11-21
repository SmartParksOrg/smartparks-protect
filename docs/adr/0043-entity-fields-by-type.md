# 0043. An entity's fields are defined by its type, as an ordered list

Date: 2026-11-21

Status: accepted; builds on 0007 and 0025

## Context

People want to say more about an entity than its name: the frequency of a VHF tag on an animal that also wears a tracker, the ear tag number of a grazing animal, the licence plate of a vehicle, the call sign of a ranger. What applies depends on what the entity is.

The tables had the room since the first migration (decision D6, ADR 0007): `entities.attributes` is a JSONB document and `entity_types.attribute_schema` a JSONB column commented "JSON schema". Neither was used. The API stored any document unchecked, no page showed it, every seeded type held `{}`, and three readers looked for loose keys that could only be set through the API: the grazing weighting, the Movebank export and the MCP answer. On the dev server on 2026-11-21 none of 289 entities had a value and no type had a schema, so nothing existing constrains the shape.

## Decision

A type defines fields and a sub-type inherits those of the type it sits under (D399). A field is one entry of an ordered list (D400): a key, a label, one of six kinds (text, number, integer, date, choice, yes or no) and, where they apply, a unit, choices, a minimum and maximum, a help text, a mark for the live map's panel and a mark for the search.

The standard fields live in code, `STANDARD_FIELDS` in `shared/catalog/entity_fields.py`, by the key of the type. The column `attribute_schema` holds only what a server admin added, as `{"fields": [...]}`. A type's fields are, in order: its parent's standard fields, its parent's own, its standard fields, its own. An own field never takes a key the type has from elsewhere.

Values are checked on write for the keys the entity's type defines and for nothing else (D401). A key no field defines is stored as it came. No field is required. An empty value removes the key. An entity that changes type keeps every value. The document holds at most 8 KB and a type at most 64 own fields.

## Alternatives considered

- JSON Schema in `attribute_schema`, as the column's comment said: a standard, but JSONB does not keep the order of an object's keys, so `properties` loses the order of the form; and a form built from any schema is far more than six kinds need.
- The standard fields seeded into the rows by a migration: every change of the standard set would be a migration, and an admin could edit a key that the search and the exports rely on.
- Fields per project: no key would be the same across projects, so no export or analysis could rely on one. An own field on a type covers a site's special case for now.
- A table per kind of entity (animals, vehicles): rejected in ADR 0007 until a kind needs heavy relational queries; a plate and a tag number do not.
- A VHF tag as a device with its own assignment: it keeps the history of a replaced tag, but a device that never reports is heavy for "which frequency for this animal" (D402).
- Required fields: entities are made in bulk and on the spot from an assignment with a name alone.

## Consequences

The same keys exist on every server, so the search, the Movebank export and the grazing weighting can name them. A change of the standard set is a code change without a migration; removing a standard field leaves its values in the documents, where they read as unknown keys. An unknown key is never refused, so existing API clients keep working, and a typing mistake in a key through the API is stored without complaint and shows under "Other". A value's history is the audit log alone; a field whose value over time matters (a weight per season) needs another model. Fields on device types can reuse the same definitions when somebody needs them.
