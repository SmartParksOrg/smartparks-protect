# ADR 0012: rules are versioned JSON documents with a stateful Python evaluator

Date: 2026-09-04. Status: accepted. Decision D9 in `PROJECT_PLAN.md`.

## Context

Architecture 15 asks for a rules engine that covers operational thresholds, geofences, stateful time windows and scientific detections, with versioning and testing against history. The options were an expression language, Python plugins per rule type, or a structured document.

## Decision

A rule is a JSON document validated by Pydantic models (`shared/rules/schema.py`): a trigger, a scope, a condition tree of typed leaves (`threshold`, `spatial`, `no_data`, `window`, with `all`, `any`, `not`), a duration, a cooldown and an event template. Documents are immutable versions; every event references the version that created it. A Python evaluator (`shared/rules/evaluator.py`) is pure apart from a data access protocol, so the rules service, the replay runner and the tests share it. Firing is edge-triggered with an optional cooldown reminder. Condition types the evaluator does not implement yet (`near`, `dwell`, `crossed`, `baseline`, `correlation`, `event_chain`) are reserved in the schema: a document can use them, a rule cannot be enabled with them.

The UI builds documents with forms; nested documents are edited as JSON. The JSON schema is served by the API for clients.

## Consequences

- Rules are testable by replaying canonical rows through the same evaluator with in-memory state, bounded in rows, events and schedule steps.
- New condition types are added as one leaf model and one evaluator branch; the schema version stays 1 while additions are backwards compatible.
- An expression language can be added later as one more leaf type without changing the storage model.
- Per-subject state lives in `rule_state` (active, holding since, last fired, inside geofences); it is small and survives restarts.
- Evaluation of one rule cannot fail the others: each rule runs in its own transaction, failures land on `rules.last_error` and a failed trace.
