"""The command path (architecture 17.4): one function creates, encodes, routes and submits a
command whether a person, an automation or later an MCP client asks for it. Provider events
(transmitted, acknowledged, failed) and device responses move the lifecycle forward; commands
that never reach a final state expire. Every command has an audit-class trace."""

import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.bus import Topic
from shared.connectivity.base import CommandConnector, DataSourceContext
from shared.connectivity.registry import ADAPTERS
from shared.control.actions import ControlAction, ResponseContext, actions_of
from shared.device_drivers.base import DecodedRecords
from shared.device_drivers.registry import DRIVERS
from shared.domain.assignments import resolve_attribution
from shared.enums import AcquisitionChannel, CommandStatus, ErrorCode, TraceClass
from shared.ingest import data_source_context
from shared.logger import get_logger
from shared.models import (
    Command,
    CommandExecution,
    DataSource,
    Device,
    DeviceType,
    ExternalIdentity,
    SourceEvent,
)
from shared.timeutil import utc_now
from shared.trace import ApplicationError, Tracer

log = get_logger("control")

RANK: dict[str, int] = {
    CommandStatus.CREATED: 0,
    CommandStatus.ENCODED: 1,
    CommandStatus.SUBMITTED: 2,
    CommandStatus.ACCEPTED_BY_NETWORK: 3,
    CommandStatus.QUEUED: 4,
    CommandStatus.SCHEDULED: 5,
    CommandStatus.TRANSMITTED: 6,
    CommandStatus.ACKNOWLEDGED: 7,
    CommandStatus.CONFIRMED_BY_DEVICE: 8,
    CommandStatus.FAILED: 9,
    CommandStatus.EXPIRED: 9,
}
FINAL = frozenset({CommandStatus.CONFIRMED_BY_DEVICE, CommandStatus.FAILED, CommandStatus.EXPIRED})
PENDING_FOR_DEVICE = frozenset(
    {
        CommandStatus.SUBMITTED,
        CommandStatus.ACCEPTED_BY_NETWORK,
        CommandStatus.QUEUED,
        CommandStatus.SCHEDULED,
        CommandStatus.TRANSMITTED,
        CommandStatus.ACKNOWLEDGED,
    }
)


@dataclass(frozen=True, slots=True)
class Actor:
    kind: str  # user, automation, system, mcp
    user_id: uuid.UUID | None = None
    automation_id: uuid.UUID | None = None
    event_id: uuid.UUID | None = None
    client: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "user_id": str(self.user_id) if self.user_id else None,
            "automation_id": str(self.automation_id) if self.automation_id else None,
            "event_id": str(self.event_id) if self.event_id else None,
            "client": self.client,
        }


@dataclass(slots=True)
class Route:
    source: DataSource
    context: DataSourceContext
    identity: ExternalIdentity
    connector: CommandConnector
    channel: AcquisitionChannel


@dataclass(slots=True)
class Availability:
    action: ControlAction
    available: bool
    reason: str | None


def command_connector_for(context: DataSourceContext) -> CommandConnector | None:
    adapter = ADAPTERS.get(context.adapter_key)
    factory = getattr(adapter, "command_connector", None)
    if adapter is None or factory is None:
        return None
    connector: CommandConnector | None = factory(context)
    return connector


async def driver_for(session: AsyncSession, device: Device) -> tuple[str, Any]:
    device_type = await session.get(DeviceType, device.device_type_id)
    assert device_type is not None
    return device_type.driver_key, DRIVERS.get(device_type.driver_key)


