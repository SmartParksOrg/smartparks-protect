"""Outbound integrations per project (architecture 18): connectors, integrations, the delivery
log with request and response inspection, retry, test sends and backfill requests."""

import uuid
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.bus import get_bus
from protect_api.crud import flush_or_409, get_or_404
from protect_api.deps import ProjectContext, require_permission
from protect_api.pagination import Page, PageResponse, page, paginate
from protect_api.schemas.integrations import (
    BackfillRequest,
    DeploymentRead,
    DeviceIntegrationRead,
    EntityIntegrationRead,
    IntegrationCreate,
    IntegrationDeliveryDetail,
    IntegrationDeliveryRead,
    IntegrationDetail,
    IntegrationRead,
    IntegrationSubjectOptions,
    IntegrationSubjectRead,
    IntegrationSubjects,
    IntegrationSubjectWrite,
    IntegrationTestRequest,
    IntegrationTestResult,
    IntegrationUpdate,
    LoginCodeRequest,
    LoginRead,
    LoginRequest,
    SubjectChoiceRead,
    TargetStatus,
)
from shared.bus import RedisStreamsBus, Topic
from shared.database import get_session
from shared.enums import (
    BackfillStatus,
    DeliveryOrigin,
    DeliveryStatus,
    DeploymentState,
    SubjectState,
)
from shared.integrations.base import (
    CodeLogin,
    PermanentFailure,
    Skipped,
    SubjectRegistrar,
    SubjectStatus,
    TransientFailure,
)
from shared.integrations.deliveries import (
    curated_ref,
    delivery_counts,
    enqueue,
    integration_context,
    requeue,
)
from shared.integrations.deployments import confirm, decline, rewritten_by
from shared.integrations.registry import CONNECTORS, describe_connector
from shared.integrations.subjects import (
    integrate,
    load_subject,
    load_subjects,
    registrar_of,
    stop,
)
from shared.models import (
    Device,
    DeviceEntityAssignment,
    DeviceProjectAssignment,
    Entity,
    EntityCurrentState,
    Integration,
    IntegrationDelivery,
    IntegrationDeployment,
    IntegrationSubject,
)
from shared.permissions import Permission
from shared.secrets import encrypt_json
from shared.timeutil import utc_now

router = APIRouter(prefix="/projects/{project_id}/integrations", tags=["integrations"])

MAX_BACKFILL_DAYS = 400


def _read(integration: Integration) -> IntegrationRead:
    data = IntegrationRead.model_validate(integration)
    data.has_credentials = integration.credentials_encrypted is not None
    return data


async def _integration(
    session: AsyncSession, project_id: uuid.UUID, integration_id: uuid.UUID
) -> Integration:
    integration = await get_or_404(session, Integration, integration_id, "Integration")
    if integration.project_id != project_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Integration not found")
    return integration


def _check_connector(key: str, object_types: list[Any]) -> None:
    connector = CONNECTORS.get(key)
    if connector is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"unknown connector {key}; known: {sorted(CONNECTORS)}",
        )
    unsupported = [str(t) for t in object_types if str(t) not in connector.supports]
    if unsupported:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{connector.label} cannot receive {', '.join(unsupported)}",
        )


@router.get("/connectors", response_model=list[dict[str, Any]])
async def list_connectors(
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
) -> list[dict[str, Any]]:
    return [describe_connector(c) for c in CONNECTORS.values()]


