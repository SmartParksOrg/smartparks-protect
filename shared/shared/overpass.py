"""The call to an Overpass API (phase 33, decisions D270 and D279): the query in, the JSON
answer out, a structured failure when no server answers, so the route can say so.

A public Overpass server refuses a burst rather than queueing it, and a refusal arrives within
seconds, so a call that may still succeed is made again — but not at the same server. The public
`overpass-api.de` spreads its clients over its backends and keeps each one where it put it, so a
host that landed on a tired backend is refused nearly every time while another host is served in
three seconds. Measured from the dev server on 2026-09-21, same query, same minute: 504, 200,
504 at `overpass-api.de` against 200, 200, 200 at `overpass.openstreetmap.fr`. So the setting
names a list, the attempts walk it, and one server's bad afternoon is another's answer. A
server's final word (a 400 on a bad query, a 403) is not repeated anywhere."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

import httpx

from shared.enums import ErrorCode
from shared.trace import ApplicationError
from shared.version import __version__

TIMEOUT_S = 30
USER_AGENT = f"SmartParksProtect/{__version__} (propose area)"
COMPONENT = "overpass"
#: How many times one call is attempted, the first included. With several servers the attempts
#: walk the list and come round again, so two servers are each asked twice at most.
ATTEMPTS = 4
#: The pause between two attempts. Long enough for a busy server's slot, short enough that
#: somebody who clicked on the map is still waiting for an answer rather than wondering.
RETRY_PAUSE_S = 2.0
#: The answers a busy server gives, which another attempt may get past.
RETRYABLE_STATUS = (429, 502, 503, 504)


def servers(setting: str | Sequence[str]) -> list[str]:
    """The servers to ask, in order: one address, or several separated by commas."""
    given = setting.split(",") if isinstance(setting, str) else setting
    return [url.strip() for url in given if url.strip()]


async def fetch_overpass(url: str | Sequence[str], query: str) -> dict[str, Any]:
    """The answer to one Overpass query, or an `ApplicationError` saying why there is none."""
    urls = servers(url)
    if not urls:
        raise ApplicationError(
            code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
            message="No OpenStreetMap server is configured",
            component=COMPONENT,
        )
    async with httpx.AsyncClient(timeout=TIMEOUT_S) as client:
        for attempt in range(ATTEMPTS - 1):
            try:
                return await _attempt(client, urls[attempt % len(urls)], query)
            except ApplicationError as error:
                if not error.retryable:
                    raise
            # the next server can be asked at once; coming round to a tried one, wait a moment
            if (attempt + 1) % len(urls) == 0:
                await asyncio.sleep(RETRY_PAUSE_S)
        return await _attempt(client, urls[(ATTEMPTS - 1) % len(urls)], query)


async def _attempt(client: httpx.AsyncClient, url: str, query: str) -> dict[str, Any]:
    try:
        response = await client.post(url, data={"data": query}, headers={"User-Agent": USER_AGENT})
    except httpx.HTTPError as error:
        raise ApplicationError(
            code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
            message=f"OpenStreetMap did not answer: {error}",
            component=COMPONENT,
            retryable=True,
            context={"url": url},
        ) from error
    if response.status_code != 200:
        raise ApplicationError(
            code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
            message=f"OpenStreetMap answered {response.status_code}",
            component=COMPONENT,
            retryable=response.status_code in RETRYABLE_STATUS,
            context={"body": response.text[:200], "url": url},
        )
    try:
        document = response.json()
    except ValueError as error:
        raise ApplicationError(
            code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
            message="OpenStreetMap answered something that is not JSON",
            component=COMPONENT,
            context={"url": url},
        ) from error
    if not isinstance(document, dict):
        raise ApplicationError(
            code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
            message="OpenStreetMap answered something that is not an object",
            component=COMPONENT,
            context={"url": url},
        )
    return document