async def select_route(
    session: AsyncSession, device: Device, capability: str = "downlink"
) -> tuple[Route | None, str | None]:
    """The enabled data source that can deliver to this device: it holds an identity of the
    device, its adapter has a command connector, and its capabilities include the one the
    action needs. The identity seen most recently wins."""
    rows = (
        await session.execute(
            select(ExternalIdentity, DataSource)
            .join(DataSource, DataSource.id == ExternalIdentity.data_source_id)
            .where(
                ExternalIdentity.device_id == device.id,
                ExternalIdentity.ignored.is_(False),
                DataSource.enabled.is_(True),
            )
            .order_by(ExternalIdentity.last_seen_at.desc().nulls_last())
        )
    ).all()
    if not rows:
        return None, "the device has no identity on an enabled data source"
    reasons: list[str] = []
    for identity, source in rows:
        context = data_source_context(source)
        if not getattr(context.capabilities, capability, False):
            reasons.append(f"{source.name} has no {capability} capability")
            continue
        connector = command_connector_for(context)
        if connector is None:
            reasons.append(f"{source.name} ({source.adapter_key}) cannot send commands")
            continue
        return (
            Route(
                source=source,
                context=context,
                identity=identity,
                connector=connector,
                channel=getattr(
                    ADAPTERS.get(source.adapter_key),
                    "acquisition_channel",
                    AcquisitionChannel.OTHER,
                ),
            ),
            None,
        )
    return None, "; ".join(reasons)


async def available_actions(session: AsyncSession, device: Device) -> list[Availability]:
    _, driver = await driver_for(session, device)
    actions = actions_of(driver)
    if not actions:
        return []
    route, reason = await select_route(session, device)
    result = []
    for action in actions.values():
        if route is None:
            result.append(Availability(action, False, reason))
        elif not getattr(route.context.capabilities, action.required_capability, False):
            result.append(
                Availability(
                    action,
                    False,
                    f"{route.source.name} has no {action.required_capability} capability",
                )
            )
        else:
            result.append(Availability(action, True, None))
    return result


async def _record(
    session: AsyncSession,
    command: Command,
    status: CommandStatus,
    source: str,
    detail: dict[str, Any] | None = None,
) -> bool:
    """Move the command to `status` when that is a step forward. Returns whether it moved."""
    if command.status in FINAL or RANK[status] < RANK[command.status]:
        return False
    if status == command.status and status not in (CommandStatus.FAILED,):
        return False
    command.status = status
    command.updated_at = utc_now()
    session.add(
        CommandExecution(
            command_id=command.id, time=utc_now(), status=status, source=source, detail=detail or {}
        )
    )
    return True


def command_message(command: Command) -> tuple[str, dict[str, Any]]:
    return (
        Topic.COMMAND_UPDATED,
        {
            "command_id": str(command.id),
            "device_id": str(command.device_id),
            "project_id": str(command.project_id) if command.project_id else None,
            "entity_id": str(command.entity_id) if command.entity_id else None,
            "action_key": command.action_key,
            "status": command.status,
            "error_message": command.error_message,
        },
    )


