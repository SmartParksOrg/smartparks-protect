"""Outgoing mail for invitations and password resets.

In development (ENVIRONMENT=development) mail goes only to addresses in DEV_NOTIFY_EMAILS; every
other message is logged instead of sent, so a development server holding real users never mails
them (pattern from AddaxAI Connect). Without SMTP settings every message is logged.
"""

from email.message import EmailMessage
from functools import lru_cache
from pathlib import Path

import aiosmtplib
from jinja2 import Environment, FileSystemLoader, select_autoescape

from shared.config import Settings, get_settings
from shared.logger import get_logger

log = get_logger("api.mailer")

TEMPLATES = Path(__file__).parent / "templates"


class Mailer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.env = Environment(
            loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"])
        )

    def _allowed(self, to: str) -> tuple[bool, str]:
        if not self.settings.mail_configured:
            return False, "mail is not configured"
        if self.settings.environment != "production":
            if to.strip().lower() in self.settings.dev_notify_email_list:
                return True, ""
            return False, "not a production server and recipient not in DEV_NOTIFY_EMAILS"
        return True, ""

    async def send(self, to: str, subject: str, template: str, **context: object) -> bool:
        """Render and send. Returns True when sent, False when logged instead."""
        context = {"public_url": self.settings.public_url, **context}
        text = self.env.get_template(f"{template}.txt").render(**context)
        html = self.env.get_template(f"{template}.html").render(**context)
        allowed, reason = self._allowed(to)
        if not allowed:
            log.warning("mail logged, not sent", to=to, subject=subject, reason=reason, body=text)
            return False
        message = EmailMessage()
        message["From"] = self.settings.mail_from
        message["To"] = to
        message["Subject"] = subject
        message.set_content(text)
        message.add_alternative(html, subtype="html")
        assert self.settings.mail_server is not None
        port = self.settings.mail_port
        await aiosmtplib.send(
            message,
            hostname=self.settings.mail_server,
            port=port,
            username=self.settings.mail_username,
            password=self.settings.mail_password,
            use_tls=port == 465,
            start_tls=port != 465,
        )
        log.info("mail sent", to=to, subject=subject)
        return True

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