@router.get("", response_model=PageResponse[IntegrationRead])
async def list_integrations(
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    page: Page = Depends(page),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[IntegrationRead]:
    rows, next_cursor = await paginate(
        session,
        Integration.id,
        select(Integration).where(Integration.project_id == context.project.id),
        page,
    )
    return PageResponse(items=[_read(r) for r in rows], next_cursor=next_cursor)


@router.post("", response_model=IntegrationRead, status_code=status.HTTP_201_CREATED)
async def create_integration(
    body: IntegrationCreate,
    context: ProjectContext = Depends(require_permission(Permission.INTEGRATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> IntegrationRead:
    _check_connector(body.connector_key, body.object_types)
    integration = Integration(
        project_id=context.project.id,
        name=body.name,
        description=body.description,
        connector_key=body.connector_key,
        enabled=body.enabled,
        config=body.config,
        credentials_encrypted=encrypt_json(body.credentials) if body.credentials else None,
        object_types=[str(t) for t in body.object_types],
        entity_ids=[str(i) for i in body.entity_ids],
        device_ids=[str(i) for i in body.device_ids],
        event_types=[t.upper() for t in body.event_types],
        metric_keys=body.metric_keys,
        min_severity=body.min_severity,
        max_object_age_seconds=body.max_object_age_seconds,
        created_by_user_id=context.user.id,
    )
    session.add(integration)
    await flush_or_409(session, "Integration")
    await record_audit(
        session,
        user=context.user,
        action="integration.create",
        object_type="integration",
        object_id=str(integration.id),
        project_id=context.project.id,
        details={"name": integration.name, "connector": integration.connector_key},
    )
    await session.commit()
    return _read(integration)


@router.get("/deliveries", response_model=PageResponse[IntegrationDeliveryRead])
async def list_deliveries(
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    page: Page = Depends(page),
    integration_id: uuid.UUID | None = Query(None),
    delivery_status: DeliveryStatus | None = Query(None, alias="status"),
    object_type: str | None = Query(None),
    stale: bool | None = Query(None, description="Only deliveries a curation made stale"),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[IntegrationDeliveryRead]:
    statement = select(IntegrationDelivery).where(
        IntegrationDelivery.project_id == context.project.id
    )
    if stale:
        statement = statement.where(IntegrationDelivery.stale_at.is_not(None))
    if integration_id is not None:
        statement = statement.where(IntegrationDelivery.integration_id == integration_id)
    if delivery_status is not None:
        statement = statement.where(IntegrationDelivery.status == delivery_status)
    if object_type is not None:
        statement = statement.where(IntegrationDelivery.object_type == object_type)
    cursor = None
    if page.cursor is not None:
        try:
            cursor = datetime.fromisoformat(page.cursor)
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "Invalid cursor") from None
        statement = statement.where(IntegrationDelivery.created_at < cursor)
    rows = list(
        (
            await session.scalars(
                statement.order_by(IntegrationDelivery.created_at.desc()).limit(page.limit + 1)
            )
        ).all()
    )
    next_cursor = rows[page.limit - 1].created_at.isoformat() if len(rows) > page.limit else None
    return PageResponse(
        items=[IntegrationDeliveryRead.model_validate(r) for r in rows[: page.limit]],
        next_cursor=next_cursor,
    )


@router.get("/deliveries/{delivery_id}", response_model=IntegrationDeliveryDetail)
async def get_delivery(
    delivery_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> IntegrationDeliveryDetail:
    delivery = await get_or_404(session, IntegrationDelivery, delivery_id, "Delivery")
    if delivery.project_id != context.project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Delivery not found")
    return IntegrationDeliveryDetail.model_validate(delivery)


@router.post("/deliveries/{delivery_id}/retry", response_model=IntegrationDeliveryRead)
async def retry_delivery(
    delivery_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.INTEGRATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> IntegrationDeliveryRead:
    delivery = await get_or_404(session, IntegrationDelivery, delivery_id, "Delivery")
    if delivery.project_id != context.project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Delivery not found")
    if delivery.status == DeliveryStatus.SENT:
        raise HTTPException(status.HTTP_409_CONFLICT, "Delivery was sent already")
    requeue(delivery)
    await session.commit()
    return IntegrationDeliveryRead.model_validate(delivery)


@router.post("/deliveries/{delivery_id}/resend", response_model=IntegrationDeliveryRead)
async def resend_delivery(
    delivery_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.INTEGRATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> IntegrationDeliveryRead:
    """Send the corrected object again (architecture 28.10, decision D82): a new delivery with
    the object's current curation version; the stale flag on the old one is cleared."""
    delivery = await get_or_404(session, IntegrationDelivery, delivery_id, "Delivery")
    if delivery.project_id != context.project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Delivery not found")
    integration = await session.get(Integration, delivery.integration_id)
    if integration is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The integration no longer exists")
    ref = await curated_ref(session, delivery)
    if ref is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "The object no longer exists")
    if ref.object_version <= delivery.object_version:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "This version of the object was delivered already"
        )
    if ref.project_id != integration.project_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "The corrected record now belongs to another project; this integration cannot "
            "resend it",
        )
    queued = await enqueue(
        session, [integration], [ref], origin=DeliveryOrigin.RETRY, honour_age=False
    )
    delivery.stale_at = None
    delivery.stale_reason = None
    await record_audit(
        session,
        user=context.user,
        action="integration_delivery.resent",
        object_type="integration_delivery",
        object_id=str(delivery.id),
        project_id=context.project.id,
        details={"object_version": ref.object_version, "queued": queued},
    )
    await session.commit()
    new = await session.scalar(
        select(IntegrationDelivery).where(
            IntegrationDelivery.integration_id == integration.id,
            IntegrationDelivery.object_type == ref.object_type,
            IntegrationDelivery.object_id == ref.object_id,
            IntegrationDelivery.object_version == ref.object_version,
        )
    )
    return IntegrationDeliveryRead.model_validate(new or delivery)


@router.get("/{integration_id}", response_model=IntegrationDetail)
async def get_integration(
    integration_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> IntegrationDetail:
    integration = await _integration(session, context.project.id, integration_id)
    data = IntegrationDetail(**_read(integration).model_dump())
    data.counts = await delivery_counts(session, integration.id)
    data.counts_24h = await delivery_counts(
        session, integration.id, since=utc_now() - timedelta(hours=24)
    )
    return data


async def _config_of_signed_in(
    session: AsyncSession, integration: Integration, wanted: dict[str, Any]
) -> dict[str, Any]:
    """The configuration of an integration that signs in by itself (decisions D414 and D415).
    Who is signed in is the sign-in's to write, never a form's. Another server knows nothing
    of this sign-in, so a changed address signs the integration out; and it knows nothing of
    the entities registered on the first one, so the change is refused while any is
    integrated: a second server is a second integration."""
    current = dict(integration.config or {})
    config = {k: v for k, v in wanted.items() if k != "account"}
    if config.get("base_url") == current.get("base_url"):
        if current.get("account"):
            config["account"] = current["account"]
        return config
    integrated = await session.scalar(
        select(func.count())
        .select_from(IntegrationSubject)
        .where(IntegrationSubject.integration_id == integration.id)
    )
    if integrated:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"{integrated} entities are integrated with this server. Stop them first, or "
            "make a second integration for the other server.",
        )
    integration.credentials_encrypted = None
    return config


@router.patch("/{integration_id}", response_model=IntegrationRead)
async def update_integration(
    integration_id: uuid.UUID,
    body: IntegrationUpdate,
    context: ProjectContext = Depends(require_permission(Permission.INTEGRATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> IntegrationRead:
    integration = await _integration(session, context.project.id, integration_id)
    patch = body.model_dump(exclude_unset=True)
    credentials = patch.pop("credentials", None)
    if "object_types" in patch and patch["object_types"] is not None:
        _check_connector(integration.connector_key, patch["object_types"])
        patch["object_types"] = [str(t) for t in patch["object_types"]]
    for key in ("entity_ids", "device_ids"):
        if patch.get(key) is not None:
            patch[key] = [str(i) for i in patch[key]]
    if patch.get("event_types") is not None:
        patch["event_types"] = [t.upper() for t in patch["event_types"]]
    if patch.get("config") is not None and isinstance(
        CONNECTORS.get(integration.connector_key), CodeLogin
    ):
        patch["config"] = await _config_of_signed_in(session, integration, patch["config"])
    for key, value in patch.items():
        setattr(integration, key, value)
    if credentials:
        integration.credentials_encrypted = encrypt_json(credentials)
    await flush_or_409(session, "Integration")
    await record_audit(
        session,
        user=context.user,
        action="integration.update",
        object_type="integration",
        object_id=str(integration.id),
        project_id=context.project.id,
        details={"fields": sorted(patch) + (["credentials"] if credentials else [])},
    )
    await session.commit()
    return _read(integration)


@router.delete("/{integration_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_integration(
    integration_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.INTEGRATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> None:
    integration = await _integration(session, context.project.id, integration_id)
    await record_audit(
        session,
        user=context.user,
        action="integration.delete",
        object_type="integration",
        object_id=str(integration.id),
        project_id=context.project.id,
        details={"name": integration.name},
    )
    await session.delete(integration)
    await session.commit()


async def _test_location(
    session: AsyncSession, project_id: uuid.UUID, body: IntegrationTestRequest
) -> tuple[float, float] | None:
    if body.latitude is not None and body.longitude is not None:
        return (body.latitude, body.longitude)
    current = await session.scalar(
        select(EntityCurrentState)
        .where(
            EntityCurrentState.project_id == project_id,
            EntityCurrentState.latest_position.is_not(None),
        )
        .order_by(EntityCurrentState.latest_position_time.desc())
        .limit(1)
    )
    if current is None or current.latest_position is None:
        return None
    from geoalchemy2.shape import to_shape

    point = to_shape(current.latest_position)
    return (point.y, point.x)


@router.post("/{integration_id}/test", response_model=IntegrationTestResult)
async def test_integration(
    integration_id: uuid.UUID,
    body: IntegrationTestRequest,
    context: ProjectContext = Depends(require_permission(Permission.INTEGRATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> IntegrationTestResult:
    integration = await _integration(session, context.project.id, integration_id)
    connector = CONNECTORS.get(integration.connector_key)
    if connector is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "unknown connector")
    location = await _test_location(session, context.project.id, body)
    try:
        response = await connector.test(integration_context(integration), location)
    except (PermanentFailure, TransientFailure, Skipped) as exc:
        integration.last_error = str(exc)
        integration.last_error_at = utc_now()
        await session.commit()
        return IntegrationTestResult(ok=False, detail=str(exc))
    integration.last_error = None
    await session.commit()
    return IntegrationTestResult(
        ok=True, detail=f"{connector.label} accepted the test", response=response
    )


def _login(integration: Integration) -> CodeLogin:
    connector = CONNECTORS.get(integration.connector_key)
    if not isinstance(connector, CodeLogin):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"{integration.connector_key} has no sign-in with a code",
        )
    return connector


@router.post("/{integration_id}/login/code", status_code=status.HTTP_204_NO_CONTENT)
async def request_login_code(
    integration_id: uuid.UUID,
    body: LoginCodeRequest,
    context: ProjectContext = Depends(require_permission(Permission.INTEGRATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Ask the target to mail a sign-in code to the account's address (decision D414)."""
    integration = await _integration(session, context.project.id, integration_id)
    connector = _login(integration)
    try:
        await connector.request_code(integration_context(integration), str(body.email))
    except (PermanentFailure, TransientFailure) as exc:
        raise _target_refused(exc) from None


@router.post("/{integration_id}/login", response_model=LoginRead)
async def login_integration(
    integration_id: uuid.UUID,
    body: LoginRequest,
    context: ProjectContext = Depends(require_permission(Permission.INTEGRATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> LoginRead:
    """Sign the integration in with the code from the email (decision D414): Protect trades
    it for the target's credentials and stores them encrypted. Nobody sees or copies a token;
    the answer names the account and what it may do."""
    integration = await _integration(session, context.project.id, integration_id)
    connector = _login(integration)
    try:
        result = await connector.exchange_code(
            integration_context(integration), str(body.email), body.code
        )
    except (PermanentFailure, TransientFailure) as exc:
        raise _target_refused(exc) from None
    integration.credentials_encrypted = encrypt_json(result.credentials)
    # who is signed in is no secret and is shown on the integration
    integration.config = {**(integration.config or {}), "account": result.account}
    integration.last_error = None
    await record_audit(
        session,
        user=context.user,
        action="integration.signed_in",
        object_type="integration",
        object_id=str(integration.id),
        project_id=context.project.id,
        details={"account": result.account, "scopes": result.scopes},
    )
    await session.commit()
    return LoginRead(account=result.account, scopes=result.scopes)


@router.post("/{integration_id}/backfill", response_model=IntegrationRead)
async def request_backfill(
    integration_id: uuid.UUID,
    body: BackfillRequest,
    context: ProjectContext = Depends(require_permission(Permission.INTEGRATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> IntegrationRead:
    integration = await _integration(session, context.project.id, integration_id)
    if body.time_to <= body.time_from:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "time_to must be after time_from"
        )
    if body.time_to - body.time_from > timedelta(days=MAX_BACKFILL_DAYS):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"a backfill covers at most {MAX_BACKFILL_DAYS} days",
        )
    if integration.backfill.get("status") in (BackfillStatus.QUEUED, BackfillStatus.RUNNING):
        raise HTTPException(status.HTTP_409_CONFLICT, "a backfill is running already")
    integration.backfill = {
        "status": BackfillStatus.QUEUED,
        "from": body.time_from.isoformat(),
        "to": body.time_to.isoformat(),
        "queued": 0,
        "scanned": 0,
        "requested_at": utc_now().isoformat(),
        "requested_by": str(context.user.id),
    }
    await record_audit(
        session,
        user=context.user,
        action="integration.backfill",
        object_type="integration",
        object_id=str(integration.id),
        project_id=context.project.id,
        details={"from": body.time_from.isoformat(), "to": body.time_to.isoformat()},
    )
    await session.commit()
    await bus.publish(
        Topic.INTEGRATION_BACKFILL_REQUESTED,
        {
            "integration_id": str(integration.id),
            "from": body.time_from.isoformat(),
            "to": body.time_to.isoformat(),
        },
    )
    return _read(integration)


def _target(status: SubjectStatus | None) -> TargetStatus | None:
    if status is None:
        return None
    return TargetStatus(
        registered=status.registered,
        sensor_id=status.sensor_id,
        external_id=status.external_id,
        external_name=status.external_name,
        since=status.since,
        elsewhere=status.elsewhere,
    )


async def _subject_reads(
    session: AsyncSession, rows: Sequence[IntegrationSubject]
) -> list[IntegrationSubjectRead]:
    """The rows with their entities' names and what still waits of each history."""
    if not rows:
        return []
    names: dict[uuid.UUID, str] = {
        entity_id: name
        for entity_id, name in (
            await session.execute(
                select(Entity.id, Entity.name).where(Entity.id.in_({r.entity_id for r in rows}))
            )
        ).all()
    }
    waiting: dict[tuple[uuid.UUID, uuid.UUID | None], int] = {}
    sending = [r for r in rows if r.state == SubjectState.SENDING_HISTORY]
    if sending:
        for integration_id, entity_id, count in (
            await session.execute(
                select(
                    IntegrationDelivery.integration_id,
                    IntegrationDelivery.entity_id,
                    func.count(),
                )
                .where(
                    IntegrationDelivery.integration_id.in_({r.integration_id for r in sending}),
                    IntegrationDelivery.entity_id.in_({r.entity_id for r in sending}),
                    IntegrationDelivery.origin == DeliveryOrigin.BACKFILL,
                    IntegrationDelivery.status == DeliveryStatus.QUEUED,
                )
                .group_by(IntegrationDelivery.integration_id, IntegrationDelivery.entity_id)
            )
        ).all():
            waiting[(integration_id, entity_id)] = int(count)
    return [
        IntegrationSubjectRead(
            integration_id=row.integration_id,
            entity_id=row.entity_id,
            entity_name=str(names.get(row.entity_id, "")),
            state=row.state,
            detail=row.detail,
            species_id=(row.settings or {}).get("species_id"),
            species_name=(row.settings or {}).get("species_name"),
            history_from=row.history_from,
            history_queued=row.history_queued,
            history_waiting=waiting.get((row.integration_id, row.entity_id), 0),
            external_id=row.external_id,
            registered_at=row.registered_at,
            created_at=row.created_at,
        )
        for row in sorted(rows, key=lambda r: str(names.get(r.entity_id, "")).lower())
    ]


async def _deployment_reads(
    session: AsyncSession, rows: Sequence[IntegrationDeployment]
) -> list[DeploymentRead]:
    """The rows with their names, newest first; which is still the device's open deployment
    on the target; and for one that waits, how many finished ones sending it would rewrite."""
    if not rows:
        return []
    entities: dict[uuid.UUID, str] = {
        entity_id: name
        for entity_id, name in (
            await session.execute(
                select(Entity.id, Entity.name).where(Entity.id.in_({r.entity_id for r in rows}))
            )
        ).all()
    }
    devices: dict[uuid.UUID, str] = {
        device_id: name
        for device_id, name in (
            await session.execute(
                select(Device.id, Device.name).where(Device.id.in_({r.device_id for r in rows}))
            )
        ).all()
    }
    latest: dict[tuple[uuid.UUID, uuid.UUID], datetime] = {
        (integration_id, device_id): start
        for integration_id, device_id, start in (
            await session.execute(
                select(
                    IntegrationDeployment.integration_id,
                    IntegrationDeployment.device_id,
                    func.max(IntegrationDeployment.starts_at),
                )
                .where(
                    IntegrationDeployment.integration_id.in_({r.integration_id for r in rows}),
                    IntegrationDeployment.device_id.in_({r.device_id for r in rows}),
                    IntegrationDeployment.state == DeploymentState.SENT,
                )
                .group_by(IntegrationDeployment.integration_id, IntegrationDeployment.device_id)
            )
        ).all()
    }
    reads = []
    for row in sorted(rows, key=lambda r: r.starts_at, reverse=True):
        waiting = row.state in (DeploymentState.PENDING, DeploymentState.REFUSED)
        reads.append(
            DeploymentRead(
                id=row.id,
                integration_id=row.integration_id,
                entity_id=row.entity_id,
                entity_name=str(entities.get(row.entity_id, "")),
                device_id=row.device_id,
                device_name=str(devices.get(row.device_id, "")),
                sensor_id=row.sensor_id,
                starts_at=row.starts_at,
                ends_at=row.ends_at,
                state=row.state,
                detail=row.detail,
                animal_id=row.animal_id,
                sent_at=row.sent_at,
                open_on_target=row.state == DeploymentState.SENT
                and latest.get((row.integration_id, row.device_id)) == row.starts_at,
                rewrites=await rewritten_by(session, row) if waiting else 0,
            )
        )
    return reads


MAX_DEPLOYMENT_ROWS = 200


def _target_refused(exc: Exception) -> HTTPException:
    """A target that refuses or cannot be reached is not our caller's malformed request."""
    code = (
        status.HTTP_422_UNPROCESSABLE_CONTENT
        if isinstance(exc, PermanentFailure)
        else status.HTTP_502_BAD_GATEWAY
    )
    return HTTPException(code, str(exc))


def _registrar(integration: Integration) -> SubjectRegistrar:
    try:
        return registrar_of(integration)
    except PermanentFailure as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None


@router.get("/by-entity/{entity_id}", response_model=list[EntityIntegrationRead])
async def entity_integrations(
    entity_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[EntityIntegrationRead]:
    """The project's integrations that register their entities, as this entity stands with
    each (decision D412): the card on the entity page. Protect's own account, the target is
    not asked. Bounded by the project's integrations."""
    entity = await session.get(Entity, entity_id)
    if (
        entity is None
        or entity.project_id != context.project.id
        or not context.visibility.entity_visible(entity.id)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Entity not found")
    integrations = [
        i
        for i in await session.scalars(
            select(Integration)
            .where(Integration.project_id == context.project.id)
            .order_by(Integration.name)
        )
        if isinstance(CONNECTORS.get(i.connector_key), SubjectRegistrar)
    ]
    rows = (
        list(
            await session.scalars(
                select(IntegrationSubject).where(
                    IntegrationSubject.entity_id == entity_id,
                    IntegrationSubject.integration_id.in_([i.id for i in integrations]),
                )
            )
        )
        if integrations
        else []
    )
    reads = {r.integration_id: r for r in await _subject_reads(session, rows)}
    deployments: dict[uuid.UUID, list[DeploymentRead]] = {}
    if integrations:
        for read in await _deployment_reads(
            session,
            list(
                await session.scalars(
                    select(IntegrationDeployment)
                    .where(
                        IntegrationDeployment.entity_id == entity_id,
                        IntegrationDeployment.integration_id.in_([i.id for i in integrations]),
                    )
                    .order_by(IntegrationDeployment.starts_at.desc())
                    .limit(MAX_DEPLOYMENT_ROWS)
                )
            ),
        ):
            deployments.setdefault(read.integration_id, []).append(read)
    return [
        EntityIntegrationRead(
            integration_id=i.id,
            name=i.name,
            connector_key=i.connector_key,
            connector_label=CONNECTORS[i.connector_key].label,
            enabled=i.enabled,
            subject=reads.get(i.id),
            deployments=deployments.get(i.id, []),
        )
        for i in integrations
    ]


@router.get("/by-device/{device_id}", response_model=list[DeviceIntegrationRead])
async def device_integrations(
    device_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[DeviceIntegrationRead]:
    """The project's integrations that register their entities, as this device sees them
    (decision D418): the entity it is on now with how that entity stands, and the device's
    deployments on each target. Protect's own account, the target is not asked. Bounded by
    the project's integrations and 200 deployments."""
    in_project = await session.scalar(
        select(DeviceProjectAssignment.id)
        .where(
            DeviceProjectAssignment.device_id == device_id,
            DeviceProjectAssignment.project_id == context.project.id,
        )
        .limit(1)
    )
    if in_project is None or not context.visibility.device_visible(device_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Device not found")
    integrations = [
        i
        for i in await session.scalars(
            select(Integration)
            .where(Integration.project_id == context.project.id)
            .order_by(Integration.name)
        )
        if isinstance(CONNECTORS.get(i.connector_key), SubjectRegistrar)
    ]
    if not integrations:
        return []
    on = (
        await session.execute(
            select(Entity.id, Entity.name)
            .join(DeviceEntityAssignment, DeviceEntityAssignment.entity_id == Entity.id)
            .where(
                DeviceEntityAssignment.device_id == device_id,
                DeviceEntityAssignment.validity.op("@>")(utc_now()),
                Entity.project_id == context.project.id,
            )
            .limit(1)
        )
    ).first()
    entity_id = on[0] if on is not None and context.visibility.entity_visible(on[0]) else None
    subjects: dict[uuid.UUID, IntegrationSubjectRead] = {}
    if entity_id is not None:
        subjects = {
            r.integration_id: r
            for r in await _subject_reads(
                session,
                list(
                    await session.scalars(
                        select(IntegrationSubject).where(
                            IntegrationSubject.entity_id == entity_id,
                            IntegrationSubject.integration_id.in_([i.id for i in integrations]),
                        )
                    )
                ),
            )
        }
    deployments: dict[uuid.UUID, list[DeploymentRead]] = {}
    for read in await _deployment_reads(
        session,
        list(
            await session.scalars(
                select(IntegrationDeployment)
                .where(
                    IntegrationDeployment.device_id == device_id,
                    IntegrationDeployment.integration_id.in_([i.id for i in integrations]),
                )
                .order_by(IntegrationDeployment.starts_at.desc())
                .limit(MAX_DEPLOYMENT_ROWS)
            )
        ),
    ):
        if context.visibility.entity_visible(read.entity_id):
            deployments.setdefault(read.integration_id, []).append(read)
    return [
        DeviceIntegrationRead(
            integration_id=i.id,
            name=i.name,
            connector_key=i.connector_key,
            connector_label=CONNECTORS[i.connector_key].label,
            enabled=i.enabled,
            entity_id=entity_id,
            entity_name=on[1] if entity_id is not None and on is not None else None,
            subject=subjects.get(i.id),
            deployments=deployments.get(i.id, []),
        )
        for i in integrations
    ]


@router.get("/{integration_id}/subjects", response_model=IntegrationSubjects)
async def list_subjects(
    integration_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.INTEGRATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> IntegrationSubjects:
    """The entities integrated with this integration and what the target has for each
    (decisions D408 and D412): the overview on the integration. The target is asked with the
    integration's credentials, which is why this takes the right to change integrations.
    At most 200 entities."""
    integration = await _integration(session, context.project.id, integration_id)
    registrar = _registrar(integration)
    rows = list(
        await session.scalars(
            select(IntegrationSubject).where(IntegrationSubject.integration_id == integration.id)
        )
    )
    reads = await _subject_reads(session, rows)
    if not reads:
        return IntegrationSubjects(items=[])
    waiting = await _deployment_reads(
        session,
        list(
            await session.scalars(
                select(IntegrationDeployment)
                .where(
                    IntegrationDeployment.integration_id == integration.id,
                    IntegrationDeployment.state.in_(
                        [DeploymentState.PENDING, DeploymentState.REFUSED]
                    ),
                )
                .order_by(IntegrationDeployment.starts_at.desc())
                .limit(MAX_DEPLOYMENT_ROWS)
            )
        ),
    )
    subjects = await load_subjects(
        session,
        integration.project_id,
        [r.entity_id for r in rows],
        {r.entity_id: r.external_id for r in rows if r.external_id},
    )
    try:
        statuses = await registrar.statuses(integration_context(integration), subjects)
    except (PermanentFailure, TransientFailure) as exc:
        return IntegrationSubjects(items=reads, waiting=waiting, target_error=str(exc))
    for read in reads:
        read.target = _target(statuses.get(read.entity_id))
    return IntegrationSubjects(items=reads, waiting=waiting)


@router.get(
    "/{integration_id}/subjects/{entity_id}/options", response_model=IntegrationSubjectOptions
)
async def subject_options(
    integration_id: uuid.UUID,
    entity_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.INTEGRATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> IntegrationSubjectOptions:
    """What a user chooses from to integrate one entity (decision D413): the target's species
    with Protect's proposal, the sensor id the entity will be known by, what the target has
    for it, and why it cannot be integrated when it cannot. Read from the target."""
    integration = await _integration(session, context.project.id, integration_id)
    registrar = _registrar(integration)
    try:
        subject = await load_subject(session, integration, entity_id)
        options = await registrar.options(integration_context(integration), subject)
    except (PermanentFailure, TransientFailure) as exc:
        raise _target_refused(exc) from None
    row = await session.scalar(
        select(IntegrationSubject).where(
            IntegrationSubject.integration_id == integration.id,
            IntegrationSubject.entity_id == entity_id,
        )
    )
    reads = await _subject_reads(session, [row] if row is not None else [])
    target = _target(options.status)
    assert target is not None
    return IntegrationSubjectOptions(
        entity_id=subject.entity_id,
        entity_name=subject.entity_name,
        device_name=subject.device_name,
        assigned_from=subject.assigned_from,
        sensor_id=options.sensor_id,
        target=target,
        species=[
            SubjectChoiceRead(id=c.id, name=c.name, common_name=c.common_name)
            for c in options.species
        ],
        proposed_species_id=options.proposed_species_id,
        blocked=options.blocked,
        subject=reads[0] if reads else None,
    )


@router.put("/{integration_id}/subjects/{entity_id}", response_model=IntegrationSubjectRead)
async def integrate_entity(
    integration_id: uuid.UUID,
    entity_id: uuid.UUID,
    body: IntegrationSubjectWrite,
    context: ProjectContext = Depends(require_permission(Permission.INTEGRATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> IntegrationSubjectRead:
    """Integrate one entity (decision D412): its data is forwarded from now on, and it is
    registered on the target with the species chosen. With `history_from` its old data goes
    first, oldest first, and the registration follows the last of it (decision D409); at most
    400 days back."""
    integration = await _integration(session, context.project.id, integration_id)
    _registrar(integration)
    if body.history_from is not None:
        if body.history_from >= utc_now():
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "The history starts in the past"
            )
        if utc_now() - body.history_from > timedelta(days=MAX_BACKFILL_DAYS):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                f"A history covers at most {MAX_BACKFILL_DAYS} days",
            )
    try:
        row = await integrate(
            session,
            integration,
            entity_id,
            {"species_id": str(body.species_id), "species_name": body.species_name},
            body.history_from,
            context.user.id,
        )
    except TransientFailure as exc:
        raise _target_refused(exc) from None
    except PermanentFailure as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    await record_audit(
        session,
        user=context.user,
        action="integration.entity_integrated",
        object_type="integration",
        object_id=str(integration.id),
        project_id=context.project.id,
        details={
            "entity_id": str(entity_id),
            "species_id": str(body.species_id),
            "history_from": body.history_from.isoformat() if body.history_from else None,
            "state": str(row.state),
        },
    )
    await session.commit()
    if row.state == SubjectState.HISTORY_REQUESTED:
        await bus.publish(Topic.INTEGRATION_BACKFILL_REQUESTED, {"subject_id": str(row.id)})
    return (await _subject_reads(session, [row]))[0]


@router.delete("/{integration_id}/subjects/{entity_id}", status_code=status.HTTP_204_NO_CONTENT)
async def stop_integrating_entity(
    integration_id: uuid.UUID,
    entity_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.INTEGRATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> None:
    """Stop forwarding an entity's data to the target. What the target holds stays there:
    Protect ends and deletes nothing on a target."""
    integration = await _integration(session, context.project.id, integration_id)
    _registrar(integration)
    if not await stop(session, integration, entity_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "The entity is not integrated here")
    await record_audit(
        session,
        user=context.user,
        action="integration.entity_stopped",
        object_type="integration",
        object_id=str(integration.id),
        project_id=context.project.id,
        details={"entity_id": str(entity_id)},
    )
    await session.commit()


async def _deployment(
    session: AsyncSession, integration: Integration, deployment_id: uuid.UUID
) -> IntegrationDeployment:
    row = await session.get(IntegrationDeployment, deployment_id)
    if row is None or row.integration_id != integration.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Deployment not found")
    return row


@router.post("/{integration_id}/deployments/{deployment_id}/confirm", response_model=DeploymentRead)
async def confirm_deployment(
    integration_id: uuid.UUID,
    deployment_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.INTEGRATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> DeploymentRead:
    """Send a deployment that waits (decision D416): the device's sensor on the entity's
    animal from the start of its assignment. The target ends the sensor's deployment before
    it at that moment. The device's held readings for the entity go after it, oldest first.
    A refusal is answered with the row marked refused."""
    integration = await _integration(session, context.project.id, integration_id)
    _registrar(integration)
    row = await _deployment(session, integration, deployment_id)
    try:
        await confirm(session, integration, row, context.user.id)
    except TransientFailure as exc:
        raise _target_refused(exc) from None
    except PermanentFailure as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    await record_audit(
        session,
        user=context.user,
        action="integration.deployment_confirmed",
        object_type="integration",
        object_id=str(integration.id),
        project_id=context.project.id,
        details={
            "deployment_id": str(row.id),
            "entity_id": str(row.entity_id),
            "device_id": str(row.device_id),
            "sensor_id": row.sensor_id,
            "start": row.starts_at.isoformat(),
            "state": str(row.state),
        },
    )
    await session.commit()
    return (await _deployment_reads(session, [row]))[0]


@router.post("/{integration_id}/deployments/{deployment_id}/decline", response_model=DeploymentRead)
async def decline_deployment(
    integration_id: uuid.UUID,
    deployment_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.INTEGRATIONS_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> DeploymentRead:
    """Do not send a deployment that waits (decision D416): nothing is made on the target,
    and the device's readings of the entity in the period are not sent."""
    integration = await _integration(session, context.project.id, integration_id)
    _registrar(integration)
    row = await _deployment(session, integration, deployment_id)
    try:
        await decline(session, row, context.user.id)
    except PermanentFailure as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from None
    await record_audit(
        session,
        user=context.user,
        action="integration.deployment_declined",
        object_type="integration",
        object_id=str(integration.id),
        project_id=context.project.id,
        details={
            "deployment_id": str(row.id),
            "entity_id": str(row.entity_id),
            "device_id": str(row.device_id),
        },
    )
    await session.commit()
    return (await _deployment_reads(session, [row]))[0]
