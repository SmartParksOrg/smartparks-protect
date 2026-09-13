# Permissions

## Roles

A role is a named set of permissions. Four built-in roles exist on every server, each a superset of the one before, and a project admin composes custom roles from the same permissions under Members, Roles (decisions D185, D187, ADR 0030).

| Role | Where it lives | What it gives |
| --- | --- | --- |
| Server admin | `users.is_superuser` | Everything in every project, plus server administration: accounts, invitations for server admins, catalogues (entity types, device types, metrics), devices, data sources |
| Admin | membership row, `project-admin` | Every permission inside the project |
| Analyst | membership row, `project-analyst` | An operator who also exports data and keeps saved views and dashboards |
| Operator | membership row, `project-operator` | A viewer who also reports events, controls devices and draws features |
| Viewer | membership row, `project-viewer` | Sees the project, reads traces, acknowledges and resolves alerts |
| A custom role | `project_roles` row named by the membership | Exactly the permissions the role lists; seeing the project is always in |

A user can hold different roles in different projects. Server admins need no membership. A project admin manages the project's members under Members; a server admin manages one person across every project from Server admin, Users, where the account page shows every membership with its role and scope, editable there (decision D189).

## Permission keys

Endpoints declare the key they need. The role decides whether the caller has it. The keys are grouped in areas, the way the role editor shows them.

| Area | Key | Viewer | Operator | Analyst | Admin |
| --- | --- | --- | --- | --- | --- |
| See | `project:read` | yes | yes | yes | yes |
| See | `traces:read` | yes | yes | yes | yes |
| Events and alerts | `alerts:write` | yes | yes | yes | yes |
| Events and alerts | `events:write` | | yes | yes | yes |
| Control | `devices:control` | | yes | yes | yes |
| Entities and devices | `features:write` | | yes | yes | yes |
| Exports and analysis | `exports:create` | | | yes | yes |
| Exports and analysis | `views:write` | | | yes | yes |
| Exports and analysis | `dashboards:write` | | | yes | yes |
| Entities and devices | `entities:write`, `devices:write` | | | | yes |
| Data quality | `data:curate`, `data:curate_bulk`, `data:approve`, `data:revert` | | | | yes |
| Rules and automations | `rules:write`, `automations:write` | | | | yes |
| Integrations | `integrations:write` | | | | yes |
| Control | `devices:control_high_impact` | | | | yes |
| Members and settings | `members:write`, `project:write` | | | | yes |

The interface asks the same keys: a button, a page or a menu entry shows when the member's role grants its key (decision D188). The project list carries the caller's keys per project.

## What a member sees: the scope

A membership can carry a scope (decision D186): groups (with everything below them), single entities and single devices. Without a scope the member sees the whole project. With one, the API applies it to every read of project data: the entities and groups, the devices, the live map's state, positions, tracks and heat, events, alerts and the feed, records, analysis series, exports (the export takes only what is in scope), search, coverage, traffic, gateway connectivity and traces, and device control. An entity in scope brings the device tracking it today. Features, gateways, rules and the rest of the project stay visible. Things outside the scope do not exist for that member: a page of another animal answers 404.

An admin sets the scope under Members in the Sees column, and an invitation can carry a scope so the person never sees more than meant.

## Devices and history

A device is visible to server admins and to members of every project the device was ever assigned to, within their scope. Members see the assignments that concern their projects, not those of other projects. After a handover, the old project keeps its history and does not see new data (architecture 28.12).

Assigning a device to a project needs server admin or `devices:write` in that project. A handover between projects needs server admin or that permission in both projects.

## Registration

Nobody can register without an invitation. Server admins invite a person as server admin and/or into any projects at once, each with a role and, when wanted, a scope (decision D190); members with `members:write` invite members of their own project, with a role and, when wanted, a scope. The new account receives every membership the invitation carries. The invitation link proves ownership of the email address, so accounts are verified on creation. Invitations expire (168 hours by default) and can be revoked before use.

## Audit

Every mutating admin action writes an `audit_log` row with the actor, action, object, project, request id and a summary of what changed, role and scope changes included. Project admins read their project's log at `/api/v1/projects/{id}/audit`; server admins read everything at `/api/v1/admin/audit`.

## All projects

A server admin can open every project at once from the project switcher (the reserved project id `all`, decision D115). The live map, the entities and devices lists, alerts, events, gateways and traffic then read across projects; nothing can be changed from that scope, and every write and configuration page stays per project. A member who opens `/projects/all/...` gets a 403.
