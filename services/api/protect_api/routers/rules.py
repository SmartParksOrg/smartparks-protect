"""Rules of a project (architecture 15): versioned documents, templates, the JSON schema for
the builder, and replay tests against history."""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.audit import record_audit
from protect_api.crud import apply_patch, flush_or_409, get_or_404
from protect_api.deps import ProjectContext, require_permission
from protect_api.pagination import Page, PageResponse, page, paginate
from protect_api.schemas.rules import (
    ReplayRequest,
    ReplayResultRead,
    RuleCreate,
    RuleDocumentUpdate,
    RuleRead,
    RuleTemplateRead,
    RuleUpdate,
    RuleVersionRead,
)
from shared.database import get_session
from shared.models import Rule, RuleVersion
from shared.permissions import Permission
from shared.rules.replay import ReplayTooLarge, replay
from shared.rules.schema import RuleDocument, json_schema
from shared.rules.templates import TEMPLATES

router = APIRouter(prefix="/projects/{project_id}/rules", tags=["rules"])


def _validate(document: dict[str, object]) -> RuleDocument:
    try:
        return RuleDocument.model_validate(document)
    except ValidationError as error:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            [{"loc": list(e["loc"]), "msg": e["msg"]} for e in error.errors()],
        ) from None


def _check_enable(doc: RuleDocument) -> None:
    reserved = doc.reserved_types()
    if reserved:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            f"Cannot enable a rule that uses reserved condition types: {', '.join(reserved)}",
        )


async def _current_version(session: AsyncSession, rule: Rule) -> RuleVersion | None:
    version: RuleVersion | None = await session.scalar(
        select(RuleVersion).where(
            RuleVersion.rule_id == rule.id, RuleVersion.version == rule.current_version
        )
    )
    return version


async def _read(session: AsyncSession, rule: Rule) -> RuleRead:
    version = await _current_version(session, rule)
    data = RuleRead.model_validate(rule)
    if version is not None:
        data.document = version.document
        try:
            data.reserved_types = RuleDocument.model_validate(version.document).reserved_types()
        except ValidationError:
            data.reserved_types = ["invalid"]
    return data


async def _project_rule(session: AsyncSession, context: ProjectContext, rule_id: uuid.UUID) -> Rule:
    rule = await get_or_404(session, Rule, rule_id, "Rule")
    if rule.project_id != context.project.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule not found")
    return rule


@router.get("/templates", response_model=list[RuleTemplateRead])
async def list_templates(
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
) -> list[RuleTemplateRead]:
    return [RuleTemplateRead(key=key, **t) for key, t in TEMPLATES.items()]


@router.get("/schema")
async def rule_schema(
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
) -> dict[str, object]:
    """JSON schema of the rule document, for the builder and for API clients."""
    return json_schema()


