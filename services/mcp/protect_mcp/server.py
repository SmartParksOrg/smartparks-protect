"""Tools, resources and prompts of the read-only proof of concept (architecture 27.2, 27.3,
27.9 and 27.13). Every tool is bounded (27.7): a row limit, a time window or the API's own
aggregation ceilings. Results carry ids and `smartparks://` URIs so a client can follow up,
and `url` fields pointing at the web application."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer, Message
from mcp.server.mcpserver.exceptions import ResourceNotFoundError, ToolError
from pydantic import Field

from protect_mcp.api import ProtectApi
from protect_mcp.auth import JWTTokenVerifier
from shared.config import get_settings
from shared.oauth import READ_SCOPES, Scope, issuer_url, mcp_resource_url

MAX_ITEMS = 100
MAX_PROJECTS_FOR_SEARCH = 10
MAX_METRICS = 5
DEFAULT_WINDOW_HOURS = 24

INSTRUCTIONS = """Smart Parks Protect is the operational data platform of a conservation area:
entities (animals, vehicles, gates, sensors) carry devices (collars, trackers) that produce
positions, measurements, states and events. Everything is scoped to a project; call
list_projects first and pass the project id to the other tools. Ids are UUIDs. Times are ISO
8601 in UTC. Every result is bounded; narrow the time window or the filters rather than asking
for more rows. Use get_processing_trace and search_traces to explain why data is missing or
failed. Tools are read-only."""

Uuid = Annotated[uuid.UUID, Field(description="UUID")]
TimeArg = Annotated[
    datetime | None, Field(description="ISO 8601 with timezone, for example 2026-09-04T00:00:00Z")
]


def _url(path: str) -> str:
    return f"{issuer_url()}{path}"


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(UTC).isoformat() if value else None


def _window(time_from: datetime | None, time_to: datetime | None, hours: int) -> dict[str, str]:
    end = time_to or datetime.now(UTC)
    start = time_from or end - timedelta(hours=hours)
    if start >= end:
        raise ToolError("time_from must be before time_to")
    return {"from": start.isoformat(), "to": end.isoformat()}


def build_server(api: ProtectApi) -> MCPServer[None]:
    mcp: MCPServer[None] = MCPServer(
        "Smart Parks Protect",
        instructions=INSTRUCTIONS,
        website_url=issuer_url(),
        token_verifier=JWTTokenVerifier(),
        # Plain strings, so the settings model keeps a path-less issuer without a trailing slash.
        auth=AuthSettings(
            issuer_url=issuer_url(),
            resource_server_url=mcp_resource_url(),
            required_scopes=list(READ_SCOPES),
            service_documentation_url=get_settings().documentation_url,
        ),
    )

    # Helpers that several tools share

    async def projects() -> list[dict[str, Any]]:
        page = await api.get("/projects", tool="list_projects", params={"limit": 500})
        return list(page["items"])

    async def entity_types() -> dict[str, str]:
        page = await api.get("/entity-types", tool="get_entity", params={"limit": 500})
        return {item["id"]: item["label"] for item in page["items"]}

    async def device_types() -> dict[str, dict[str, Any]]:
        page = await api.get("/device-types", tool="get_device", params={"limit": 500})
        return {item["id"]: item for item in page["items"]}

    def entity_summary(
        project_id: str, entity: dict[str, Any], type_name: str | None
    ) -> dict[str, Any]:
        return {
            "id": entity["id"],
            "uri": f"smartparks://projects/{project_id}/entities/{entity['id']}",
            "name": entity["name"],
            "entity_type": type_name,
            "entity_type_id": entity["entity_type_id"],
            "status": entity["status"],
            "attributes": entity.get("attributes", {}),
            "url": _url(f"/projects/{project_id}/entities"),
        }

    async def latest_position(project_id: str, tool: str, **filters: str) -> dict[str, Any] | None:
        rows = await api.get(
            f"/projects/{project_id}/positions",
            tool=tool,
            params={
                **filters,
                "limit": 1,
                "from": (datetime.now(UTC) - timedelta(days=365)).isoformat(),
            },
        )
        if not rows:
            return None
        return position_summary(rows[0])

    def position_summary(row: dict[str, Any]) -> dict[str, Any]:
        geometry = row.get("geometry") or {}
        coordinates = geometry.get("coordinates") or [None, None]
        return {
            "time": row["time"],
            "latitude": coordinates[1],
            "longitude": coordinates[0],
            "altitude_m": row.get("altitude_m"),
            "speed_mps": row.get("speed_mps"),
            "accuracy_m": row.get("accuracy_m"),
            "record_type": row["record_type"],
            "device_id": row["device_id"],
            "entity_id": row.get("entity_id"),
            "source_event_id": row.get("source_event_id"),
            "trace_id": row.get("trace_id"),
            "trace_uri": f"smartparks://traces/{row['trace_id']}" if row.get("trace_id") else None,
        }

    # Tools (architecture 27.13)

    @mcp.tool()
    async def list_projects() -> dict[str, Any]:
        """Projects the authenticated user can read, with the user's role in each. Call this
        first: every other tool needs a project id."""
        items = await projects()
        return {
            "projects": [
                {
                    "id": p["id"],
                    "uri": f"smartparks://projects/{p['id']}",
                    "name": p["name"],
                    "slug": p["slug"],
                    "role": p["role"],
                    "timezone": p["timezone"],
                    "description": p.get("description"),
                    "url": _url(f"/projects/{p['id']}/map"),
                }
                for p in items
            ]
        }

    @mcp.tool()
    async def search_entities(
        project_id: Uuid,
        query: Annotated[str | None, Field(description="Name contains, case-insensitive")] = None,
        entity_type_id: Uuid | None = None,
        status: Annotated[str | None, Field(description="active, inactive or archived")] = None,
        limit: Annotated[int, Field(ge=1, le=MAX_ITEMS)] = 20,
    ) -> dict[str, Any]:
        """Find entities (animals, people, vehicles, gates, traps, sensors) in a project by
        name, type or status. Returns at most `limit` entities."""
        types = await entity_types()
        page = await api.get(
            f"/projects/{project_id}/entities",
            tool="search_entities",
            params={
                "q": query,
                "entity_type_id": str(entity_type_id) if entity_type_id else None,
                "status_filter": status,
                "limit": limit,
            },
        )
        return {
            "entities": [
                entity_summary(str(project_id), e, types.get(e["entity_type_id"]))
                for e in page["items"]
            ],
            "truncated": page.get("next_cursor") is not None,
        }

    @mcp.tool()
    async def get_entity(project_id: Uuid, entity_id: Uuid) -> dict[str, Any]:
        """One entity with its type, its current device assignment and its latest position."""
        entity = await api.get(f"/projects/{project_id}/entities/{entity_id}", tool="get_entity")
        types = await entity_types()
        assignments = await api.get(
            f"/projects/{project_id}/entity-assignments",
            tool="get_entity",
            params={"entity_id": str(entity_id), "limit": 20},
        )
        current = [a for a in assignments["items"] if a.get("valid_to") is None]
        return {
            **entity_summary(str(project_id), entity, types.get(entity["entity_type_id"])),
            "notes": entity.get("notes"),
            "geometry": entity.get("geometry"),
            "current_devices": [
                {
                    "device_id": a["device_id"],
                    "uri": f"smartparks://devices/{a['device_id']}",
                    "since": a["valid_from"],
                }
                for a in current
            ],
            "assignment_history": [
                {"device_id": a["device_id"], "from": a["valid_from"], "to": a.get("valid_to")}
                for a in assignments["items"]
            ],
            "latest_position": await latest_position(
                str(project_id), "get_entity", entity_id=str(entity_id)
            ),
        }

    @mcp.tool()
    async def get_device(device_id: Uuid) -> dict[str, Any]:
        """A device (collar, tracker, sensor) with its type, project and entity assignments,
        external identities (DevEUI and the like) and deep links into the source platforms."""
        device = await api.get(f"/devices/{device_id}", tool="get_device")
        types = await device_types()
        device_type = types.get(device["device_type_id"], {})
        return {
            "id": device["id"],
            "uri": f"smartparks://devices/{device['id']}",
            "name": device["name"],
            "serial_number": device.get("serial_number"),
            "status": device["status"],
            "firmware_version": device.get("firmware_version"),
            "device_type": device_type.get("label"),
            "driver": device_type.get("driver_key"),
            "capabilities": device_type.get("capabilities", []),
            "attributes": device.get("attributes", {}),
            "project_assignments": device.get("project_assignments", []),
            "entity_assignments": device.get("entity_assignments", []),
            "external_identities": [
                {
                    "data_source_id": i["data_source_id"],
                    "identity_type": i["identity_type"],
                    "external_id": i["external_id"],
                    "last_seen_at": i.get("last_seen_at"),
                    "event_count": i.get("event_count"),
                }
                for i in device.get("external_identities", [])
            ],
            "links": device.get("links", []),
            "url": next(
                (
                    _url(f"/projects/{a['project_id']}/devices/{device['id']}")
                    for a in device.get("project_assignments", [])
                    if a.get("valid_to") is None
                ),
                None,
            ),
        }

    @mcp.tool()
    async def get_latest_position(
        project_id: Uuid, entity_id: Uuid | None = None, device_id: Uuid | None = None
    ) -> dict[str, Any]:
        """The newest canonical position of an entity or a device in a project (last year)."""
        if entity_id is None and device_id is None:
            raise ToolError("Give entity_id or device_id")
        filters = {}
        if entity_id is not None:
            filters["entity_id"] = str(entity_id)
        if device_id is not None:
            filters["device_id"] = str(device_id)
        position = await latest_position(str(project_id), "get_latest_position", **filters)
        return {"position": position, "url": _url(f"/projects/{project_id}/map")}

    @mcp.tool()
    async def query_measurements(
        project_id: Uuid,
        metric: Annotated[list[str], Field(min_length=1, max_length=MAX_METRICS)],
        entity_id: Uuid | None = None,
        device_id: Uuid | None = None,
        time_from: TimeArg = None,
        time_to: TimeArg = None,
        bucket: Annotated[
            str | None,
            Field(description="1s, 10s, 1m, 5m, 15m, 1h, 6h, 1d, 7d or all; default automatic"),
        ] = None,
        aggregates: Annotated[
            list[str] | None, Field(description="mean, min, max, median, sum, count, first, last")
        ] = None,
    ) -> dict[str, Any]:
        """Server-side aggregated measurements (battery voltage, temperature, RSSI, ...) per
        metric and entity. Default window: the last 24 hours. The API picks the bucket so that
        a series has at most 5,000 points; ask for a coarser bucket for long ranges. Use
        list_metrics to learn the metric keys with data."""
        params: dict[str, Any] = {
            "metric": metric,
            "entity_id": [str(entity_id)] if entity_id else None,
            "device_id": [str(device_id)] if device_id else None,
            "bucket": bucket,
            "agg": aggregates,
            "layout": "series",
            **_window(time_from, time_to, DEFAULT_WINDOW_HOURS),
        }
        result = await api.get(
            f"/projects/{project_id}/analytics/series", tool="query_measurements", params=params
        )
        return {
            "time_from": result["time_from"],
            "time_to": result["time_to"],
            "bucket": result["bucket"],
            "aggregates": result["aggregates"],
            "series": result.get("series") or [],
            "url": _url(f"/projects/{project_id}/analyze/explorer"),
        }

    @mcp.tool()
    async def list_metrics(
        project_id: Uuid, time_from: TimeArg = None, time_to: TimeArg = None
    ) -> dict[str, Any]:
        """Metric keys that have measurements in the project within the window (default the
        last 30 days), with units and counts."""
        rows = await api.get(
            f"/projects/{project_id}/analytics/metrics",
            tool="list_metrics",
            params=_window(time_from, time_to, 30 * 24),
        )
        return {"metrics": rows}

    @mcp.tool()
    async def query_events(
        project_id: Uuid,
        event_type: str | None = None,
        severity: Annotated[str | None, Field(description="info, warning or critical")] = None,
        entity_id: Uuid | None = None,
        time_from: TimeArg = None,
        time_to: TimeArg = None,
        limit: Annotated[int, Field(ge=1, le=MAX_ITEMS)] = 20,
    ) -> dict[str, Any]:
        """Domain events of a project (geofence, battery, detections, system findings), newest
        first, with their alert status. Default window: the last 7 days."""
        page = await api.get(
            f"/projects/{project_id}/events",
            tool="query_events",
            params={
                "event_type": event_type,
                "severity": severity,
                "entity_id": str(entity_id) if entity_id else None,
                "limit": limit,
                **_window(time_from, time_to, 7 * 24),
            },
        )
        return {
            "events": [
                {
                    "id": e["id"],
                    "uri": f"smartparks://projects/{project_id}/events/{e['id']}",
                    "time": e["time"],
                    "event_type": e["event_type"],
                    "severity": e["severity"],
                    "title": e["title"],
                    "description": e.get("description"),
                    "entity_id": e.get("entity_id"),
                    "device_id": e.get("device_id"),
                    "alert_status": e.get("alert_status"),
                    "trace_id": e.get("trace_id"),
                    "context": e.get("context", {}),
                }
                for e in page["items"]
            ],
            "truncated": page.get("next_cursor") is not None,
            "url": _url(f"/projects/{project_id}/rules/events"),
        }

    @mcp.tool()
    async def get_processing_trace(trace_id: Uuid) -> dict[str, Any]:
        """How one message, command or delivery moved through the platform: ordered steps with
        status and the structured error where it stopped. Trace ids come from positions,
        measurements, events and search_traces."""
        trace = await api.get(f"/traces/{trace_id}", tool="get_processing_trace")
        return {"trace": trace}

    @mcp.tool()
    async def search_traces(
        project_id: Uuid,
        device_id: Uuid | None = None,
        external_id: Annotated[str | None, Field(description="DevEUI or other identity")] = None,
        status: Annotated[
            str | None, Field(description="success, failed, dead_letter, duplicate, skipped")
        ] = None,
        error_code: str | None = None,
        time_from: TimeArg = None,
        time_to: TimeArg = None,
        limit: Annotated[int, Field(ge=1, le=MAX_ITEMS)] = 20,
    ) -> dict[str, Any]:
        """Processing traces of a project's devices, newest first (default the last 24 hours).
        The way to find out whether a device is still transmitting and where its data stopped."""
        rows = await api.get(
            f"/projects/{project_id}/traces",
            tool="search_traces",
            params={
                "device_id": str(device_id) if device_id else None,
                "external_id": external_id,
                "status": status,
                "error_code": error_code,
                "limit": limit,
                **_window(time_from, time_to, DEFAULT_WINDOW_HOURS),
            },
        )
        return {
            "traces": [{**t, "uri": f"smartparks://traces/{t['id']}"} for t in rows],
            "url": _url(f"/projects/{project_id}/network/traces"),
        }

    # ChatGPT's search and fetch contract (developer documentation for connectors)

    # Write tools (architecture 27.4 and 27.6, decision D87): every write goes through the
    # API's AI action endpoint, which applies the server's AI action policy and the person's
    # permissions, and may hold the action for `confirm_action`.

    def _needs_scope(scope: str) -> None:
        access = get_access_token()
        if access is None or scope not in access.scopes:
            raise ToolError(
                f"This tool needs the {scope} scope, which this connection was not granted. "
                "Reconnect and grant it on the consent page."
            )

    async def _action(tool: str, action: str, parameters: dict[str, Any]) -> dict[str, Any]:
        answer = await api.post(
            "/mcp/actions", tool=tool, body={"action": action, "parameters": parameters}
        )
        if answer.get("status") == "confirmation_required":
            answer["next_step"] = (
                "Show the summary to the user and ask them to confirm. When they confirm, call "
                f"confirm_action with action_id {answer['id']} within ten minutes. Do not "
                "call confirm_action without an explicit confirmation from the user."
            )
        return dict(answer)

    @mcp.tool()
    async def create_event(
        project_id: Uuid,
        event_type: Annotated[str, Field(description="Upper snake case, for example SIGHTING")],
        title: Annotated[str, Field(max_length=200)],
        severity: Annotated[str, Field(description="info, warning or critical")] = "info",
        description: str | None = None,
        entity_id: Uuid | None = None,
        device_id: Uuid | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        create_alert: Annotated[bool, Field(description="Also open an alert for a person")] = False,
    ) -> dict[str, Any]:
        """Record an event (a report: a sighting, an incident, a note) in a project on behalf
        of the user. A safe write: the server's AI action policy may require the user's
        confirmation first; then this tool returns a summary and an action id."""
        _needs_scope(str(Scope.EVENTS_WRITE))
        return await _action(
            "create_event",
            "create_event",
            {
                "project_id": str(project_id),
                "event_type": event_type,
                "title": title,
                "severity": severity,
                "description": description,
                "entity_id": str(entity_id) if entity_id else None,
                "device_id": str(device_id) if device_id else None,
                "latitude": latitude,
                "longitude": longitude,
                "create_alert": create_alert,
            },
        )

    @mcp.tool()
    async def acknowledge_alert(
        project_id: Uuid, alert_id: Uuid, note: str | None = None
    ) -> dict[str, Any]:
        """Acknowledge an open alert on behalf of the user (they take ownership of it). A safe
        write under the AI action policy; may need the user's confirmation first."""
        _needs_scope(str(Scope.ALERTS_WRITE))
        return await _action(
            "acknowledge_alert",
            "acknowledge_alert",
            {"project_id": str(project_id), "alert_id": str(alert_id), "note": note},
        )

    @mcp.tool()
    async def request_device_status(device_id: Uuid) -> dict[str, Any]:
        """Ask a device for a status message (battery, temperature, errors) through the normal
        device control path. Operational control: needs the device control permission and,
        by policy, the user's confirmation."""
        _needs_scope(str(Scope.DEVICES_CONTROL))
        return await _action(
            "request_device_status", "request_device_status", {"device_id": str(device_id)}
        )

    @mcp.tool()
    async def request_device_position(device_id: Uuid) -> dict[str, Any]:
        """Ask a device for a GNSS fix now, through the normal device control path.
        Operational control: needs the device control permission and, by policy, the user's
        confirmation."""
        _needs_scope(str(Scope.DEVICES_CONTROL))
        return await _action(
            "request_device_position", "request_device_position", {"device_id": str(device_id)}
        )

    @mcp.tool()
    async def confirm_action(action_id: Uuid) -> dict[str, Any]:
        """Execute an action that was proposed by another tool and held for confirmation.
        Call this only after the user explicitly confirmed the summary; the proposal expires
        after ten minutes."""
        return dict(
            await api.post(f"/mcp/actions/{action_id}/confirm", tool="confirm_action", body={})
        )

    @mcp.tool()
    async def get_ai_policy() -> dict[str, Any]:
        """The server's AI action policy: which write actions are allowed, need confirmation
        or are disabled for AI clients."""
        return dict(await api.get("/mcp/policy", tool="get_ai_policy"))

    @mcp.tool()
    async def search(query: str) -> dict[str, Any]:
        """Search entities and devices by name across the user's projects. Returns ids that
        `fetch` accepts. Bounded to ten projects and ten hits per project and kind."""
        results: list[dict[str, str]] = []
        for project in (await projects())[:MAX_PROJECTS_FOR_SEARCH]:
            entities = await api.get(
                f"/projects/{project['id']}/entities",
                tool="search",
                params={"q": query, "limit": 10},
            )
            results.extend(
                {
                    "id": f"smartparks://projects/{project['id']}/entities/{e['id']}",
                    "title": f"{e['name']} (entity in {project['name']})",
                    "url": _url(f"/projects/{project['id']}/entities"),
                }
                for e in entities["items"]
            )
            devices = await api.get(
                "/devices",
                tool="search",
                params={"project_id": project["id"], "q": query, "limit": 10},
            )
            results.extend(
                {
                    "id": f"smartparks://devices/{d['id']}",
                    "title": f"{d['name']} (device in {project['name']})",
                    "url": _url(f"/projects/{project['id']}/devices/{d['id']}"),
                }
                for d in devices["items"]
            )
        return {"results": results}

    @mcp.tool()
    async def fetch(id: Annotated[str, Field(description="A smartparks:// URI")]) -> dict[str, Any]:
        """The full record behind a search result or any smartparks:// URI."""
        document = await read_uri(id, tool="fetch")
        return {
            "id": id,
            "title": document.get("title", id),
            "text": _text(document),
            "url": document.get("url") or issuer_url(),
            "metadata": {"kind": document.get("kind")},
        }

    # Resources (architecture 27.2). The API needs the project for entities and events, so
    # those URIs carry it.

    async def read_uri(uri: str, *, tool: str) -> dict[str, Any]:
        parts = uri.removeprefix("smartparks://").strip("/").split("/")
        try:
            match parts:
                case ["projects", project_id]:
                    project = await api.get(f"/projects/{uuid.UUID(project_id)}", tool=tool)
                    return {"kind": "project", "title": project["name"], **project}
                case ["projects", project_id, "entities", entity_id]:
                    entity = await get_entity(uuid.UUID(project_id), uuid.UUID(entity_id))
                    return {"kind": "entity", "title": entity["name"], **entity}
                case ["projects", project_id, "events", event_id]:
                    event = await api.get(
                        f"/projects/{uuid.UUID(project_id)}/events/{uuid.UUID(event_id)}", tool=tool
                    )
                    return {"kind": "event", "title": event["title"], **event}
                case ["devices", device_id]:
                    device = await get_device(uuid.UUID(device_id))
                    return {"kind": "device", "title": device["name"], **device}
                case ["traces", trace_id]:
                    trace = await api.get(f"/traces/{uuid.UUID(trace_id)}", tool=tool)
                    return {"kind": "trace", "title": f"Trace {trace_id}", **trace}
        except ValueError:
            raise ResourceNotFoundError(f"{uri} is not a valid smartparks:// URI") from None
        raise ResourceNotFoundError(f"{uri} is not a known smartparks:// URI")

    @mcp.resource("smartparks://projects/{project_id}", mime_type="application/json")
    async def project_resource(project_id: str) -> dict[str, Any]:
        """A project."""
        return await read_uri(f"smartparks://projects/{project_id}", tool="resource")

    @mcp.resource(
        "smartparks://projects/{project_id}/entities/{entity_id}", mime_type="application/json"
    )
    async def entity_resource(project_id: str, entity_id: str) -> dict[str, Any]:
        """An entity with its current device and latest position."""
        return await read_uri(
            f"smartparks://projects/{project_id}/entities/{entity_id}", tool="resource"
        )

    @mcp.resource(
        "smartparks://projects/{project_id}/events/{event_id}", mime_type="application/json"
    )
    async def event_resource(project_id: str, event_id: str) -> dict[str, Any]:
        """An event with its alert and deliveries."""
        return await read_uri(
            f"smartparks://projects/{project_id}/events/{event_id}", tool="resource"
        )

    @mcp.resource("smartparks://devices/{device_id}", mime_type="application/json")
    async def device_resource(device_id: str) -> dict[str, Any]:
        """A device with assignments and identities."""
        return await read_uri(f"smartparks://devices/{device_id}", tool="resource")

    @mcp.resource("smartparks://traces/{trace_id}", mime_type="application/json")
    async def trace_resource(trace_id: str) -> dict[str, Any]:
        """A processing trace with its steps."""
        return await read_uri(f"smartparks://traces/{trace_id}", tool="resource")

    # Prompts (architecture 27.9)

    @mcp.prompt(title="Analyze device health")
    def analyze_device_health(device_id: str) -> list[Message]:
        """Check whether a device is healthy: connectivity, battery, data flow."""
        return [
            Message(
                role="user",
                content=(
                    f"Assess the health of device {device_id} in Smart Parks Protect. Steps: "
                    "call get_device for its type, assignments and identities; find its project "
                    "from the current project assignment; call search_traces for the last 24 "
                    "hours filtered on the device to see whether it still transmits and whether "
                    "processing fails; call query_measurements for battery_voltage or "
                    "battery_level and rssi over the last 7 days; call get_latest_position. Then "
                    "report: last contact, transmission cadence, failures with error codes, "
                    "battery trend, signal, and a plain conclusion with the next action."
                ),
            )
        ]

    @mcp.prompt(title="Investigate missing data")
    def investigate_missing_data(project_id: str, entity_or_device: str) -> list[Message]:
        """Find out why an entity or device stopped updating."""
        return [
            Message(
                role="user",
                content=(
                    f"In project {project_id}, {entity_or_device} has stopped updating. Find out "
                    "why. Use search_entities or search to identify it, get_entity for its "
                    "current device, get_device for the device's identities and links, "
                    "search_traces over the last 48 hours for that device (all statuses), and "
                    "get_processing_trace on failed traces. Distinguish: the device is silent "
                    "(no traces), the network delivered but decoding failed (failed traces with "
                    "an error code), or data arrived but is attributed elsewhere (no current "
                    "assignment). End with what a ranger or administrator should do next."
                ),
            )
        ]

    return mcp


def _text(document: dict[str, Any]) -> str:
    import json

    return json.dumps(document, indent=1, default=str)
