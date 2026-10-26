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
| Exports and analysis | `analysis:run` | | | yes | yes |
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

A device is visible to server admins and to members of every project the device was ever assigned to, within their scope. Members see the assignments that concern their projects, not those of other projects. After a move, the old project keeps what lies before the chosen moment and does not see the rest; a device moved with its whole history leaves the old project. A boundary between two assignments is moved after the fact by whoever could have made the rows: a project boundary by a server admin or a project admin of every project involved, an entity boundary by a member with `devices:write` in the entities' projects; the change is audited with the reason (decisions D355 to D358).

Assigning a device to a project needs server admin or project admin in that project, one device or many at once. A move between projects, of a device or of an entity with its devices, needs server admin or project admin in every project involved. Creating an entity per device from a selection needs `devices:write` and `entities:write`.

A device in a project is its project admins' to manage (decision D337, Tim, 2026-10-19: a project admin had to be made server admin to add offload stations). With `devices:write` a member adds a device to the project (the Devices page's "Add device" and the station dialog, `POST /projects/{id}/devices`, decision D326), changes its name, type, status, notes and location source (`PATCH /devices/{id}`), sets or clears its picture, and links an identity such as a DevEUI (`POST /devices/{id}/identities`), choosing the data source by name from `GET /projects/{id}/data-sources`, which carries names and adapters alone. A device made by mistake is deleted from its page by the same people, while it has no data (no message, no log file, no record); a device with data is retired instead, or deleted with all its data by a server admin who typed DELETE in the dialog. Server admin stays required for a device in no project, for moving a device out of its project's reach, for the CSV import, for device types and for the data sources themselves.

## Registration

Nobody can register without an invitation. Server admins invite a person as server admin and/or into any projects at once, each with a role and, when wanted, a scope (decision D190); members with `members:write` invite members of their own project, with a role and, when wanted, a scope. The new account receives every membership the invitation carries. The invitation link proves ownership of the email address, so accounts are verified on creation. Invitations expire (168 hours by default) and can be revoked before use.

## Audit

Every mutating admin action writes an `audit_log` row with the actor, action, object, project, request id and a summary of what changed, role and scope changes included. Project admins read their project's log at `/api/v1/projects/{id}/audit`; server admins read everything at `/api/v1/admin/audit`.

## All projects

A server admin can open every project at once from the project switcher (the reserved project id `all`, decision D115). The live map, the entities and devices lists, alerts, events, gateways and traffic then read across projects; nothing can be changed from that scope, and every write and configuration page stays per project. A member who opens `/projects/all/...` gets a 403.
