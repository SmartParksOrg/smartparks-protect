"""Inbound HTTP push: `POST /api/v1/ingest/http/{data_source_id}` with the source's bearer token."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.bus import get_bus
from shared.bus import RedisStreamsBus
from shared.connectivity.registry import ADAPTERS
from shared.connectivity.transports.http import bearer_token, token_matches
from shared.database import get_session
from shared.ingest import commit_and_publish, data_source_context, store_inbound
from shared.models import DataSource
from shared.trace import ApplicationError

router = APIRouter(prefix="/ingest", tags=["ingest"])


class IngestResponse(BaseModel):
    accepted: int
    source_event_ids: list[int]
    trace_ids: list[uuid.UUID]


@router.post(
    "/http/{data_source_id}", response_model=IngestResponse, status_code=status.HTTP_202_ACCEPTED
)
async def ingest_http(
    data_source_id: uuid.UUID,
    request: Request,
    session: AsyncSession = Depends(get_session),
    bus: RedisStreamsBus = Depends(get_bus),
) -> IngestResponse:
    source = await session.get(DataSource, data_source_id)
    if source is None or not source.enabled:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Data source not found or disabled")
    token = bearer_token(dict(request.headers))
    if token is None or not token_matches(token, source.webhook_token_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing bearer token")
    adapter = ADAPTERS.get(source.adapter_key)
    if adapter is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown adapter {source.adapter_key}"
        )
    try:
        body: Any = await request.json()
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Body is not valid JSON"
        ) from None
    context = data_source_context(source)
    try:
        messages = adapter.parse_webhook(context, body, dict(request.headers))
    except ApplicationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    stored = [await store_inbound(session, source, message) for message in messages]
    await commit_and_publish(session, bus, stored)
    return IngestResponse(
        accepted=len(stored),
        source_event_ids=[s.source_event.id for s in stored],
        trace_ids=[s.trace_id for s in stored],
    )
