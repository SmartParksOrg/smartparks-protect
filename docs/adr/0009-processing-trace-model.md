# 0009. Processing trace model

Date: 2026-09-03

Status: accepted

## Context

Architecture 26 asks that an administrator can see where a message, command, import or delivery stopped without shell access, that errors have stable codes, and that tracing routine telemetry stays compact at 250 events per second.

## Decision

Three tables: `processing_traces` (one per flow: root object, status, trace class, start and end, optional project, device and data source, an actor for commands and MCP calls), `processing_steps` (ordered steps with component, operation, status, timing, input and output references, retry count and error id) and `application_errors` (error code from the `ErrorCode` enum, severity, retryable, user-actionable, component, message, technical context).

`shared.trace.Tracer` is the only way to write them. A step is an async context manager. An `ApplicationError` raised inside a step is recorded and re-raised; any other exception is recorded as `INTERNAL_ERROR` and re-raised, so bugs are not swallowed. Compact traces keep successful steps as JSON on the trace row and write step rows only for failures. The trace class (routine, failed, command, audit) drives retention per class in phase 10.

## Alternatives considered

- Log lines only: not queryable per object, not linkable from the UI.
- OpenTelemetry spans as the application trace: too low level for administrators and retained too briefly; OpenTelemetry is evaluated in phase 10 as the technical layer, correlated by trace id.
- One step row per routine step: at the design envelope that is more rows than the telemetry itself.

## Consequences

Every worker and endpoint that moves data creates a tracer. Errors need a code from the enum, so new failure modes extend the enum in a migration. Trace tables are regular tables now; if the benchmark in phase 4 shows they dominate, they become hypertables in a later migration.
