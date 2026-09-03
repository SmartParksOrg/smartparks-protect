"""Generic JSON driver for tests and simple custom devices.

Payload fields (all optional): `time` (ISO 8601 with offset, or unix seconds), `latitude` or
`lat`, `longitude` or `lon`, `altitude`, `speed` (m/s), `heading`, `accuracy`, `satellites`,
`measurements` (object of metric key to value), `state` (object), `events` (list of objects
with `type`, `title`, optional `severity` and `context`). Without `time` the network receive
time is canonical (NETWORK_TIME semantics).
"""

from datetime import UTC, datetime
from typing import Any, ClassVar

from shared.device_drivers.base import (
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

    def decode(self, event: SourceEventData) -> DecodedRecords:
        payload = event.payload
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
            records.events.append(
                DecodedEvent(
                    time=time,
                    event_type=str(item["type"]),
                    title=str(item.get("title") or item["type"]),
                    severity=Severity(item.get("severity", "info")),
                    context=dict(item.get("context") or {}),
                )
            )
        return records
