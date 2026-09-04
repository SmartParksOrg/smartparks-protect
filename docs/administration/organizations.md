# Organizations

An organization is a grouping of projects for server admins (decision D92): a name and a
slug, shown as a column and a filter on the Projects page and as a setting on each project.
It is not a security boundary. Membership, roles and permissions stay per project (decision
D21), and a server admin sees every project whatever its organization.

- Server admin, Projects: the Organizations card creates and removes groupings; the filter
  above the table narrows it to one organization or to projects without one; a new project
  can be created inside an organization.
- Project admin, Settings: server admins move a project between organizations there. Project
  admins see the field but cannot change it.
- Removing an organization leaves its projects in place without a grouping.

API: `GET`, `POST`, `PATCH` and `DELETE` under `/api/v1/admin/organizations`; `organization_id`
on projects; `GET /api/v1/projects?organization_id=` filters the list, for server admins and
members alike. Enforcement of organizations as a boundary is reconsidered when two
organizations share one server.
