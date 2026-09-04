"""Email over SMTP with the development guard from AddaxAI Connect: on a non-production server
only addresses in DEV_NOTIFY_EMAILS receive mail, everything else is logged. Without SMTP
settings every message is logged."""

from email.message import EmailMessage

import aiosmtplib

from shared.config import get_settings
from shared.logger import get_logger

log = get_logger("notifications.email")


def allowed_recipient(to: str) -> tuple[bool, str]:
    settings = get_settings()
    if not settings.mail_configured:
        return False, "mail is not configured"
    if settings.environment != "production":
        if to.strip().lower() in settings.dev_notify_email_list:
            return True, ""
        return False, "not a production server and recipient not in DEV_NOTIFY_EMAILS"
    return True, ""


async def send_email(to: str, subject: str, text: str, html: str | None = None) -> bool:
    """Send, or log when the guard says no. Returns True when sent. Raises on SMTP failure so
    the caller can retry."""
    settings = get_settings()
    allowed, reason = allowed_recipient(to)
    if not allowed:
        log.warning("mail logged, not sent", to=to, subject=subject, reason=reason, body=text)
        return False
    message = EmailMessage()
    message["From"] = settings.mail_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    if html:
        message.add_alternative(html, subtype="html")
    assert settings.mail_server is not None
    port = settings.mail_port
    await aiosmtplib.send(
        message,
        hostname=settings.mail_server,
        port=port,
        username=settings.mail_username,
        password=settings.mail_password,
        use_tls=port == 465,
        start_tls=port != 465,
    )
    log.info("mail sent", to=to, subject=subject)
    return True
