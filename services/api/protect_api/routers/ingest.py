"""Inbound HTTP push: `POST /api/v1/ingest/http/{data_source_id}` with the source's bearer token,
or `?token=` for adapters whose platform cannot set a header; optionally limited to the
platform's source addresses (`allowed_source_ips` in the source config)."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.bus import get_bus
from shared.bus import RedisStreamsBus
from shared.connectivity.channels import channel_enabled, webhook_channel_key
from shared.connectivity.registry import ADAPTERS
from shared.connectivity.transports.http import bearer_token, token_matches
from shared.database import get_session
from shared.ingest import commit_and_publish, data_source_context, store_inbound
from shared.models import DataSource
from shared.trace import ApplicationError

router = APIRouter(prefix="/ingest", tags=["ingest"])


def client_address(request: Request) -> str:
    """The caller behind the reverse proxy: the first address of X-Forwarded-For, which the
    frontend's nginx sets, else the socket peer."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


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
    adapter = ADAPTERS.get(source.adapter_key)
    if adapter is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"Unknown adapter {source.adapter_key}"
        )
    if not channel_enabled(source.channels, webhook_channel_key(source.adapter_key)):
        raise HTTPException(status.HTTP_409_CONFLICT, "The HTTP channel of this source is off")
    token = bearer_token(dict(request.headers))
    if token is None and getattr(adapter, "webhook_token_in_query", False):
        # Platforms that cannot set a header (Cloudloop) carry the token in the URL (D78).
        token = request.query_params.get("token")
    if token is None or not token_matches(token, source.webhook_token_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing bearer token")
    allowed = source.config.get("allowed_source_ips") if isinstance(source.config, dict) else None
    if allowed:
        caller = client_address(request)
        if caller not in {str(a).strip() for a in allowed}:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"Address {caller} may not post to this source"
            )
    try:
        body: Any = await request.json()
    except ValueError:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "Body is not valid JSON"
        ) from None
    context = data_source_context(source)
    headers = dict(request.headers)
    if "event" in request.query_params:  # ChirpStack HTTP integration style
        headers["x-event"] = request.query_params["event"]
    try:
        messages = adapter.parse_webhook(context, body, headers)
    except ApplicationError as error:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(error)) from None
    stored = [await store_inbound(session, source, message) for message in messages]
    await commit_and_publish(session, bus, stored)
    return IngestResponse(
        accepted=len(stored),
        source_event_ids=[s.source_event.id for s in stored],
        trace_ids=[s.trace_id for s in stored],
    )
