"""Skeleton of a device driver. Copy to `shared/device_drivers/<family>/`, implement `decode`,
register it in `shared/device_drivers/registry.py`, add recorded payloads and golden tests under
`tests/fixtures/payloads/<family>/`, and document the family under `docs/devices/<family>.md`.
"""

from datetime import UTC, datetime
from typing import ClassVar

from shared.device_drivers.base import (
    DecodedMeasurement,
    DecodedPosition,
    DecodedRecords,
    SourceEventData,
    TimestampSemantics,
)
from shared.enums import ErrorCode
from shared.trace import ApplicationError


class ExampleDeviceDriver:
    key: ClassVar[str] = "example_device"
    label: ClassVar[str] = "Example device"
    capabilities: ClassVar[frozenset[str]] = frozenset({"gnss", "battery"})
    timestamp_semantics: ClassVar[dict[str, TimestampSemantics]] = {
        "gnss": TimestampSemantics.DEVICE_TIME,
        "measurement": TimestampSemantics.DEVICE_TIME,
    }

    def decode(self, event: SourceEventData) -> DecodedRecords:
        payload = event.payload
        try:
            time = datetime.fromtimestamp(int(payload["ts"]), tz=UTC)
            latitude, longitude = float(payload["lat"]), float(payload["lon"])
            battery = float(payload["bat"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ApplicationError(
                code=ErrorCode.PAYLOAD_DECODE_FAILED,
                message=f"cannot decode {self.key} payload: {exc}",
                component=f"driver.{self.key}",
                user_actionable=True,
            ) from exc
        records = DecodedRecords(decoder_version="1")
        records.positions.append(DecodedPosition(time=time, latitude=latitude, longitude=longitude))
        records.measurements.append(
            DecodedMeasurement(time=time, metric_key="battery_voltage", value=battery)
        )
        return records
