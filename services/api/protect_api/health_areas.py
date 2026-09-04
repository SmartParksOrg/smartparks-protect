"""System Health per pipeline area (architecture 26.2): ingestion, decoding, rules and
automation, integrations, device control, exports, backups. Each area has a status and a few
indicators with a link to where an administrator drills down. Counts are bounded to the last
hour or the last 24 hours."""

from datetime import timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.backup import assess as assess_backups
from shared.config import get_settings
from shared.control.commands import FINAL as COMMAND_FINAL
from shared.enums import DeliveryStatus, ExportStatus, ProcessingStatus, TraceStatus
from shared.models import (
    ActionDelivery,
    Command,
    DataSource,
    ExportJob,
    ExternalIdentity,
    IntegrationDelivery,
    ProcessingTrace,
    Rule,
    SourceEvent,
)
from shared.models import ApplicationError as ApplicationErrorRow
from shared.timeutil import utc_now

DAY = timedelta(hours=24)
HOUR = timedelta(hours=1)


class AreaIndicator(BaseModel):
    label: str
    value: str
    status: str = "ok"  # ok, warning, critical
    link: str | None = None


class AreaHealth(BaseModel):
    key: str
    label: str
    status: str
    indicators: list[AreaIndicator]


def _status(indicators: list[AreaIndicator]) -> str:
    statuses = {i.status for i in indicators}
    if "critical" in statuses:
        return "critical"
    if "warning" in statuses:
        return "warning"
    return "ok"


async def _count(session: AsyncSession, statement: Any) -> int:
    return int(await session.scalar(statement) or 0)


def _ind(
    label: str,
    value: int | str,
    *,
    warn: bool = False,
    critical: bool = False,
    link: str | None = None,
) -> AreaIndicator:
    return AreaIndicator(
        label=label,
        value=str(value),
        status="critical" if critical else "warning" if warn else "ok",
        link=link,
    )


async def ingestion(session: AsyncSession, now: Any) -> AreaHealth:
    hour_ago = now - HOUR
    events = await _count(
        session,
        select(func.count()).select_from(SourceEvent).where(SourceEvent.ingested_at >= hour_ago),
    )
    failed = await _count(
        session,
        select(func.count())
        .select_from(SourceEvent)
        .where(
            SourceEvent.ingested_at >= hour_ago,
            SourceEvent.processing_status == ProcessingStatus.FAILED,
        ),
    )
    unknown = await _count(
        session,
        select(func.count())
        .select_from(ExternalIdentity)
        .where(ExternalIdentity.device_id.is_(None), ExternalIdentity.ignored.is_(False)),
    )
    enabled_sources = list(
        await session.scalars(select(DataSource).where(DataSource.enabled.is_(True)))
    )
    silent = 0
    for source in enabled_sources:
        last = await session.scalar(
            select(func.max(SourceEvent.ingested_at)).where(SourceEvent.data_source_id == source.id)
        )
        if last is None or last < hour_ago:
            silent += 1
    return AreaHealth(
        key="ingestion",
        label="Ingestion",
        status=_status(
            indicators := [
                _ind("Events per minute", f"{events / 60:.2f}"),
                _ind("Rejected, last hour", failed, warn=failed > 0, link="/admin/attention"),
                _ind("Unknown identities", unknown, warn=unknown > 0, link="/admin/attention"),
                _ind(
                    "Enabled sources silent for an hour",
                    f"{silent} of {len(enabled_sources)}",
                    warn=silent > 0,
                    link="/admin/data-sources",
                ),
            ]
        ),
        indicators=indicators,
    )


async def decoding(session: AsyncSession, now: Any) -> AreaHealth:
    day_ago = now - DAY
    hour_ago = now - HOUR
    by_code = (
        await session.execute(
            select(ApplicationErrorRow.error_code, func.count())
            .select_from(ProcessingTrace)
            .join(ApplicationErrorRow, ApplicationErrorRow.id == ProcessingTrace.error_id)
            .where(
                ProcessingTrace.started_at >= day_ago,
                ProcessingTrace.status.in_((TraceStatus.FAILED, TraceStatus.DEAD_LETTER)),
                ProcessingTrace.root_object_type == "source_event",
            )
            .group_by(ApplicationErrorRow.error_code)
            .order_by(func.count().desc())
            .limit(3)
        )
    ).all()
    total = await _count(
        session,
        select(func.count()).select_from(SourceEvent).where(SourceEvent.ingested_at >= hour_ago),
    )
    duplicates = await _count(
        session,
        select(func.count())
        .select_from(SourceEvent)
        .where(
            SourceEvent.ingested_at >= hour_ago,
            SourceEvent.processing_status == ProcessingStatus.DUPLICATE,
        ),
    )
    unassigned = await _count(
        session,
        select(func.count())
        .select_from(SourceEvent)
        .where(
            SourceEvent.ingested_at >= day_ago,
            SourceEvent.processing_status == ProcessingStatus.UNASSIGNED,
        ),
    )
    failed_total = sum(int(c) for _, c in by_code)
    indicators = [
        _ind(
            "Decode failures, last 24 hours",
            failed_total,
            warn=failed_total > 0,
            link="/admin/attention",
        ),
        *[
            _ind(f"  {code}", int(count), warn=True, link="/admin/attention")
            for code, count in by_code
        ],
        _ind("Duplicate rate, last hour", f"{(100 * duplicates / total):.0f}%" if total else "0%"),
        _ind(
            "Unassigned devices, last 24 hours",
            unassigned,
            warn=unassigned > 0,
            link="/admin/attention",
        ),
    ]
    return AreaHealth(
        key="decoding", label="Decoding", status=_status(indicators), indicators=indicators
    )


