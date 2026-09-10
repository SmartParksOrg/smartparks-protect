"""Inbound HTTP push: `POST /api/v1/ingest/http/{data_source_id}` with the source's bearer token,
or `?token=` for adapters whose platform cannot set a header, or the platform's own signature
verified by the adapter (`verify_webhook`, ThingPark's Token, decision D95); optionally limited
to the platform's source addresses (`allowed_source_ips` in the source config)."""

import uuid
from typing import Any
from urllib.parse import parse_qs

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from protect_api.bus import get_bus
from shared.bus import RedisStreamsBus
from shared.connectivity.channels import channel_enabled, webhook_channel_key
from shared.connectivity.registry import ADAPTERS
from shared.connectivity.transports.http import raw_query_params, webhook_authenticated
from shared.database import get_session
from shared.ingest import commit_and_publish, data_source_context, store_inbound
from shared.models import DataSource
from shared.trace import ApplicationError

router = APIRouter(prefix="/ingest", tags=["ingest"])

FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"


def client_address(request: Request) -> str:
    """The caller as the reverse proxy saw it: `X-Real-IP`, which nginx sets from the socket
    (the server's `proxy_params`), else the last address of `X-Forwarded-For`, the one the
    proxy appended (`$proxy_add_x_forwarded_for`; the frontend's nginx and the server's both
    append), else the socket peer. The first address of the forwarded list is whatever the
    caller sent and passed an address allow-list with a forged header (seen on 2026-09-10)."""
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
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
    # Platforms that cannot set a header (Cloudloop, D78) or send one header map to every URL
    # (ChirpStack, D127) may carry the token in the URL.
    authenticated = webhook_authenticated(
        dict(request.headers),
        dict(request.query_params),
        source.webhook_token_hash,
        token_in_query=bool(getattr(adapter, "webhook_token_in_query", False)),
    )
    verify = getattr(adapter, "verify_webhook", None)
    if not authenticated and verify is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or missing bearer token")
    allowed = source.config.get("allowed_source_ips") if isinstance(source.config, dict) else None
    if allowed:
        caller = client_address(request)
        if caller not in {str(a).strip() for a in allowed}:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"Address {caller} may not post to this source"
            )
    body: Any
    if request.headers.get("content-type", "").split(";")[0].strip() == FORM_CONTENT_TYPE:
        # Rock7 posts its fields as a form (and Cloudloop's Core shape may too): one value each
        body = {
            key: values[-1]
            for key, values in parse_qs(
                (await request.body()).decode("utf-8", errors="replace"), keep_blank_values=True
            ).items()
        }
    else:
        try:
            body = await request.json()
        except ValueError:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, "Body is not valid JSON"
            ) from None
    context = data_source_context(source)
    headers = dict(request.headers)
    # Without a valid bearer, a platform that signed the push itself is checked by the adapter
    # with the source's credentials (ThingPark hashes the unencoded query, hence the raw parser).
    if (
        not authenticated
        and verify is not None
        and not verify(context, body, headers, raw_query_params(request.url.query))
    ):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid or missing bearer token, and the platform's own token did not verify",
        )
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
