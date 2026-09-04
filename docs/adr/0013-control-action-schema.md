# ADR 0013: control actions are versioned driver code with typed parameters

Date: 2026-09-04. Status: accepted. Decisions D49 to D51 in `PROJECT_PLAN.md`.

## Context

Architecture 17.3 asks for capability-driven, configurable control actions with typed parameters, permissions, confirmation policies and result interpretation, usable by the UI, by rules and later by MCP. Section 32 left open how action definitions are versioned.

## Decision

Actions are `ControlAction` objects declared in the driver (`shared/control/actions.py`): key, label, a Pydantic parameter model exported as JSON schema, permission, confirmation policy, required connectivity capability, encoder and optional interpreter. The set carries a `schema_version`; a command stores the version it was created with. Definitions are not stored in the database: encoding is code, and a second source of truth would drift.

The command path is one function (`shared/control/commands.py`): create, encode, select the route among the device's data sources, submit through the adapter's command connector, and record every stage as a `command_executions` row. Provider events and device responses move the lifecycle; the driver's interpreter decides `confirmed_by_device`. ChirpStack delivers through its REST API queue.

## Consequences

- Manual, automated and later MCP commands share encoding, routing, permissions, audit and traces.
- Adding an action is one declaration plus two tests; adding a network is one command connector.
- A lifecycle stage the platform cannot report is never shown as reached.
- Per-installation edits of labels or limits are not possible without a code change; that can be added as an overlay later if needed.
