"""Which API paths an access token of an AI client may reach, per scope (AI action policy,
architecture 27.6 and 27.7): reads per scope, writes through the AI action endpoint only."""

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


# Writes an AI client may make, through the AI action endpoint or the frameworks people use
# (architecture 27.4); the action policy applies on top (architecture 27.6).
_WRITE_RULES: list[tuple[str, re.Pattern[str], str]] = [
    ("POST", re.compile(r"^/api/v1/mcp/actions$"), ""),
    ("POST", re.compile(r"^/api/v1/mcp/actions/[^/]+/confirm$"), ""),
    ("GET", re.compile(r"^/api/v1/mcp/(policy|actions/[^/]+)$"), ""),
    ("GET", re.compile(r"^/api/v1/devices/[^/]+/actions$"), Scope.DEVICES_READ),
]


def authorize_request(method: str, path: str, granted: list[str]) -> tuple[bool, str | None]:
    """(allowed, missing scope). Reads per scope; writes only through the AI action endpoint,
    which checks the write scope of the action; an unknown path is never allowed."""
    for write_method, pattern, scope in _WRITE_RULES:
        if method == write_method and pattern.match(path):
            if scope == "" or scope in granted:
                return True, None
            return False, scope
    if method != "GET":
        return False, None
    for pattern, scope in _RULES:
        if pattern.match(path):
            if scope == "" or scope in granted:
                return True, None
            return False, scope
    return False, None
