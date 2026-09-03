"""Create the invitation for the first server admin.

Registration is by invitation only, so a fresh installation needs one invitation that nobody
sent. This command creates it when the database has no server admin yet and prints the
registration link. It refuses when a server admin exists: from then on admins invite admins.

    docker compose run --rm api /app/.venv/bin/python -m protect_api.bootstrap admin@example.org
    scripts/dev.sh bootstrap-admin admin@example.org
"""

import argparse
import asyncio
import secrets
import sys
from datetime import timedelta

from sqlalchemy import func, select

from shared.config import get_settings
from shared.database import session_scope
from shared.models import Invitation, User
from shared.timeutil import utc_now


async def create_first_admin_invitation(email: str) -> str:
    settings = get_settings()
    async with session_scope() as session:
        admins = await session.scalar(
            select(func.count()).select_from(User).where(User.is_superuser.is_(True))
        )
        if admins:
            raise SystemExit(
                "A server admin exists already. Invite further admins through the API."
            )
        token = secrets.token_urlsafe(32)
        session.add(
            Invitation(
                email=email.lower(),
                server_admin=True,
                token=token,
                expires_at=utc_now() + timedelta(hours=settings.invitation_lifetime_hours),
            )
        )
        await session.commit()
    return f"{settings.public_url}/register?token={token}"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Invite the first server admin")
    parser.add_argument("email")
    args = parser.parse_args(argv)
    link = asyncio.run(create_first_admin_invitation(args.email))
    sys.stdout.write(f"Invitation created for {args.email}\nRegister at: {link}\n")


if __name__ == "__main__":
    main()
