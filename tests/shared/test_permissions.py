"""Roles and permission keys (decisions D185, D188): the built-in sets nest, a custom role
resolves from its keys with project:read always in, and the areas cover every key once."""

import pytest

from shared.enums import Role
from shared.permissions import (
    AREAS,
    BUILTIN_ROLE_LABELS,
    ROLE_PERMISSIONS,
    Permission,
    normalise_permissions,
    permissions_for,
)


def test_builtin_roles_nest_and_have_labels():
    viewer, operator, analyst, admin = (
        ROLE_PERMISSIONS[Role.PROJECT_VIEWER],
        ROLE_PERMISSIONS[Role.PROJECT_OPERATOR],
        ROLE_PERMISSIONS[Role.PROJECT_ANALYST],
        ROLE_PERMISSIONS[Role.PROJECT_ADMIN],
    )
    assert viewer < operator < analyst < admin
    assert Permission.PROJECT_READ in viewer and Permission.ALERTS_WRITE in viewer
    assert Permission.EVENTS_WRITE not in viewer and Permission.EXPORTS_CREATE not in operator
    assert Permission.DEVICES_CONTROL in operator and Permission.DASHBOARDS_WRITE in analyst
    assert admin == frozenset(Permission)
    assert set(BUILTIN_ROLE_LABELS) == set(Role)


def test_areas_cover_every_key_once():
    listed = [key for _, keys in AREAS for key in keys]
    assert sorted(listed) == sorted(Permission)
    assert len(listed) == len(set(listed))


def test_custom_role_resolution():
    custom = permissions_for(
        Role.PROJECT_VIEWER, server_admin=False, custom=["events:write", "devices:control"]
    )
    assert custom == {Permission.PROJECT_READ, Permission.EVENTS_WRITE, Permission.DEVICES_CONTROL}
    assert permissions_for(Role.PROJECT_VIEWER, server_admin=False, custom=[]) == {
        Permission.PROJECT_READ
    }
    assert permissions_for(None, server_admin=True, custom=[]) == frozenset(Permission)
    assert permissions_for(None, server_admin=False) == frozenset()
    with pytest.raises(ValueError, match="unknown permission"):
        normalise_permissions(["exports:everything"])
