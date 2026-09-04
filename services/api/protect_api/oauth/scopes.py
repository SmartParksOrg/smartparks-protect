"""Which API paths an access token of an AI client may reach, per scope (AI action policy,
architecture 27.6 and 27.7). Phase 9: reads only; every other request is refused."""

import re

from shared.oauth import Scope

# Path pattern, scope required. An empty scope means any valid token may call it.
_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^/api/v1/users/me$"), ""),
    (re.compile(r"^/api/v1/projects(/[^/]+)?$"), Scope.PROJECTS_READ),
    (re.compile(r"^/api/v1/(entity-types|device-types|metrics)(/[^/]+)?$"), Scope.PROJECTS_READ),
    (
        re.compile(r"^/api/v1/projects/[^/]+/(entities|features|entity-assignments)(/[^/]+)?$"),
        Scope.ENTITIES_READ,
    ),
    (re.compile(r"^/api/v1/devices(/[^/]+)?$"), Scope.DEVICES_READ),
    (re.compile(r"^/api/v1/projects/[^/]+/(positions|tracks|map/current)$"), Scope.POSITIONS_READ),
    (
        re.compile(r"^/api/v1/projects/[^/]+/analytics/(series|rows|metrics)$"),
        Scope.MEASUREMENTS_READ,
    ),
    (re.compile(r"^/api/v1/projects/[^/]+/(events|alerts)(/[^/]+)?$"), Scope.EVENTS_READ),
    (re.compile(r"^/api/v1/projects/[^/]+/(traces|traffic)$"), Scope.TRACES_READ),
    (re.compile(r"^/api/v1/(traces|source-events)/[^/]+$"), Scope.TRACES_READ),
]


def authorize_request(method: str, path: str, granted: list[str]) -> tuple[bool, str | None]:
    """(allowed, missing scope). A write is never allowed; an unknown path is never allowed."""
    if method != "GET":
        return False, None
    for pattern, scope in _RULES:
        if pattern.match(path):
            if scope == "" or scope in granted:
                return True, None
            return False, scope
    return False, None
