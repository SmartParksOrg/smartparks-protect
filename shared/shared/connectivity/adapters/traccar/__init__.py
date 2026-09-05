"""Traccar (architecture 7.2, decision D65): the non-LoRaWAN tracking source that proves the
connectivity abstraction is generic.

Built from the Traccar OpenAPI document (traccar/openapi.yaml) and the API overview at
https://www.traccar.org/traccar-api/:

- `POST /api/session` with form fields `email` and `password` opens a session and sets the
  `JSESSIONID` cookie; `GET /api/session?token=...` does the same with an API token. The
  websocket accepts the session cookie only.
- `/api/socket` streams `{"positions": [...]}`, `{"devices": [...]}` and `{"events": [...]}`.
- A position carries `deviceId`, `protocol`, `deviceTime`, `fixTime`, `serverTime`, `valid`,
  `latitude`, `longitude`, `altitude` (m), `speed` (knots), `course` (degrees), `accuracy` (m)
  and `attributes` (batteryLevel, battery, sat, ignition, motion, ...).
- A device carries `id`, `name`, `uniqueId`, `status` (online, offline, unknown), `lastUpdate`.
- An event carries `type` (deviceOnline, geofenceEnter, alarm, ...), `eventTime`, `deviceId`,
  `positionId`, `geofenceId`, `attributes`.
- `GET /api/positions` returns the latest position of every device the user sees.
- `POST /api/commands/send` with `{deviceId, type, attributes}` sends a command; 200 means
  sent, 202 queued until the device connects. `GET /api/commands/types?deviceId=` lists the
  types the device's protocol supports.

Positions become the generic JSON shape (`time`, `lat`, `lon`, `speed` in m/s, ...) with the
original Traccar record under `raw`; device types for Traccar trackers use the Generic JSON
driver. The Traccar device id is the external identity; the `uniqueId` (IMEI) is an attribute.
Deep links target the Traccar web app; the path is a guess until seen live.

Config: `url` (for example https://demo.traccar.org), `web_url` (default url). Credentials:
`email` and `password`, or `token`.
"""

import asyncio
import json
import re
from datetime import UTC, datetime
from typing import Any, ClassVar
from urllib.parse import urlsplit

import httpx
import websockets

from shared.connectivity.base import (
    AdapterCapabilities,
    DataSourceContext,
    Emit,
    EventConnector,
    InboundMessage,
)
from shared.enums import AcquisitionChannel, ErrorCode, IngestionMethod
from shared.logger import get_logger
from shared.trace import ApplicationError

log = get_logger("adapter.traccar")

KNOTS_TO_MPS = 0.514444
RECONNECT_SECONDS = 5.0
HTTP_TIMEOUT = 20.0
IDENTITY_TYPE = "traccar_device_id"

# Traccar attributes that are measurements in the metric registry.
MEASUREMENT_ATTRIBUTES: dict[str, str] = {
    "batteryLevel": "battery_level",
    "battery": "battery_voltage",
    "power": "external_voltage",
    "temp1": "temperature",
    "rssi": "cellular_rssi",
    "odometer": "odometer_m",
    "totalDistance": "total_distance_m",
}
STATE_ATTRIBUTES = ("ignition", "motion", "blocked", "charge", "status")


def _error(message: str, code: ErrorCode = ErrorCode.PAYLOAD_DECODE_FAILED) -> ApplicationError:
    return ApplicationError(
        code=code, message=message, component="adapter.traccar", user_actionable=True
    )


