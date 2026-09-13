# 0030. Roles as named permission sets, custom roles per project, and a member's scope enforced on every read

Date: 2026-09-13

Status: accepted

## Context

Access was two project roles and a server-admin flag. The nineteen permission keys existed, but the admin role held all of them and the viewer a fixed five, so the keys were a viewer-or-admin split in disguise. Every read was filtered by project only: a member saw every animal, device and event of the project, and the layers panel's hide lists were a preference the browser applied, not a limit. The interface hard-coded the two role names in its gates. Tim wants administrators to control, per person or per kind of person, both what they may do (settings, dashboards, exports, control) and what they may see (specific devices, entities or groups).

## Decision

A role is a named set of permission keys (decision D185). Four built-in roles exist on every server, each a superset of the one before: Viewer (see the project, read traces, acknowledge alerts), Operator (also report events, control devices, draw features), Analyst (also export, keep saved views, build dashboards), Admin (everything). A project admin composes custom roles from the same keys (decision D187: `project_roles` rows of the project), grouped in nine areas the role editor shows with a line of explanation per key; `project:read` is in every role. A member holds one role; the two old role values keep their names, so existing rows need no migration, and operator and analyst join them.

A membership carries a scope (decision D186): none for the whole project, or groups (with everything below them), single entities and single devices. The API resolves the scope per request to entity and device ids (an entity in scope brings the device tracking it today) and every project read applies it: entities and groups, devices, the map's current state, positions, tracks and heat, events, alerts and the feed, records, analysis series, exports (the job's parameters are narrowed, so the export worker needs no membership), search, coverage, traffic, gateway connectivity and traces, device control and the device's own reads. Features, gateways, rules and the rest of the project stay visible; things outside the scope do not exist for that member, 404 like anything else that is not theirs. Invitations carry the role and the scope, and registration copies both.

The interface follows permission keys, not role names (decision D188): the project list carries the caller's keys per project, every gate asks `can(key)`, the navigation and the project admin routes are keyed the same way, and the role names appear only where a role is chosen.

## Alternatives considered

- Per-member checkboxes without roles: flexible, but forty members mean forty forms to keep aligned, and no name to say what a person is.
- Built-in roles only: no way to say "events and control but no exports" without a code change.
- Server-wide custom roles: a project's admin knows the project's people; server-wide templates can come when two projects want the same role.
- Scope by groups only: a ranger who watches one collar wants that collar, not a group made for one animal.
- Hiding the network, features and rules for scoped members as well: more keys and more to explain for a need nobody has yet; a custom role without the keys already keeps them from changing any of it.
- Enforcing the scope in the browser: a preference is not a limit.

## Consequences

An administrator sets a member's role from a list and, when needed, narrows what they see with a picker; the members page shows both in one table. Every read of project data passes through the visibility filter, so a new read must apply it too: the access tests check a scoped member across the reads, and the export worker trusts the narrowed parameters on the job. A custom role deleted while in use is refused; a role narrowed later narrows its members at once. Viewers lost the right to report events and export, which the operator and analyst roles carry now; existing viewers who need those get one of those roles.
