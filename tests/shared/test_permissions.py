from shared.enums import Role
from shared.permissions import Permission, permissions_for


def test_server_admin_has_everything():
    assert permissions_for(None, server_admin=True) == frozenset(Permission)


def test_viewer_cannot_write():
    perms = permissions_for(Role.PROJECT_VIEWER, server_admin=False)
    assert Permission.PROJECT_READ in perms
    assert Permission.TRACES_READ in perms
    assert Permission.DEVICES_WRITE not in perms
    assert Permission.DEVICES_CONTROL not in perms


def test_no_role_no_permissions():
    assert permissions_for(None, server_admin=False) == frozenset()