async def request_command(
    session: AsyncSession,
    *,
    device: Device,
    action_key: str,
    parameters: dict[str, Any],
    actor: Actor,
) -> Command:
    """Create, encode, route and submit. The caller checks permissions and confirmation and
    commits afterwards. A command that cannot be delivered is stored as failed with the reason,
    so the audit trail holds the attempt."""
    driver_key, driver = await driver_for(session, device)
    action = actions_of(driver).get(action_key)
    if action is None:
        raise ApplicationError(
            code=ErrorCode.COMMAND_REJECTED,
            message=f"driver {driver_key} has no action {action_key}",
            component="control",
            user_actionable=True,
        )
    try:
        params = action.parameters.model_validate(parameters or {})
    except ValidationError as error:
        raise ApplicationError(
            code=ErrorCode.COMMAND_REJECTED,
            message=f"invalid parameters: {error.errors()[0]['msg']}",
            component="control",
            user_actionable=True,
            context={"errors": [{"loc": list(e["loc"]), "msg": e["msg"]} for e in error.errors()]},
        ) from None
    now = utc_now()
    attribution = await resolve_attribution(session, device.id, now)
    tracer = Tracer(
        session,
        root_object_type="command",
        root_object_id="pending",
        trace_class=TraceClass.COMMAND,
        project_id=attribution.project_id,
        device_id=device.id,
        actor=actor.to_dict(),
    )
    await tracer.start()
    command = Command(
        device_id=device.id,
        project_id=attribution.project_id,
        entity_id=attribution.entity_id,
        action_key=action.key,
        driver_key=driver_key,
        schema_version=action.schema_version,
        parameters=params.model_dump(mode="json"),
        status=CommandStatus.CREATED,
        actor=actor.to_dict(),
        requested_by_user_id=actor.user_id,
        automation_id=actor.automation_id,
        event_id=actor.event_id,
        trace_id=tracer.trace_id,
        expires_at=now + timedelta(seconds=action.expiry_seconds),
    )
    session.add(command)
    await session.flush()
    tracer.trace.root_object_id = str(command.id)
    session.add(
        CommandExecution(
            command_id=command.id, time=now, status=CommandStatus.CREATED, source=actor.kind
        )
    )

    try:
        async with tracer.step(
            "control", "action encoded", input_ref=f"action:{action.key}"
        ) as step:
            encoded = action.encode(params)
            command.payload_hex = encoded.payload.hex()
            command.f_port = encoded.f_port
            command.confirmed_downlink = encoded.confirmed
            step.metadata.update(
                f_port=encoded.f_port, bytes=len(encoded.payload), **encoded.metadata
            )
            step.output_ref = f"payload:{command.payload_hex}"
            await _record(
                session, command, CommandStatus.ENCODED, "control", {"f_port": encoded.f_port}
            )

        async with tracer.step("control", "route selected") as step:
            route, reason = await select_route(session, device, action.required_capability)
            if route is None:
                raise ApplicationError(
                    code=ErrorCode.COMMAND_REJECTED,
                    message=reason or "no route",
                    component="control",
                    user_actionable=True,
                )
            command.data_source_id = route.source.id
            command.external_id = route.identity.external_id
            command.route = route.channel
            step.output_ref = f"data_source:{route.source.id}"
            step.metadata.update(
                adapter=route.source.adapter_key, external_id=route.identity.external_id
            )

        async with tracer.step(
            f"adapter.{route.source.adapter_key}", "submitted to platform"
        ) as step:
            command.submitted_at = utc_now()
            await _record(session, command, CommandStatus.SUBMITTED, "control")
            try:
                response = await route.connector.submit(
                    route.identity.external_id,
                    encoded.payload,
                    {
                        "f_port": encoded.f_port,
                        "confirmed": encoded.confirmed,
                        "reference": str(command.id),
                    },
                )
            except ApplicationError:
                raise
            except Exception as exc:
                raise ApplicationError(
                    code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
                    message=f"{route.source.name}: {type(exc).__name__}: {exc}",
                    component=f"adapter.{route.source.adapter_key}",
                    retryable=True,
                ) from exc
            command.provider_ref = str(response.get("provider_ref") or "") or None
            command.provider_response = response
            step.output_ref = f"provider_ref:{command.provider_ref}"
            for status in response.get("statuses", [CommandStatus.ACCEPTED_BY_NETWORK]):
                await _record(
                    session,
                    command,
                    CommandStatus(status),
                    f"adapter:{route.source.adapter_key}",
                    {"provider_ref": command.provider_ref},
                )
    except ApplicationError as error:
        command.error_code = error.code
        command.error_message = str(error)
        await _record(
            session, command, CommandStatus.FAILED, error.component, {"error": str(error)}
        )
        await tracer.finish()
        log.warning("command failed", command_id=str(command.id), error=str(error))
        return command
    await tracer.finish()
    log.info(
        "command submitted",
        command_id=str(command.id),
        action=action.key,
        device_id=str(device.id),
        provider_ref=command.provider_ref,
    )
    return command


