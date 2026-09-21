"""The one HTTP call to an Overpass API (phase 33, decision D270): the query in, the JSON
answer out, a structured failure when the server does not answer, so the route can say so."""

from __future__ import annotations

from typing import Any

import httpx

from shared.enums import ErrorCode
from shared.trace import ApplicationError
from shared.version import __version__

TIMEOUT_S = 30
USER_AGENT = f"SmartParksProtect/{__version__} (propose area)"
COMPONENT = "overpass"


async def fetch_overpass(url: str, query: str) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
            response = await client.post(
                url, data={"data": query}, headers={"User-Agent": USER_AGENT}
            )
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
            retryable=response.status_code in (429, 502, 503, 504),
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
