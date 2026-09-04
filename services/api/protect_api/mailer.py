"""Outgoing mail for invitations and password resets: the auth templates on top of the shared
sender in `shared.notifications.email`, which holds the development guard."""

from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from shared.config import Settings, get_settings
from shared.logger import get_logger
from shared.notifications.email import send_email

log = get_logger("api.mailer")

TEMPLATES = Path(__file__).parent / "templates"


class Mailer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.env = Environment(
            loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"])
        )

    async def send(self, to: str, subject: str, template: str, **context: object) -> bool:
        """Render and send through the shared sender (development guard included). Returns
        True when sent, False when logged instead."""
        context = {"public_url": self.settings.public_url, **context}
        text = self.env.get_template(f"{template}.txt").render(**context)
        html = self.env.get_template(f"{template}.html").render(**context)
        return await send_email(to, subject, text, html)

    async def send_invitation(
        self, to: str, token: str, *, project_name: str | None, invited_by: str | None
    ) -> bool:
        link = f"{self.settings.public_url}/register?token={token}"
        return await self.send(
            to,
            "You are invited to Smart Parks Protect",
            "invitation",
            link=link,
            project_name=project_name,
            invited_by=invited_by,
        )

    async def send_password_reset(self, to: str, token: str) -> bool:
        link = f"{self.settings.public_url}/reset-password?token={token}"
        return await self.send(
            to, "Reset your Smart Parks Protect password", "password_reset", link=link
        )


@lru_cache
def get_mailer() -> Mailer:
    return Mailer(get_settings())