async def rules(session: AsyncSession, now: Any) -> AreaHealth:
    day_ago = now - DAY
    broken = await _count(
        session,
        select(func.count())
        .select_from(Rule)
        .where(Rule.enabled.is_(True), Rule.last_error.is_not(None)),
    )
    failed_actions = await _count(
        session,
        select(func.count())
        .select_from(ActionDelivery)
        .where(
            ActionDelivery.created_at >= day_ago, ActionDelivery.status == DeliveryStatus.FAILED
        ),
    )
    queued_actions = await _count(
        session,
        select(func.count())
        .select_from(ActionDelivery)
        .where(ActionDelivery.status == DeliveryStatus.QUEUED),
    )
    indicators = [
        _ind(
            "Enabled rules with an evaluation error", broken, warn=broken > 0, link="/admin/alerts"
        ),
        _ind(
            "Notification actions failed, last 24 hours",
            failed_actions,
            warn=failed_actions > 0,
            link="/admin/automations",
        ),
        _ind("Notification actions waiting", queued_actions, warn=queued_actions > 100),
    ]
    return AreaHealth(
        key="rules", label="Rules and automation", status=_status(indicators), indicators=indicators
    )


async def integrations(session: AsyncSession, now: Any) -> AreaHealth:
    day_ago = now - DAY
    queued = await _count(
        session,
        select(func.count())
        .select_from(IntegrationDelivery)
        .where(
            IntegrationDelivery.status == DeliveryStatus.QUEUED, IntegrationDelivery.attempts == 0
        ),
    )
    retrying = await _count(
        session,
        select(func.count())
        .select_from(IntegrationDelivery)
        .where(
            IntegrationDelivery.status == DeliveryStatus.QUEUED, IntegrationDelivery.attempts > 0
        ),
    )
    failed = await _count(
        session,
        select(func.count())
        .select_from(IntegrationDelivery)
        .where(
            IntegrationDelivery.created_at >= day_ago,
            IntegrationDelivery.status == DeliveryStatus.FAILED,
        ),
    )
    indicators = [
        _ind("Deliveries waiting", queued, warn=queued > 1000),
        _ind("Deliveries retrying", retrying, warn=retrying > 0),
        _ind("Deliveries failed, last 24 hours", failed, warn=failed > 0),
    ]
    return AreaHealth(
        key="integrations", label="Integrations", status=_status(indicators), indicators=indicators
    )


async def control(session: AsyncSession, now: Any) -> AreaHealth:
    day_ago = now - DAY
    pending = await _count(
        session,
        select(func.count())
        .select_from(Command)
        .where(Command.status.notin_([s.value for s in COMMAND_FINAL])),
    )
    failed = await _count(
        session,
        select(func.count())
        .select_from(Command)
        .where(Command.created_at >= day_ago, Command.status == "failed"),
    )
    expired = await _count(
        session,
        select(func.count())
        .select_from(Command)
        .where(Command.created_at >= day_ago, Command.status == "expired"),
    )
    indicators = [
        _ind("Commands in flight", pending),
        _ind("Commands refused or failed, last 24 hours", failed, warn=failed > 0),
        _ind("Commands expired, last 24 hours", expired, warn=expired > 0),
    ]
    return AreaHealth(
        key="control", label="Device control", status=_status(indicators), indicators=indicators
    )


async def exports(session: AsyncSession, now: Any) -> AreaHealth:
    day_ago = now - DAY
    queued = await _count(
        session,
        select(func.count()).select_from(ExportJob).where(ExportJob.status == ExportStatus.QUEUED),
    )
    running = await _count(
        session,
        select(func.count()).select_from(ExportJob).where(ExportJob.status == ExportStatus.RUNNING),
    )
    failed = await _count(
        session,
        select(func.count())
        .select_from(ExportJob)
        .where(ExportJob.created_at >= day_ago, ExportJob.status == ExportStatus.FAILED),
    )
    indicators = [
        _ind("Jobs queued", queued, warn=queued > 20),
        _ind("Jobs running", running),
        _ind("Jobs failed, last 24 hours", failed, warn=failed > 0),
    ]
    return AreaHealth(
        key="exports", label="Exports", status=_status(indicators), indicators=indicators
    )


async def backups(session: AsyncSession) -> AreaHealth:
    health = await assess_backups(session)
    if not health.enabled:
        indicators = [
            _ind(
                "Backups",
                "not enabled",
                warn=get_settings().environment == "production",
                link="/admin/backups",
            )
        ]
    else:
        indicators = [
            _ind(
                item.label,
                item.detail,
                warn=item.status == "stale",
                critical=item.status == "failed",
                link="/admin/backups",
            )
            for item in health.items
        ]
    return AreaHealth(
        key="backups",
        label="Backup and recovery",
        status=_status(indicators),
        indicators=indicators,
    )


async def area_health(session: AsyncSession) -> list[AreaHealth]:
    now = utc_now()
    return [
        await ingestion(session, now),
        await decoding(session, now),
        await rules(session, now),
        await integrations(session, now),
        await control(session, now),
        await exports(session, now),
        await backups(session),
    ]