def _time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def event_type_of(traccar_type: str) -> str:
    """`geofenceEnter` to `GEOFENCE_ENTER`, `alarm` to `ALARM`."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", traccar_type).upper()


def base_url(source: DataSourceContext) -> str:
    url = str(source.config.get("url") or "").strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise _error(
            "the Traccar source needs `url` in config (http or https)",
            ErrorCode.CONNECTIVITY_AUTH_FAILED,
        )
    return url


def socket_url(source: DataSourceContext) -> str:
    parts = urlsplit(base_url(source))
    scheme = "wss" if parts.scheme == "https" else "ws"
    return f"{scheme}://{parts.netloc}{parts.path}/api/socket"


def device_attributes(device: dict[str, Any] | None) -> dict[str, Any]:
    if not device:
        return {}
    return {
        k: v
        for k, v in {
            "device_name": device.get("name"),
            "unique_id": device.get("uniqueId"),
            "model": device.get("model"),
            "category": device.get("category"),
            "group_id": device.get("groupId"),
        }.items()
        if v not in (None, "")
    }


def parse_position(
    source: DataSourceContext,
    position: dict[str, Any],
    device: dict[str, Any] | None = None,
    *,
    method: IngestionMethod = IngestionMethod.WEBSOCKET,
) -> InboundMessage:
    if not isinstance(position, dict) or position.get("deviceId") is None:
        raise _error("Traccar position without deviceId")
    attributes = position.get("attributes") or {}
    if not isinstance(attributes, dict):
        attributes = {}
    fix_time = _time(position.get("fixTime")) or _time(position.get("deviceTime"))
    payload: dict[str, Any] = {
        "time": fix_time.isoformat() if fix_time else None,
        "raw": position,
    }
    if position.get("valid", True) and position.get("latitude") is not None:
        payload.update(
            {
                "lat": _float(position.get("latitude")),
                "lon": _float(position.get("longitude")),
                "altitude": _float(position.get("altitude")),
                "speed": (
                    round(float(position["speed"]) * KNOTS_TO_MPS, 3)
                    if position.get("speed") is not None
                    else None
                ),
                "heading": _float(position.get("course")),
                "accuracy": _float(position.get("accuracy")),
                "satellites": attributes.get("sat"),
            }
        )
    measurements = {
        metric: _float(attributes[key])
        for key, metric in MEASUREMENT_ATTRIBUTES.items()
        if attributes.get(key) is not None and _float(attributes[key]) is not None
    }
    if measurements:
        payload["measurements"] = measurements
    state = {k: attributes[k] for k in STATE_ATTRIBUTES if k in attributes}
    if state:
        payload["state"] = state
    payload = {k: v for k, v in payload.items() if v is not None}
    return InboundMessage(
        external_id=str(position["deviceId"]),
        event_type="position" if position.get("valid", True) else "position_invalid",
        payload=payload,
        acquisition_channel=AcquisitionChannel.CELLULAR,
        ingestion_method=method,
        provider_metadata={
            "traccar_position_id": position.get("id"),
            "protocol": position.get("protocol"),
            "valid": position.get("valid"),
            "device_time": position.get("deviceTime"),
            "server_time": position.get("serverTime"),
        },
        network_received_at=_time(position.get("serverTime")),
        identity_type=IDENTITY_TYPE,
        identity_attributes=device_attributes(device),
    )


def parse_event(
    source: DataSourceContext,
    event: dict[str, Any],
    device: dict[str, Any] | None = None,
    position: dict[str, Any] | None = None,
    *,
    method: IngestionMethod = IngestionMethod.WEBSOCKET,
) -> InboundMessage:
    if not isinstance(event, dict) or event.get("deviceId") is None or not event.get("type"):
        raise _error("Traccar event without deviceId or type")
    when = _time(event.get("eventTime"))
    name = (device or {}).get("name") or f"device {event['deviceId']}"
    kind = str(event["type"])
    normalized = event_type_of(kind)
    attributes = event.get("attributes") or {}
    item: dict[str, Any] = {
        "type": normalized,
        "title": f"{name}: {kind}"
        + (
            f" ({attributes['alarm']})"
            if isinstance(attributes, dict) and "alarm" in attributes
            else ""
        ),
        "severity": "warning" if kind in ("alarm", "deviceOffline", "geofenceExit") else "info",
        "context": {
            "traccar_event_id": event.get("id"),
            "traccar_type": kind,
            "geofence_id": event.get("geofenceId"),
            "position_id": event.get("positionId"),
            "attributes": attributes,
        },
    }
    if position and position.get("latitude") is not None:
        item["lat"] = _float(position.get("latitude"))
        item["lon"] = _float(position.get("longitude"))
    payload = {"time": when.isoformat() if when else None, "events": [item], "raw": event}
    return InboundMessage(
        external_id=str(event["deviceId"]),
        event_type="event",
        payload={k: v for k, v in payload.items() if v is not None},
        acquisition_channel=AcquisitionChannel.CELLULAR,
        ingestion_method=method,
        provider_metadata={"traccar_event_id": event.get("id"), "traccar_type": kind},
        network_received_at=when,
        identity_type=IDENTITY_TYPE,
        identity_attributes=device_attributes(device),
    )


def parse_device_status(source: DataSourceContext, device: dict[str, Any]) -> InboundMessage:
    when = _time(device.get("lastUpdate"))
    return InboundMessage(
        external_id=str(device["id"]),
        event_type="state",
        payload={
            "time": when.isoformat() if when else None,
            "state": {"connection": device.get("status") or "unknown"},
            "raw": device,
        },
        acquisition_channel=AcquisitionChannel.CELLULAR,
        ingestion_method=IngestionMethod.WEBSOCKET,
        provider_metadata={"traccar_status": device.get("status")},
        network_received_at=when,
        identity_type=IDENTITY_TYPE,
        identity_attributes=device_attributes(device),
    )


class TraccarSession:
    """Login and the authenticated HTTP client. `login` returns the JSESSIONID cookie."""

    def __init__(self, source: DataSourceContext) -> None:
        self.source = source
        self.base = base_url(source)
        self.client = httpx.AsyncClient(base_url=self.base, timeout=HTTP_TIMEOUT)

    async def login(self) -> str:
        credentials = self.source.credentials
        token = credentials.get("token")
        if token:
            response = await self.client.get("/api/session", params={"token": token})
        else:
            email, password = credentials.get("email"), credentials.get("password")
            if not email or not password:
                raise _error(
                    "the Traccar source needs `email` and `password` or `token` in credentials",
                    ErrorCode.CONNECTIVITY_AUTH_FAILED,
                )
            response = await self.client.post(
                "/api/session", data={"email": email, "password": password}
            )
        if response.status_code in (401, 403):
            raise _error(
                f"Traccar refused the credentials ({response.status_code})",
                ErrorCode.CONNECTIVITY_AUTH_FAILED,
            )
        response.raise_for_status()
        session_id = self.client.cookies.get("JSESSIONID")
        if not session_id:
            raise _error(
                "Traccar answered without a JSESSIONID cookie", ErrorCode.CONNECTIVITY_AUTH_FAILED
            )
        return session_id

    async def get(self, path: str, **params: Any) -> Any:
        response = await self.client.get(path, params=params or None)
        if response.status_code in (401, 403):
            raise _error(
                f"Traccar refused the session ({response.status_code})",
                ErrorCode.CONNECTIVITY_AUTH_FAILED,
            )
        response.raise_for_status()
        return response.json()

    async def devices(self) -> dict[int, dict[str, Any]]:
        return {int(d["id"]): d for d in await self.get("/api/devices") if d.get("id") is not None}

    async def positions(self) -> list[dict[str, Any]]:
        body = await self.get("/api/positions")
        return list(body) if isinstance(body, list) else []

    async def close(self) -> None:
        await self.client.aclose()


class TraccarConnector:
    """Session, a snapshot of the latest positions, then the websocket until it drops."""

    def __init__(self, source: DataSourceContext) -> None:
        self.source = source
        self.devices: dict[int, dict[str, Any]] = {}

    async def run(self, emit: Emit) -> None:
        while True:
            session = TraccarSession(self.source)
            try:
                session_id = await session.login()
                self.devices = await session.devices()
                for position in await session.positions():
                    await self._emit_position(emit, position)
                await self._stream(session_id, emit)
            except asyncio.CancelledError:
                raise
            except ApplicationError as error:
                log.warning("traccar connector stopped", source=self.source.name, error=str(error))
            except Exception as exc:
                log.warning(
                    "traccar connection lost, reconnecting",
                    source=self.source.name,
                    error=f"{type(exc).__name__}: {exc}",
                )
            finally:
                await session.close()
            await asyncio.sleep(RECONNECT_SECONDS)

    async def _emit_position(self, emit: Emit, position: dict[str, Any]) -> None:
        try:
            device = self.devices.get(int(position.get("deviceId", -1)))
            await emit(parse_position(self.source, position, device))
        except (ApplicationError, ValueError, TypeError) as error:
            log.warning("traccar position dropped", source=self.source.name, error=str(error))

    async def _stream(self, session_id: str, emit: Emit) -> None:
        async with websockets.connect(
            socket_url(self.source), additional_headers={"Cookie": f"JSESSIONID={session_id}"}
        ) as connection:
            log.info("traccar websocket connected", source=self.source.name)
            async for frame in connection:
                await self.on_frame(frame, emit)

    async def on_frame(self, frame: str | bytes, emit: Emit) -> None:
        try:
            data = json.loads(frame if isinstance(frame, str) else frame.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            log.warning("traccar frame is not JSON", source=self.source.name)
            return
        if not isinstance(data, dict):
            return
        for device in data.get("devices") or []:
            if isinstance(device, dict) and device.get("id") is not None:
                previous = self.devices.get(int(device["id"]))
                self.devices[int(device["id"])] = device
                if previous is None or previous.get("status") != device.get("status"):
                    await emit(parse_device_status(self.source, device))
        for position in data.get("positions") or []:
            if isinstance(position, dict):
                await self._emit_position(emit, position)
        for event in data.get("events") or []:
            if not isinstance(event, dict):
                continue
            try:
                device = self.devices.get(int(event.get("deviceId", -1)))
                await emit(parse_event(self.source, event, device))
            except (ApplicationError, ValueError, TypeError) as error:
                log.warning("traccar event dropped", source=self.source.name, error=str(error))


class TraccarCommands:
    """Command connector proof of concept: the platform command of the generic JSON driver
    (`{"type": ..., "attributes": {...}}` as JSON) becomes `POST /api/commands/send`."""

    def __init__(self, source: DataSourceContext) -> None:
        self.source = source

    async def submit(
        self, external_id: str, payload: bytes, options: dict[str, Any]
    ) -> dict[str, Any]:
        try:
            command = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApplicationError(
                code=ErrorCode.COMMAND_REJECTED,
                message="Traccar commands need a JSON payload with `type` and `attributes`",
                component="adapter.traccar",
                user_actionable=True,
            ) from exc
        if not isinstance(command, dict) or not command.get("type"):
            raise ApplicationError(
                code=ErrorCode.COMMAND_REJECTED,
                message="Traccar command without a type",
                component="adapter.traccar",
                user_actionable=True,
            )
        body = {
            "deviceId": int(external_id),
            "type": str(command["type"]),
            "attributes": dict(command.get("attributes") or {}),
        }
        session = TraccarSession(self.source)
        try:
            await session.login()
            response = await session.client.post("/api/commands/send", json=body)
        finally:
            await session.close()
        if response.status_code in (401, 403):
            raise _error(
                f"Traccar refused the session ({response.status_code})",
                ErrorCode.CONNECTIVITY_AUTH_FAILED,
            )
        if response.status_code >= 500:
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
                message=f"Traccar answered {response.status_code}: {response.text[:200]}",
                component="adapter.traccar",
                retryable=True,
            )
        if response.status_code >= 400:
            raise ApplicationError(
                code=ErrorCode.COMMAND_REJECTED,
                message=(
                    f"Traccar rejected the command ({response.status_code}): {response.text[:200]}"
                ),
                component="adapter.traccar",
                user_actionable=True,
            )
        statuses = ["accepted_by_network"]
        statuses.append("queued" if response.status_code == 202 else "transmitted")
        body_json: Any = None
        try:
            body_json = response.json()
        except ValueError:
            body_json = None
        return {
            "provider_ref": str(body_json.get("id")) if isinstance(body_json, dict) else None,
            "statuses": statuses,
            "http_status": response.status_code,
        }

    async def command_types(self, external_id: str) -> list[dict[str, Any]]:
        session = TraccarSession(self.source)
        try:
            await session.login()
            body = await session.get("/api/commands/types", deviceId=int(external_id))
        finally:
            await session.close()
        return list(body) if isinstance(body, list) else []


class TraccarManagement:
    def __init__(self, source: DataSourceContext) -> None:
        self.source = source

    async def list_devices(self) -> list[dict[str, Any]]:
        session = TraccarSession(self.source)
        try:
            await session.login()
            devices = await session.devices()
        finally:
            await session.close()
        return [
            {
                "external_id": str(device_id),
                "name": device.get("name"),
                "unique_id": device.get("uniqueId"),
                "status": device.get("status"),
                "last_update": device.get("lastUpdate"),
                "attributes": device_attributes(device),
            }
            for device_id, device in devices.items()
        ]

    async def test_connection(self) -> dict[str, Any]:
        session = TraccarSession(self.source)
        try:
            await session.login()
            devices = await session.devices()
        finally:
            await session.close()
        return {"ok": True, "devices": len(devices)}


class TraccarAdapter:
    key: ClassVar[str] = "traccar"
    label: ClassVar[str] = "Traccar"
    push: ClassVar[bool] = False
    acquisition_channel: ClassVar[AcquisitionChannel] = AcquisitionChannel.CELLULAR
    config_example: ClassVar[dict[str, Any]] = {
        "url": "https://demo.traccar.org",
        "web_url": "https://demo.traccar.org",
    }
    credentials_schema: ClassVar[dict[str, str]] = {
        "email": "Traccar user email",
        "password": "Traccar user password",
        "token": "API token instead of email and password (optional)",
    }
    setup_hint: ClassVar[str] = (
        "Create a Traccar user that sees the devices to import. Device types for these "
        "trackers use the Generic JSON driver; the Traccar device id is the external identity."
    )
    default_capabilities: ClassVar[AdapterCapabilities] = AdapterCapabilities(
        uplink=True,
        downlink=True,
        device_management=True,
        statistics=False,
    )
    channels: ClassVar[list[dict[str, Any]]] = [
        {
            "key": "stream",
            "label": "Traccar websocket",
            "direction": "in",
            "purpose": "The ingest service follows the server's live positions and events",
            "config_keys": ["url"],
            "credential_keys": [],
            "optional_credential_keys": ["email", "password", "token"],
            "hint": "email and password, or token",
        },
        {
            "key": "api",
            "label": "Traccar API",
            "direction": "out",
            "purpose": "Device list and commands",
            "config_keys": ["url"],
            "credential_keys": [],
            "capabilities": ["downlink", "device_management"],
        },
    ]
    default_link_templates: ClassVar[dict[str, str]] = {
        "OPEN_DEVICE": "{web_url}/settings/device/{external_id}",
    }
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "required": ["url"],
        "properties": {
            "url": {"type": "string", "description": "Traccar server, http or https"},
            "web_url": {"type": "string", "description": "Traccar web app, for deep links"},
        },
    }

    def event_connector(self, source: DataSourceContext) -> EventConnector | None:
        return TraccarConnector(source)

    def command_connector(self, source: DataSourceContext) -> TraccarCommands:
        return TraccarCommands(source)

    def management_connector(self, source: DataSourceContext) -> TraccarManagement:
        return TraccarManagement(source)

    def parse_webhook(
        self, source: DataSourceContext, body: Any, headers: dict[str, str]
    ) -> list[InboundMessage]:
        """Traccar's event forwarding posts `{"event": ..., "device": ..., "position": ...}`;
        position forwarding posts `{"position": ..., "device": ...}`."""
        if not isinstance(body, dict):
            raise _error("Traccar webhook body must be a JSON object")
        device = body.get("device") if isinstance(body.get("device"), dict) else None
        position = body.get("position") if isinstance(body.get("position"), dict) else None
        messages: list[InboundMessage] = []
        if isinstance(body.get("event"), dict):
            messages.append(
                parse_event(source, body["event"], device, position, method=IngestionMethod.WEBHOOK)
            )
        elif position is not None:
            messages.append(
                parse_position(source, position, device, method=IngestionMethod.WEBHOOK)
            )
        else:
            raise _error("Traccar webhook body carries neither an event nor a position")
        return messages
