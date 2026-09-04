"""Fine-grained permission keys and their mapping from roles.

Endpoints declare the permission they need; the role of the caller in the project decides. A server
admin has every permission in every project. Keys are stable strings so they can appear in the
audit log, in the UI and later in per-member overrides.
"""

from enum import StrEnum

from shared.enums import Role


class Permission(StrEnum):
    PROJECT_READ = "project:read"
    PROJECT_WRITE = "project:write"
    MEMBERS_WRITE = "members:write"
    ENTITIES_WRITE = "entities:write"
    DEVICES_WRITE = "devices:write"
    DEVICES_CONTROL = "devices:control"
    DEVICES_CONTROL_HIGH_IMPACT = "devices:control_high_impact"
    DATA_SOURCES_WRITE = "data_sources:write"
    RULES_WRITE = "rules:write"
    ALERTS_WRITE = "alerts:write"
    AUTOMATIONS_WRITE = "automations:write"
    INTEGRATIONS_WRITE = "integrations:write"
    DATA_CURATE = "data:curate"
    DATA_CURATE_BULK = "data:curate_bulk"
    DATA_APPROVE = "data:approve"
    DATA_REVERT = "data:revert"
    TRACES_READ = "traces:read"
    EXPORTS_CREATE = "exports:create"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.PROJECT_VIEWER: frozenset(
        {
            Permission.PROJECT_READ,
            Permission.TRACES_READ,
            Permission.EXPORTS_CREATE,
            Permission.ALERTS_WRITE,
        }
    ),
    Role.PROJECT_ADMIN: frozenset(Permission),
}


def permissions_for(role: Role | None, *, server_admin: bool) -> frozenset[Permission]:
    if server_admin:
        return frozenset(Permission)
    if role is None:
        return frozenset()
    return ROLE_PERMISSIONS[role]
