"""System alerts through the same event and alert path as rules (architecture 26.2, 26.6):
stale workers, dead letters, consumer lag. Each check opens one alert per subject and resolves
it when the condition clears, so the alert inbox shows the current state and nothing repeats.
System events have no project and are visible to server admins only."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.bus import RedisStreamsBus, Topic, is_stale
from shared.database import session_scope
from shared.enums import AlertStatus, Severity
from shared.logger import get_logger
from shared.models import Alert, Event
from shared.rules.events import NewEvent, close_alert, create_event, event_messages
from shared.timeutil import utc_now

log = get_logger("rules.system")

WORKERS = ("ingest", "decoder", "export", "rules", "automation")
TOPICS = (
    Topic.SOURCE_EVENT_RECEIVED,
    Topic.POSITION_CREATED,
    Topic.MEASUREMENT_CREATED,
    Topic.DEVICE_STATE_CHANGED,
    Topic.EVENT_CREATED,
    Topic.EXPORT_REQUESTED,
)
CONSUMERS = {
    Topic.SOURCE_EVENT_RECEIVED: "decoder",
    Topic.POSITION_CREATED: "rules",
    Topic.MEASUREMENT_CREATED: "rules",
    Topic.EVENT_CREATED: "automation",
    Topic.EXPORT_REQUESTED: "export",
}
LAG_THRESHOLD = 1_000
DEAD_LETTER_THRESHOLD = 1

EVENT_WORKER_STALE = "SYSTEM_WORKER_STALE"
EVENT_DEAD_LETTERS = "SYSTEM_DEAD_LETTERS"
EVENT_STREAM_LAG = "SYSTEM_STREAM_LAG"


@dataclass(slots=True)
class Finding:
    event_type: str
    subject: str
    severity: Severity
    title: str
    context: dict[str, Any]


async def collect(bus: RedisStreamsBus) -> tuple[list[Finding], set[tuple[str, str]]]:
    """Current problems, and every (event_type, subject) the checks know about so cleared ones
    can be resolved."""
    findings: list[Finding] = []
    known: set[tuple[str, str]] = set()
    stamps = await bus.heartbeats()
    for worker in WORKERS:
        known.add((EVENT_WORKER_STALE, worker))
        stamp = stamps.get(worker)
        if is_stale(stamp):
            findings.append(
                Finding(
                    EVENT_WORKER_STALE,
                    worker,
                    Severity.CRITICAL,
                    f"Worker {worker} has not reported for over 15 minutes",
                    {"worker": worker, "last_heartbeat": stamp.isoformat() if stamp else None},
                )
            )
    for topic in TOPICS:
        known.add((EVENT_DEAD_LETTERS, topic))
        count = await bus.dead_count(topic)
        if count >= DEAD_LETTER_THRESHOLD:
            findings.append(
                Finding(
                    EVENT_DEAD_LETTERS,
                    topic,
                    Severity.WARNING,
                    f"{count} dead letters on {topic}",
                    {"topic": topic, "count": count},
                )
            )
    for topic, group in CONSUMERS.items():
        known.add((EVENT_STREAM_LAG, topic))
        lag = await bus.lag(topic, group)
        if lag >= LAG_THRESHOLD:
            findings.append(
                Finding(
                    EVENT_STREAM_LAG,
                    topic,
                    Severity.WARNING,
                    f"{group} is {lag} messages behind on {topic}",
                    {"topic": topic, "group": group, "lag": lag},
                )
            )
    return findings, known


async def _open_alerts(session: AsyncSession) -> dict[tuple[str, str], Alert]:
    rows = await session.execute(
        select(Alert, Event)
        .join(Event, Event.id == Alert.event_id)
        .where(
            Event.project_id.is_(None),
            Alert.status != AlertStatus.RESOLVED,
            Event.event_type.in_((EVENT_WORKER_STALE, EVENT_DEAD_LETTERS, EVENT_STREAM_LAG)),
        )
    )
    result: dict[tuple[str, str], Alert] = {}
    for alert, event in rows:
        result[(event.event_type, str(event.context.get("subject")))] = alert
    return result


async def run_system_checks(bus: RedisStreamsBus) -> tuple[int, int]:
    """Open alerts for new findings, resolve alerts whose finding cleared. Returns
    (opened, resolved)."""
    findings, known = await collect(bus)
    opened = resolved = 0
    messages: list[tuple[str, dict[str, Any]]] = []
    async with session_scope() as session:
        current = await _open_alerts(session)
        active = {(f.event_type, f.subject) for f in findings}
        for finding in findings:
            key = (finding.event_type, finding.subject)
            if key in current:
                continue
            event, alert = await create_event(
                session,
                NewEvent(
                    time=utc_now(),
                    event_type=finding.event_type,
                    severity=finding.severity,
                    title=finding.title,
                    project_id=None,
                    context={**finding.context, "subject": finding.subject, "system": True},
                    create_alert=True,
                ),
            )
            messages.extend(event_messages(event, alert))
            opened += 1
        for key, alert in current.items():
            if key in known and key not in active:
                await close_alert(
                    session,
                    alert,
                    AlertStatus.RESOLVED,
                    user_id=None,
                    note="Resolved automatically: the condition cleared",
                )
                resolved += 1
        await session.commit()
    for topic, payload in messages:
        await bus.publish(topic, payload)
    if opened or resolved:
        log.info("system checks", opened=opened, resolved=resolved)
    return opened, resolved