@router.get("", response_model=PageResponse[RuleRead])
async def list_rules(
    page: Page = Depends(page),
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> PageResponse[RuleRead]:
    rows, next_cursor = await paginate(
        session, Rule.id, select(Rule).where(Rule.project_id == context.project.id), page
    )
    return PageResponse(items=[await _read(session, r) for r in rows], next_cursor=next_cursor)


@router.post("", response_model=RuleRead, status_code=status.HTTP_201_CREATED)
async def create_rule(
    body: RuleCreate,
    context: ProjectContext = Depends(require_permission(Permission.RULES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> RuleRead:
    doc = _validate(body.document)
    if body.enabled:
        _check_enable(doc)
    rule = Rule(
        project_id=context.project.id,
        name=body.name,
        description=body.description,
        enabled=body.enabled,
        current_version=1,
    )
    session.add(rule)
    await flush_or_409(session, "Rule")
    session.add(
        RuleVersion(
            rule_id=rule.id,
            version=1,
            document=doc.model_dump(mode="json", by_alias=True, exclude_none=True),
            created_by_user_id=context.user.id,
        )
    )
    await session.flush()
    await record_audit(
        session,
        user=context.user,
        action="rule.created",
        object_type="rule",
        object_id=str(rule.id),
        project_id=context.project.id,
        details={"name": rule.name, "enabled": rule.enabled},
    )
    await session.commit()
    return await _read(session, rule)


@router.post("/test-document", response_model=ReplayResultRead)
async def test_document(
    body: ReplayRequest,
    context: ProjectContext = Depends(require_permission(Permission.RULES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> ReplayResultRead:
    """Replay an unsaved document over the project's history (architecture 15.5)."""
    if body.document is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "document is required")
    doc = _validate(body.document)
    return await _replay(session, context, doc, body, "draft")


@router.get("/{rule_id}", response_model=RuleRead)
async def get_rule(
    rule_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> RuleRead:
    return await _read(session, await _project_rule(session, context, rule_id))


@router.patch("/{rule_id}", response_model=RuleRead)
async def update_rule(
    rule_id: uuid.UUID,
    body: RuleUpdate,
    context: ProjectContext = Depends(require_permission(Permission.RULES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> RuleRead:
    rule = await _project_rule(session, context, rule_id)
    if body.enabled:
        version = await _current_version(session, rule)
        if version is not None:
            _check_enable(_validate(version.document))
    changed = apply_patch(rule, body)
    await flush_or_409(session, "Rule")
    await record_audit(
        session,
        user=context.user,
        action="rule.updated",
        object_type="rule",
        object_id=str(rule.id),
        project_id=context.project.id,
        details=changed,
    )
    await session.commit()
    return await _read(session, rule)


@router.put("/{rule_id}/document", response_model=RuleRead)
async def update_document(
    rule_id: uuid.UUID,
    body: RuleDocumentUpdate,
    context: ProjectContext = Depends(require_permission(Permission.RULES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> RuleRead:
    """A new immutable version. Events keep referencing the version that created them."""
    rule = await _project_rule(session, context, rule_id)
    doc = _validate(body.document)
    if rule.enabled:
        _check_enable(doc)
    rule.current_version += 1
    session.add(
        RuleVersion(
            rule_id=rule.id,
            version=rule.current_version,
            document=doc.model_dump(mode="json", by_alias=True, exclude_none=True),
            created_by_user_id=context.user.id,
        )
    )
    await session.flush()
    await record_audit(
        session,
        user=context.user,
        action="rule.version_created",
        object_type="rule",
        object_id=str(rule.id),
        project_id=context.project.id,
        details={"version": rule.current_version},
    )
    await session.commit()
    return await _read(session, rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: uuid.UUID,
    context: ProjectContext = Depends(require_permission(Permission.RULES_WRITE)),
    session: AsyncSession = Depends(get_session),
) -> None:
    rule = await _project_rule(session, context, rule_id)
    await record_audit(
        session,
        user=context.user,
        action="rule.deleted",
        object_type="rule",
        object_id=str(rule.id),
        project_id=context.project.id,
        details={"name": rule.name},
    )
    await session.delete(rule)
    await session.commit()


@router.get("/{rule_id}/versions", response_model=list[RuleVersionRead])
async def list_versions(
    rule_id: uuid.UUID,
    limit: int = Query(50, ge=1, le=200),
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> list[RuleVersion]:
    rule = await _project_rule(session, context, rule_id)
    rows = await session.scalars(
        select(RuleVersion)
        .where(RuleVersion.rule_id == rule.id)
        .order_by(RuleVersion.version.desc())
        .limit(limit)
    )
    return list(rows)


@router.post("/{rule_id}/test", response_model=ReplayResultRead)
async def test_rule(
    rule_id: uuid.UUID,
    body: ReplayRequest,
    context: ProjectContext = Depends(require_permission(Permission.PROJECT_READ)),
    session: AsyncSession = Depends(get_session),
) -> ReplayResultRead:
    """Replay a saved version over history without creating anything."""
    rule = await _project_rule(session, context, rule_id)
    version = await session.scalar(
        select(RuleVersion).where(
            RuleVersion.rule_id == rule.id,
            RuleVersion.version == (body.version or rule.current_version),
        )
    )
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Rule version not found")
    return await _replay(session, context, _validate(version.document), body, rule.name)


async def _replay(
    session: AsyncSession,
    context: ProjectContext,
    doc: RuleDocument,
    body: ReplayRequest,
    rule_name: str,
) -> ReplayResultRead:
    try:
        result = await replay(
            session, context.project.id, doc, body.time_from, body.time_to, rule_name=rule_name
        )
    except ReplayTooLarge as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    return ReplayResultRead.model_validate(result, from_attributes=True)
