"""The permission catalogue (decision D185): the keys by area and the built-in roles with their
sets, for the role editor and the members page. Static, for any signed-in account."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from protect_api.auth.users import current_active_user
from shared.enums import Role
from shared.models import User
from shared.permissions import AREAS, BUILTIN_ROLE_LABELS, ROLE_PERMISSIONS

router = APIRouter(prefix="/permissions", tags=["permissions"])


class PermissionArea(BaseModel):
    key: str
    permissions: list[str]


class BuiltinRole(BaseModel):
    key: Role
    label: str
    permissions: list[str]


class PermissionCatalogue(BaseModel):
    areas: list[PermissionArea]
    roles: list[BuiltinRole]


@router.get("", response_model=PermissionCatalogue)
async def permission_catalogue(_: User = Depends(current_active_user)) -> PermissionCatalogue:
    return PermissionCatalogue(
        areas=[PermissionArea(key=key, permissions=[str(p) for p in keys]) for key, keys in AREAS],
        roles=[
            BuiltinRole(key=role, label=BUILTIN_ROLE_LABELS[role], permissions=sorted(perms))
            for role, perms in ROLE_PERMISSIONS.items()
        ],
    )
