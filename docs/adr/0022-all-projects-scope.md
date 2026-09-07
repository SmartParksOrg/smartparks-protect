# 0022 The all-projects scope

Date: 2026-09-07. Status: accepted. Decision D115 in the project plan.

## Context

One server carries several parks. The person running it wants one live map and one set of monitoring lists over every project, while every page, link, query key and user preference in the application is keyed by a project id in the URL (`/projects/{project_id}/...`). Project isolation is the security boundary (decision D92): a member sees the projects of their memberships, a server admin sees everything.

## Decision

The reserved project id `all` is the scope over every project, for server admins only. The frontend's project switcher lists All projects at the top for a server admin and navigates to `/projects/all/map`, so nothing else in the application needs a second addressing scheme. In the API, the endpoints that support the scope take a `ScopeContext` from `get_scope_context`, which accepts `all` for a server admin (403 for anyone else) or a project id as before; they filter with `context.where(Model.project_id)`, which is the project's id in a project and "any project" (never the system scope of events without a project) in the all scope. Every other `/projects/{project_id}` endpoint keeps a UUID path parameter, so `all` is a 422 there and no write or configuration endpoint ever runs across projects. The WebSocket accepts `all` the same way and forwards every project's messages on one connection. Reads and map features carry `project_id`, so the frontend can name the project and link into it.

## Consequences

The monitoring views (live map with every layer, entities, devices, alerts, events, gateways, traffic) work across projects with the same bounds as within one; the tiles path takes over above the entity threshold as it does for a large project. The other pages stay per project and the sidebar hides them in the scope. The access matrix test walks the scope: a server admin gets 200 on the supported reads with `all`, a project admin 403, and every unsupported endpoint refuses the id. A new endpoint that should work across projects must opt in by taking the scope context; the default is per project.
