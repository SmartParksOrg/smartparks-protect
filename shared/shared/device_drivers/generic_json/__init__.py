"""Generic JSON driver for tests and simple custom devices.

Payload fields (all optional): `time` (ISO 8601 with offset, or unix seconds), `latitude` or
`lat`, `longitude` or `lon`, `altitude`, `speed` (m/s), `heading`, `accuracy`, `satellites`,
`measurements` (object of metric key to value), `state` (object), `events` (list of objects
with `type`, `title`, optional `severity`, `description`, `context`, `lat` and `lon`). Without
`time` the network receive time is canonical (NETWORK_TIME semantics). Application platforms
whose data arrives decoded (a tracking server, a camera platform) deliver this shape and keep
the original record under `raw`, which the driver ignores.

The driver declares one control action, `PLATFORM_COMMAND`: a platform-level command (`type`
plus attributes) encoded as JSON for an adapter whose platform relays commands to its devices.
"""

import json
from datetime import UTC, datetime
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from shared.control.actions import ConfirmationPolicy, ControlAction, EncodedCommand
from shared.device_drivers.base import (
    DEFAULT_DECODABLE_EVENT_TYPES,
    DecodedEvent,
    DecodedMeasurement,
    DecodedPosition,
    DecodedRecords,
    DecodedState,
    SourceEventData,
    TimestampSemantics,
)
from shared.enums import ErrorCode, Severity
from shared.timeutil import require_aware
from shared.trace import ApplicationError


def _time(payload: dict[str, Any], event: SourceEventData) -> tuple[datetime, TimestampSemantics]:
    raw = payload.get("time")
    if raw is None or raw == "":
        if event.network_received_at is None:
            return event.ingested_at, TimestampSemantics.NETWORK_TIME
        return event.network_received_at, TimestampSemantics.NETWORK_TIME
    try:
        if isinstance(raw, int | float):
            return datetime.fromtimestamp(raw, tz=UTC), TimestampSemantics.DEVICE_TIME
        return require_aware(datetime.fromisoformat(str(raw))), TimestampSemantics.DEVICE_TIME
    except ValueError as exc:
        raise ApplicationError(
            code=ErrorCode.TIMESTAMP_INVALID,
            message=f"time {raw!r} is not a valid timestamp with offset: {exc}",
            component="driver.generic_json",
            user_actionable=True,
        ) from exc


def _number(payload: dict[str, Any], *names: str) -> float | None:
    for name in names:
        value = payload.get(name)
        if value is not None:
            try:
                return float(value)
            except (TypeError, ValueError) as exc:
                raise ApplicationError(
                    code=ErrorCode.PAYLOAD_DECODE_FAILED,
                    message=f"{name} is not a number: {value!r}",
                    component="driver.generic_json",
                    user_actionable=True,
                ) from exc
    return None


class GenericJsonDriver:
    key: ClassVar[str] = "generic_json"
    label: ClassVar[str] = "Generic JSON"
    capabilities: ClassVar[frozenset[str]] = frozenset({"gnss", "measurements", "state", "events"})
    timestamp_semantics: ClassVar[dict[str, TimestampSemantics]] = {
        "gnss": TimestampSemantics.DEVICE_TIME,
        "measurement": TimestampSemantics.DEVICE_TIME,
        "state": TimestampSemantics.DEVICE_TIME,
        "event": TimestampSemantics.DEVICE_TIME,
    }

    decodable_event_types: ClassVar[frozenset[str]] = DEFAULT_DECODABLE_EVENT_TYPES | frozenset(
        {"position", "event", "state", "detection"}
    )

    def decode(self, event: SourceEventData) -> DecodedRecords:
        payload: Any = event.payload
        if event.frame is not None:
            try:
                payload = json.loads(event.frame.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ApplicationError(
                    code=ErrorCode.PAYLOAD_DECODE_FAILED,
                    message=f"frame is not JSON: {exc}",
                    component="driver.generic_json",
                    user_actionable=True,
                ) from exc
        if not isinstance(payload, dict):
            raise ApplicationError(
                code=ErrorCode.PAYLOAD_DECODE_FAILED,
                message="payload must be a JSON object",
                component="driver.generic_json",
                user_actionable=True,
            )
        time, _ = _time(payload, event)
        records = DecodedRecords()
        latitude = _number(payload, "latitude", "lat")
        longitude = _number(payload, "longitude", "lon", "lng")
        if latitude is not None and longitude is not None:
            if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
                raise ApplicationError(
                    code=ErrorCode.PAYLOAD_DECODE_FAILED,
                    message=f"coordinates out of range: {latitude}, {longitude}",
                    component="driver.generic_json",
                    user_actionable=True,
                )
            records.positions.append(
                DecodedPosition(
                    time=time,
                    latitude=latitude,
                    longitude=longitude,
                    altitude_m=_number(payload, "altitude"),
                    speed_mps=_number(payload, "speed"),
                    heading_deg=_number(payload, "heading"),
                    accuracy_m=_number(payload, "accuracy"),
                    satellites=int(payload["satellites"])
                    if payload.get("satellites") is not None
                    else None,
                )
            )
        measurements = payload.get("measurements") or {}
        if not isinstance(measurements, dict):
            raise ApplicationError(
                code=ErrorCode.PAYLOAD_DECODE_FAILED,
                message="measurements must be an object",
                component="driver.generic_json",
                user_actionable=True,
            )
        for metric_key, value in measurements.items():
            records.measurements.append(
                DecodedMeasurement(time=time, metric_key=str(metric_key), value=value)
            )
        state = payload.get("state")
        if isinstance(state, dict) and state:
            records.states.append(DecodedState(time=time, state=state))
        for item in payload.get("events") or []:
            if not isinstance(item, dict) or "type" not in item:
                continue
            event_time = time
            if item.get("time") not in (None, ""):
                event_time, _ = _time(item, event)
            records.events.append(
                DecodedEvent(
                    time=event_time,
                    event_type=str(item["type"]),
                    title=str(item.get("title") or item["type"]),
                    severity=Severity(item.get("severity", "info")),
                    description=str(item["description"]) if item.get("description") else None,
                    context=dict(item.get("context") or {}),
                    latitude=_number(item, "latitude", "lat"),
                    longitude=_number(item, "longitude", "lon", "lng"),
                )
            )
        return records

    control_actions: ClassVar[dict[str, Any]] = {}


class PlatformCommandParameters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str = Field(min_length=1, max_length=64, description="Command type of the platform")
    attributes: dict[str, Any] = Field(
        default_factory=dict, description="Parameters the platform expects for that type"
    )


def _encode_platform_command(params: BaseModel) -> EncodedCommand:
    return EncodedCommand(
        payload=json.dumps(params.model_dump(), separators=(",", ":")).encode(),
        f_port=0,
        metadata={"encoding": "json"},
    )


GenericJsonDriver.control_actions = {
    "PLATFORM_COMMAND": ControlAction(
        key="PLATFORM_COMMAND",
        label="Platform command",
        description=(
            "Send a command the platform relays to the device: its type and attributes as "
            "JSON. The adapter of the route maps it to the platform's command API."
        ),
        parameters=PlatformCommandParameters,
        encode=_encode_platform_command,
        confirmation=ConfirmationPolicy.CONFIRM,
        required_capability="downlink",
    )
}
