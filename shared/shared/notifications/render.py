"""Messages for the channels. One text rendering for Telegram and the plain part of a mail, one
HTML rendering for mail. Every message links back to the object in Smart Parks Protect."""

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape

from shared.config import get_settings

TEMPLATES = Path(__file__).parent / "templates"


@lru_cache
def environment() -> Environment:
    return Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html"]))


@dataclass(slots=True)
class Rendered:
    subject: str
    text: str
    html: str


@dataclass(slots=True)
class EventMessage:
    """What a notification needs to know about an event, resolved by the caller."""

    event_id: str
    event_type: str
    severity: str
    title: str
    time: str
    description: str | None = None
    project_id: str | None = None
    project_name: str | None = None
    entity_name: str | None = None
    device_name: str | None = None
    alert: bool = False
    context: dict[str, Any] = field(default_factory=dict)

    @property
    def link(self) -> str:
        base = get_settings().public_url
        if self.project_id:
            return f"{base}/projects/{self.project_id}/rules/events?event={self.event_id}"
        return f"{base}/admin/alerts?event={self.event_id}"


SEVERITY_MARK = {"info": "INFO", "warning": "WARNING", "critical": "CRITICAL"}


def render_event(message: EventMessage) -> Rendered:
    env = environment()
    context = {
        "m": message,
        "link": message.link,
        "mark": SEVERITY_MARK.get(message.severity, message.severity.upper()),
        "public_url": get_settings().public_url,
    }
    subject = f"[{context['mark']}] {message.title}"
    if message.project_name:
        subject += f" ({message.project_name})"
    return Rendered(
        subject=subject,
        text=env.get_template("event.txt").render(**context),
        html=env.get_template("event.html").render(**context),
    )


def render_test(target_name: str, project_name: str | None) -> Rendered:
    env = environment()
    context = {
        "target_name": target_name,
        "project_name": project_name,
        "public_url": get_settings().public_url,
    }
    return Rendered(
        subject="Smart Parks Protect test notification",
        text=env.get_template("test.txt").render(**context),
        html=env.get_template("test.html").render(**context),
    )
