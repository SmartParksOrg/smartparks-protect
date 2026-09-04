# Permissions

## Roles

| Role | Where it lives | What it gives |
| --- | --- | --- |
| Server admin | `users.is_superuser` | Everything in every project, plus server administration: accounts, invitations for server admins, catalogues (entity types, device types, metrics), devices, data sources |
| Project admin | membership row | Every permission inside the project: entities, features, members, invitations, assignments of devices to entities, rules, integrations, control, curation |
| Project viewer | membership row | Read the project, read traces, create exports, acknowledge and resolve alerts |

A user can hold different roles in different projects. Server admins need no membership.

## Permission keys

Endpoints declare the key they need. The role decides whether the caller has it.

| Key | Viewer | Admin |
| --- | --- | --- |
| `project:read` | yes | yes |
| `traces:read` | yes | yes |
| `exports:create` | yes | yes |
| `alerts:write` | yes | yes |
| `project:write` | | yes |
| `members:write` | | yes |
| `entities:write` | | yes |
| `devices:write` | | yes |
| `devices:control` | | yes |
| `devices:control_high_impact` | | yes |
| `data_sources:write` | | yes |
| `rules:write` | | yes |
| `automations:write` | | yes |
| `integrations:write` | | yes |
| `data:curate`, `data:curate_bulk`, `data:approve`, `data:revert` | | yes |

## Devices and history

A device is visible to server admins and to members of every project the device was ever assigned to. Members see the assignments that concern their projects, not those of other projects. After a handover, the old project keeps its history and does not see new data (architecture 28.12).

Assigning a device to a project needs server admin or project admin of that project. A handover between projects needs server admin or project admin of both projects.

## Registration

Nobody can register without an invitation. Server admins invite server admins; project admins invite members of their project. The invitation link proves ownership of the email address, so accounts are verified on creation. Invitations expire (168 hours by default) and can be revoked before use.

## Audit

Every mutating admin action writes an `audit_log` row with the actor, action, object, project, request id and a summary of what changed. Project admins read their project's log at `/api/v1/projects/{id}/audit`; server admins read everything at `/api/v1/admin/audit`.