async def apply_provider_signal(
    session: AsyncSession, event: SourceEvent, payload: dict[str, Any]
) -> list[tuple[str, dict[str, Any]]]:
    """Network events about a queued item move the command: transmitted, acknowledged, or
    failed with the platform's description. Unknown references are ignored."""
    ref = payload.get("queueItemId") or (payload.get("context") or {}).get("queue_item_id")
    if not ref or event.data_source_id is None:
        return []
    command = await session.scalar(
        select(Command).where(
            Command.provider_ref == str(ref), Command.data_source_id == event.data_source_id
        )
    )
    if command is None:
        return []
    source = f"adapter:{event.event_type}"
    when = event.network_received_at or event.ingested_at
    moved = False
    if event.event_type == "downlink_transmitted":
        command.transmitted_at = command.transmitted_at or when
        moved = await _record(
            session,
            command,
            CommandStatus.TRANSMITTED,
            source,
            {"gateway_id": payload.get("gatewayId"), "f_cnt_down": payload.get("fCntDown")},
        )
    elif event.event_type == "downlink_ack":
        if payload.get("acknowledged", True):
            command.acknowledged_at = command.acknowledged_at or when
            moved = await _record(
                session,
                command,
                CommandStatus.ACKNOWLEDGED,
                source,
                {"f_cnt_down": payload.get("fCntDown")},
            )
        else:
            command.error_code = ErrorCode.COMMAND_REJECTED
            command.error_message = "the device did not acknowledge the confirmed downlink"
            moved = await _record(
                session, command, CommandStatus.FAILED, source, {"acknowledged": False}
            )
    elif event.event_type == "log" and str(payload.get("level", "")).upper() in ("ERROR", "FATAL"):
        command.error_code = ErrorCode.COMMAND_REJECTED
        command.error_message = str(
            payload.get("description") or payload.get("code") or "platform error"
        )
        moved = await _record(
            session, command, CommandStatus.FAILED, source, {"code": payload.get("code")}
        )
    return [command_message(command)] if moved else []


async def interpret_device_records(
    session: AsyncSession,
    device: Device,
    driver: Any,
    event: SourceEvent,
    records: DecodedRecords,
) -> list[tuple[str, dict[str, Any]]]:
    """Offer the decoded records of a later uplink to the pending commands of the device; the
    action's interpreter decides whether the device answered (decision D51)."""
    actions = actions_of(driver)
    if not any(a.interpret for a in actions.values()):
        return []
    pending = (
        await session.scalars(
            select(Command)
            .where(Command.device_id == device.id, Command.status.in_(PENDING_FOR_DEVICE))
            .order_by(Command.created_at)
        )
    ).all()
    when = event.network_received_at or event.ingested_at
    messages: list[tuple[str, dict[str, Any]]] = []
    for command in pending:
        action = actions.get(command.action_key)
        if action is None or action.interpret is None:
            continue
        if command.submitted_at is not None and when < command.submitted_at:
            continue
        result = action.interpret(
            ResponseContext(
                event_type=event.event_type, records=records, parameters=command.parameters
            )
        )
        if result is None:
            continue
        command.result = {**result.detail, "source_event_id": event.id}
        if result.confirmed:
            command.confirmed_at = when
            moved = await _record(
                session, command, CommandStatus.CONFIRMED_BY_DEVICE, "device", result.detail
            )
        else:
            command.error_code = ErrorCode.COMMAND_REJECTED
            command.error_message = str(
                result.detail.get("response") or "the device reported a failure"
            )
            moved = await _record(session, command, CommandStatus.FAILED, "device", result.detail)
        if moved:
            messages.append(command_message(command))
    return messages


async def expire_commands(session: AsyncSession) -> list[tuple[str, dict[str, Any]]]:
    now = utc_now()
    rows = (
        await session.scalars(
            select(Command).where(
                Command.status.notin_([s.value for s in FINAL]), Command.expires_at < now
            )
        )
    ).all()
    messages = []
    for command in rows:
        command.error_code = ErrorCode.COMMAND_EXPIRED
        command.error_message = f"no final state within the action's expiry ({command.expires_at})"
        if await _record(session, command, CommandStatus.EXPIRED, "expiry"):
            messages.append(command_message(command))
    return messages
