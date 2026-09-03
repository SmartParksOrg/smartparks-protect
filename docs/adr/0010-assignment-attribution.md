# 0010. Assignment attribution stored on canonical rows

Date: 2026-09-03

Status: accepted (decision D27)

## Context

Architecture 32 asks whether normalized records should persist `entity_id` at processing time in addition to the temporal assignment. Historical queries by project and entity are the most common queries on the largest tables. Resolving assignments with a range join on every query is expensive at 250 million positions.

## Decision

Canonical rows carry `project_id` and `entity_id` resolved at their canonical time by `shared.domain.assignments.resolve_attribution`, next to `device_id`. The assignment tables stay the source of truth. A change to an assignment does not rewrite history; a timestamp correction in phase 12 reruns the resolution and reports what would move before it is applied.

## Alternatives considered

- Range join at query time: correct but slow, and every query author must remember it.
- Only `entity_id`, not `project_id`: project access control needs the project on every row.

## Consequences

Fast per-project and per-entity queries with plain indexes. Attribution is computed once, in one function, and stored. Backfilled assignments (a device assigned after its data arrived) require a reprocessing job that re-resolves affected rows; Needs Attention in phase 2 triggers it.
