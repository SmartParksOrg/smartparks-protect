# 0006. Schema versioning for bus messages, webhook payloads and API responses

Date: 2026-09-03

Status: accepted

## Context

Architecture section 28.6 asks for versioned event and webhook schemas. Workers are deployed together but restart at different moments, outbound webhooks are consumed by systems the project does not control, and the API is consumed by the frontend, MCP clients and scripts.

## Decision

- Bus messages carry `schema_version` (integer) in their envelope. A worker rejects a version it does not know and the message goes to the dead-letter stream with `SCHEMA_VERSION_UNSUPPORTED`. Versions only go up; a field is never removed within a version.
- Outbound webhook payloads carry `schema_version` and `event_type` at the top level. Breaking changes create a new version; the old one stays supported for at least two releases and the changelog says when it ends.
- The REST API is versioned by path prefix, `/api/v1/...`, starting in phase 1. Response fields are added, never renamed or removed, within a version. OpenAPI is generated from the code and checked in CI for freshness.

## Alternatives considered

- No versioning until it hurts: the first breaking change then costs a coordinated deployment across every consumer.
- Header-based API versioning: harder to see in logs and browser tools.

## Consequences

Every message and payload model has a version field from the start. Changelog entries must call out schema changes.
