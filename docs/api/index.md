# API

The complete reference is the OpenAPI schema the server publishes at `/api/docs` (Swagger UI) and `/api/openapi.json`; the frontend's `services/frontend/openapi.json` and `schema.d.ts` are the same schema as the generator writes it, checked in CI. This page collects the conventions the schema cannot express.

- Scope: project resources live under `/api/v1/projects/{id}/…`; a server admin may use the reserved id `all` for the read-only all-projects scope (ADR 0022). Server-level resources live under `/api/v1/admin/…` and need a server admin.
- Pagination: list endpoints take `limit` and return `items` with a `next_cursor` to pass back as `cursor`; time-series lists order newest first and cursor on the time of the last item.
- Deep links the frontend understands: `?tab=` on the entity and device pages, `?event=` on the map and the events pages, `?entity=`, `?device=`, `?gateway=`, `?feature=`, `?tracks=`, `?heat=`, `?layers=1` and `?feed=1` on the live map.
- The WebSocket stream at `/api/v1/projects/{id}/stream` carries the bus topics for that project as JSON frames with a `topic` field: `position.created`, `event.created`, `alert.created` and the others of `shared/bus.py`.
- Every write goes through the same policy as the interface (ADR 0019); AI clients use the MCP server (ADR 0015).
- Schema versioning of messages and payloads follows ADR 0006.
