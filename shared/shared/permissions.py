"""Permission keys, the built-in roles and their sets, and custom roles (decisions D185, D186).

Endpoints declare the permission they need; the caller's role in the project decides. A role
is a named set of keys: four built-in roles (viewer, operator, analyst, admin) that every
server has, or a custom role a project admin composes from the same keys. A server admin has
every permission in every project. Keys are stable strings so they can appear in the audit
log and in the interface; `AREAS` groups them the way the role editor shows them.
"""

from collections.abc import Iterable
from enum import StrEnum

from shared.enums import Role


class Permission(StrEnum):
    PROJECT_READ = "project:read"
    PROJECT_WRITE = "project:write"
    MEMBERS_WRITE = "members:write"
    ENTITIES_WRITE = "entities:write"
    DEVICES_WRITE = "devices:write"
    FEATURES_WRITE = "features:write"
    DEVICES_CONTROL = "devices:control"
    DEVICES_CONTROL_HIGH_IMPACT = "devices:control_high_impact"
    RULES_WRITE = "rules:write"
    ALERTS_WRITE = "alerts:write"
    EVENTS_WRITE = "events:write"
    AUTOMATIONS_WRITE = "automations:write"
    INTEGRATIONS_WRITE = "integrations:write"
    DATA_CURATE = "data:curate"
    DATA_CURATE_BULK = "data:curate_bulk"
    DATA_APPROVE = "data:approve"
    DATA_REVERT = "data:revert"
    TRACES_READ = "traces:read"
    EXPORTS_CREATE = "exports:create"
    VIEWS_WRITE = "views:write"
    DASHBOARDS_WRITE = "dashboards:write"


#: The keys grouped by area, in the order the role editor shows them. `project:read` is in
#: every role: a member who cannot read the project is not a member.
AREAS: tuple[tuple[str, tuple[Permission, ...]], ...] = (
    ("see", (Permission.PROJECT_READ, Permission.TRACES_READ)),
    (
        "entities_and_devices",
        (Permission.ENTITIES_WRITE, Permission.DEVICES_WRITE, Permission.FEATURES_WRITE),
    ),
    ("events_and_alerts", (Permission.EVENTS_WRITE, Permission.ALERTS_WRITE)),
    (
        "data_quality",
        (
            Permission.DATA_CURATE,
            Permission.DATA_CURATE_BULK,
            Permission.DATA_APPROVE,
            Permission.DATA_REVERT,
        ),
    ),
    ("rules_and_automations", (Permission.RULES_WRITE, Permission.AUTOMATIONS_WRITE)),
    ("integrations", (Permission.INTEGRATIONS_WRITE,)),
    (
        "exports_and_analysis",
        (Permission.EXPORTS_CREATE, Permission.VIEWS_WRITE, Permission.DASHBOARDS_WRITE),
    ),
    ("control", (Permission.DEVICES_CONTROL, Permission.DEVICES_CONTROL_HIGH_IMPACT)),
    ("members_and_settings", (Permission.MEMBERS_WRITE, Permission.PROJECT_WRITE)),
)

ALWAYS = frozenset({Permission.PROJECT_READ})

_VIEWER = frozenset({Permission.PROJECT_READ, Permission.TRACES_READ, Permission.ALERTS_WRITE})
_OPERATOR = _VIEWER | {
    Permission.EVENTS_WRITE,
    Permission.DEVICES_CONTROL,
    Permission.FEATURES_WRITE,
}
_ANALYST = _OPERATOR | {
    Permission.EXPORTS_CREATE,
    Permission.VIEWS_WRITE,
    Permission.DASHBOARDS_WRITE,
}

#: The built-in roles, each a superset of the one before (decision D185).
ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.PROJECT_VIEWER: _VIEWER,
    Role.PROJECT_OPERATOR: _OPERATOR,
    Role.PROJECT_ANALYST: _ANALYST,
    Role.PROJECT_ADMIN: frozenset(Permission),
}

BUILTIN_ROLE_LABELS: dict[Role, str] = {
    Role.PROJECT_VIEWER: "Viewer",
    Role.PROJECT_OPERATOR: "Operator",
    Role.PROJECT_ANALYST: "Analyst",
    Role.PROJECT_ADMIN: "Admin",
}


def normalise_permissions(keys: Iterable[str]) -> frozenset[Permission]:
    """A custom role's keys as permissions, `project:read` always included; an unknown key
    raises ValueError with the key in the message."""
    result = set(ALWAYS)
    for key in keys:
        try:
            result.add(Permission(key))
        except ValueError:
            raise ValueError(f"unknown permission {key!r}") from None
    return frozenset(result)


def permissions_for(
    role: Role | None,
    *,
    server_admin: bool,
    custom: Iterable[str] | None = None,
) -> frozenset[Permission]:
    """The caller's permissions: everything for a server admin, a custom role's set when the
    membership names one, else the built-in role's set, nothing without a membership."""
    if server_admin:
        return frozenset(Permission)
    if custom is not None:
        return normalise_permissions(custom)
    if role is None:
        return frozenset()
    return ROLE_PERMISSIONS[role]
