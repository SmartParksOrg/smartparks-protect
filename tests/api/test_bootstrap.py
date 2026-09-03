import pytest
from sqlalchemy import select

from protect_api.bootstrap import create_first_admin_invitation
from shared.models import Invitation
from tests.api.conftest import PASSWORD

pytestmark = pytest.mark.asyncio


async def test_bootstrap_creates_invitation_once(client, db, migrated_database):
    # the test database may already hold server admins from other tests; check both branches
    from sqlalchemy import func

    from shared.models import User

    admins = await db.scalar(
        select(func.count()).select_from(User).where(User.is_superuser.is_(True))
    )
    if admins:
        with pytest.raises(SystemExit):
            await create_first_admin_invitation("first@example.org")
        return
    link = await create_first_admin_invitation("first@example.org")
    token = link.rsplit("token=", 1)[1]
    invitation = await db.scalar(select(Invitation).where(Invitation.token == token))
    assert invitation is not None and invitation.server_admin
    response = await client.post(
        "/api/v1/auth/register", json={"token": token, "password": PASSWORD}
    )
    assert response.status_code == 201 and response.json()["is_superuser"] is True
    with pytest.raises(SystemExit):
        await create_first_admin_invitation("second@example.org")
