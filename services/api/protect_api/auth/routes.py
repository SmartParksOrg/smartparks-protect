"""Auth endpoints under /api/v1/auth and /api/v1/users."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi_users import exceptions
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.auth.manager import UserManager
from protect_api.auth.schemas import (
    ChangePasswordRequest,
    InvitationInfo,
    RegisterRequest,
    TokenResponse,
    UserCreate,
    UserRead,
    UserUpdate,
)
from protect_api.auth.users import (
    auth_backend,
    current_active_user,
    fastapi_users,
    get_jwt_strategy,
    get_user_manager,
)
from shared.database import get_session
from shared.enums import Role
from shared.logger import get_logger
from shared.models import Invitation, Project, ProjectMembership, User

log = get_logger("api.auth")

router = APIRouter()
router.include_router(fastapi_users.get_auth_router(auth_backend), prefix="/auth", tags=["auth"])
router.include_router(fastapi_users.get_reset_password_router(), prefix="/auth", tags=["auth"])
router.include_router(
    fastapi_users.get_users_router(UserRead, UserUpdate), prefix="/users", tags=["users"]
)


async def _valid_invitation(session: AsyncSession, token: str) -> Invitation:
    invitation = await session.scalar(select(Invitation).where(Invitation.token == token))
    if invitation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Invalid invitation token")
    if invitation.used_at is not None:
        raise HTTPException(status.HTTP_410_GONE, "This invitation has already been used")
    if invitation.expires_at < datetime.now(UTC):
        raise HTTPException(status.HTTP_410_GONE, "This invitation has expired")
    return invitation


@router.get("/auth/invitation", response_model=InvitationInfo, tags=["auth"])
async def invitation_info(
    token: str, session: AsyncSession = Depends(get_session)
) -> InvitationInfo:
    """What an invitation link offers, so the registration page can show it before asking for a
    password."""
    invitation = await _valid_invitation(session, token)
    project_name = None
    if invitation.project_id is not None:
        project_name = await session.scalar(
            select(Project.name).where(Project.id == invitation.project_id)
        )
    return InvitationInfo(
        email=invitation.email,
        server_admin=invitation.server_admin,
        role=invitation.role,
        project_id=invitation.project_id,
        project_name=project_name,
        expires_at=invitation.expires_at,
    )


@router.post(
    "/auth/register", response_model=UserRead, status_code=status.HTTP_201_CREATED, tags=["auth"]
)
async def register(
    body: RegisterRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
    user_manager: UserManager = Depends(get_user_manager),
) -> User:
    """Registration by invitation only. The token proves ownership of the invited address, so the
    account is verified on creation. The invitation's role becomes a membership."""
    invitation = await _valid_invitation(session, body.token)
    try:
        user = await user_manager.create(
            UserCreate(
                email=invitation.email,
                password=body.password,
                full_name=body.full_name,
                timezone=body.timezone,
                is_superuser=invitation.server_admin,
                is_verified=True,
            ),
            safe=False,
            request=request,
        )
    except exceptions.UserAlreadyExists:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "An account with this email exists"
        ) from None
    except exceptions.InvalidPasswordException as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.reason) from None
    if invitation.project_id is not None and invitation.role is not None:
        session.add(
            ProjectMembership(
                user_id=user.id,
                project_id=invitation.project_id,
                role=Role(invitation.role),
                added_by_user_id=invitation.invited_by_user_id,
            )
        )
    invitation.used_at = datetime.now(UTC)
    invitation.used_by_user_id = user.id
    await record_audit(
        session,
        user=user,
        action="user.registered",
        object_type="user",
        object_id=str(user.id),
        project_id=invitation.project_id,
        details={"invitation_id": str(invitation.id), "role": invitation.role},
    )
    await session.commit()
    log.info("user registered", user_id=str(user.id), project_id=str(invitation.project_id))
    return user


@router.post("/auth/change-password", response_model=TokenResponse, tags=["auth"])
async def change_password(
    body: ChangePasswordRequest,
    user: User = Depends(current_active_user),
    user_manager: UserManager = Depends(get_user_manager),
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """Change the password and return a fresh token for this session. Every other session is
    logged out because their tokens predate `password_changed_at`."""
    verified, _ = user_manager.password_helper.verify_and_update(
        body.current_password, user.hashed_password
    )
    if not verified:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Current password is incorrect")
    try:
        await user_manager.validate_password(body.new_password, user)
    except exceptions.InvalidPasswordException as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.reason) from None
    updated = await user_manager.user_db.update(
        user,
        {
            "hashed_password": user_manager.password_helper.hash(body.new_password),
            "password_changed_at": datetime.now(UTC).replace(microsecond=0),
        },
    )
    await record_audit(
        session,
        user=user,
        action="user.password_changed",
        object_type="user",
        object_id=str(user.id),
    )
    await session.commit()
    return TokenResponse(access_token=await get_jwt_strategy().write_token(updated))
