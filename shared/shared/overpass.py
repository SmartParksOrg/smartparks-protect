"""The call to an Overpass API (phase 33, decision D270): the query in, the JSON
answer out, a structured failure when the server does not answer, so the route can say so.

A public Overpass server refuses a burst rather than queueing it, and a refusal arrives within
seconds, so a call that may still succeed is made once more after a short pause; the answer the
caller sees is the last attempt's. A server's final word (a 400 on a bad query, a 403) is not
repeated."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from shared.enums import ErrorCode
from shared.trace import ApplicationError
from shared.version import __version__

TIMEOUT_S = 30
USER_AGENT = f"SmartParksProtect/{__version__} (propose area)"
COMPONENT = "overpass"
#: How many times one call is attempted, the first included.
ATTEMPTS = 2
#: The pause between two attempts. Long enough for a busy server's slot, short enough that
#: somebody who clicked on the map is still waiting for an answer rather than wondering.
RETRY_PAUSE_S = 2.0
#: The answers a busy server gives, which another attempt may get past.
RETRYABLE_STATUS = (429, 502, 503, 504)


async def fetch_overpass(url: str, query: str) -> dict[str, Any]:
    """The answer to one Overpass query, or an `ApplicationError` saying why there is none."""
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        for _ in range(ATTEMPTS - 1):
            try:
                return await _attempt(client, url, query)
            except ApplicationError as error:
                if not error.retryable:
                    raise
            await asyncio.sleep(RETRY_PAUSE_S)
        return await _attempt(client, url, query)


async def _attempt(client: httpx.AsyncClient, url: str, query: str) -> dict[str, Any]:
    try:
        response = await client.post(url, data={"data": query}, headers={"User-Agent": USER_AGENT})
    except httpx.HTTPError as error:
        raise ApplicationError(
            code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
            message=f"OpenStreetMap did not answer: {error}",
            component=COMPONENT,
            retryable=True,
        ) from error
    if response.status_code != 200:
        raise ApplicationError(
            code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
            message=f"OpenStreetMap answered {response.status_code}",
            component=COMPONENT,
            retryable=response.status_code in RETRYABLE_STATUS,
            context={"body": response.text[:200]},
        )
    try:
        document = response.json()
    except ValueError as error:
        raise ApplicationError(
            code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
            message="OpenStreetMap answered something that is not JSON",
            component=COMPONENT,
        ) from error
    if not isinstance(document, dict):
        raise ApplicationError(
            code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
            message="OpenStreetMap answered something that is not an object",
            component=COMPONENT,
        )
    return document
