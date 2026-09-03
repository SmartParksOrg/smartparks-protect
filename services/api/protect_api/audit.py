"""Audit log writer. Every mutating admin action calls `record_audit` in the same transaction."""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from shared.enums import ActorType
from shared.logger import request_id_var, trace_id_var
from shared.models import AuditLog, User


async def record_audit(
    session: AsyncSession,
    *,
    user: User | None,
    action: str,
    object_type: str,
    object_id: str | None = None,
    project_id: uuid.UUID | None = None,
    details: dict[str, Any] | None = None,
    actor_type: ActorType = ActorType.USER,
) -> AuditLog:
    trace = trace_id_var.get()
    entry = AuditLog(
        actor_type=actor_type,
        user_id=user.id if user is not None else None,
        project_id=project_id,
        action=action,
        object_type=object_type,
        object_id=object_id,
        details=details or {},
        request_id=request_id_var.get(),
        trace_id=uuid.UUID(trace) if trace else None,
    )
    session.add(entry)
    return entry
