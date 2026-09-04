"""akenza.io (decision D59), from docs.akenza.io (webhook output connector, uplink event
structure, downlink object, REST API) and the published akenza API collection.

Events: a Webhook output connector posts the whole emitted sample as the request body to the
source's webhook URL, with static headers (the bearer token). For a LoRaWAN device whose device
type keeps the raw frame, the sample is `{"data": {"port", "payloadHex"}, "uplinkMetrics":
{"deviceId", "timestamp", "port", "frameCountUp", "frameCountDown", "rssi", "snr", "sf",
"txPower", "numberOfGateways", "esp", "sqi", "latitude", "longitude"}, "device": {"id",
"deviceId", "name", "description", "customFields"}, "topic", "timestamp"}`. A sample without
`data.payloadHex` (a decoding device type) is refused with an explanation.

Identity: the akenza device id (`device.id`), because downlinks address it; `device.deviceId`
(the DevEUI of a LoRaWAN device) is kept as an identity attribute.

Downlinks: `POST {api_url}/v3/devices/{id}/downlink` with the `x-api-key` header and
`{"raw": true, "loraDownlink": {"port", "payloadHex", "confirmed"}}` (the collection's "Send raw
LoRa downlink" request). Akenza reports no queue; the network behind it (LORIOT, TTN,
Swisscom, ChirpStack) transmits.

Config: `api_url` (default `https://api.akenza.io`), `web_url` (default
`https://app.akenza.io`), `workspace_id` (for deep links). Credentials: `api_key`.
"""

from datetime import datetime
from typing import Any, ClassVar

import httpx

from shared.connectivity.base import (
    AdapterCapabilities,
    DataSourceContext,
    EventConnector,
    InboundMessage,
)
from shared.connectivity.transports.http import require_object
from shared.enums import AcquisitionChannel, ErrorCode, IngestionMethod
from shared.logger import get_logger
from shared.timeutil import require_aware
from shared.trace import ApplicationError

log = get_logger("adapter.akenza")

DEFAULT_API_URL = "https://api.akenza.io"
DEFAULT_WEB_URL = "https://app.akenza.io"


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return require_aware(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError as exc:
        raise ApplicationError(
            code=ErrorCode.TIMESTAMP_INVALID,
            message=f"akenza timestamp {value!r} is not ISO 8601: {exc}",
            component="adapter.akenza",
        ) from exc


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def parse_sample(source: DataSourceContext, body: Any) -> InboundMessage:
    sample = require_object(body, "akenza")
    data: dict[str, Any] = sample["data"] if isinstance(sample.get("data"), dict) else {}
    device: dict[str, Any] = sample["device"] if isinstance(sample.get("device"), dict) else {}
    metrics: dict[str, Any] = (
        sample["uplinkMetrics"] if isinstance(sample.get("uplinkMetrics"), dict) else {}
    )
    akenza_id = str(device.get("id") or metrics.get("deviceId") or "").strip() or None
    payload_hex = data.get("payloadHex")
    if not isinstance(payload_hex, str) or not payload_hex:
        raise ApplicationError(
            code=ErrorCode.PAYLOAD_DECODE_FAILED,
            message=(
                "akenza sample carries no data.payloadHex; use a device type that keeps the "
                "raw frame (a passthrough uplink script emitting port and payloadHex)"
            ),
            component="adapter.akenza",
            user_actionable=True,
        )
    metadata: dict[str, Any] = {
        "akenza_topic": sample.get("topic"),
        "frame_hex": payload_hex,
        "f_port": _int(data.get("port") if data.get("port") is not None else metrics.get("port")),
        "f_cnt": metrics.get("frameCountUp"),
        "f_cnt_down": metrics.get("frameCountDown"),
        "spreading_factor": metrics.get("sf"),
        "best_rssi": _number(metrics.get("rssi")),
        "best_snr": _number(metrics.get("snr")),
        "tx_power": metrics.get("txPower"),
        "gateway_count": metrics.get("numberOfGateways"),
        "esp": metrics.get("esp"),
        "sqi": metrics.get("sqi"),
        "uplink_id": metrics.get("uplinkId"),
        "latitude": metrics.get("latitude"),
        "longitude": metrics.get("longitude"),
    }
    identity = {
        k: v
        for k, v in {
            "device_id": device.get("deviceId"),
            "dev_eui": device.get("deviceId"),
            "name": device.get("name"),
            "description": device.get("description"),
            "custom_fields": device.get("customFields"),
            "workspace_id": source.config.get("workspace_id"),
        }.items()
        if v not in (None, "", {})
    }
    return InboundMessage(
        external_id=akenza_id,
        event_type="uplink",
        payload=sample,
        acquisition_channel=AcquisitionChannel.LORAWAN,
        ingestion_method=IngestionMethod.WEBHOOK,
        provider_metadata={k: v for k, v in metadata.items() if v is not None},
        network_received_at=parse_time(metrics.get("timestamp") or sample.get("timestamp")),
        identity_type="akenza_device_id",
        identity_attributes=identity,
    )


class AkenzaCommands:
    """Command connector: the akenza REST downlink for a LoRaWAN device."""

    def __init__(self, source: DataSourceContext) -> None:
        self.base = str(source.config.get("api_url") or DEFAULT_API_URL).rstrip("/")
        self.api_key = str(source.credentials.get("api_key") or "")

    async def submit(
        self, external_id: str, payload: bytes, options: dict[str, Any]
    ) -> dict[str, Any]:
        if not self.api_key:
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_AUTH_FAILED,
                message="the akenza source has no api_key credential",
                component="adapter.akenza",
                user_actionable=True,
            )
        body = {
            "raw": True,
            "loraDownlink": {
                "port": int(options["f_port"]),
                "payloadHex": payload.hex(),
                "confirmed": bool(options.get("confirmed", False)),
            },
        }
        async with httpx.AsyncClient(
            base_url=self.base,
            headers={"x-api-key": self.api_key, "Content-Type": "application/json"},
            timeout=15,
        ) as client:
            response = await client.post(f"/v3/devices/{external_id}/downlink", json=body)
        if response.status_code in (401, 403):
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_AUTH_FAILED,
                message=f"akenza refused the API key ({response.status_code})",
                component="adapter.akenza",
                user_actionable=True,
            )
        if response.status_code == 404:
            raise ApplicationError(
                code=ErrorCode.DEVICE_NOT_FOUND,
                message=f"akenza does not know device {external_id}",
                component="adapter.akenza",
                user_actionable=True,
            )
        if response.status_code >= 500:
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
                message=f"akenza answered {response.status_code}: {response.text[:200]}",
                component="adapter.akenza",
                retryable=True,
            )
        if response.status_code >= 400:
            raise ApplicationError(
                code=ErrorCode.COMMAND_REJECTED,
                message=(
                    f"akenza rejected the downlink ({response.status_code}): {response.text[:200]}"
                ),
                component="adapter.akenza",
                user_actionable=True,
            )
        try:
            parsed: Any = response.json() if response.content else {}
        except ValueError:
            parsed = response.text[:200]
        reference = None
        if isinstance(parsed, dict):
            reference = parsed.get("id") or parsed.get("downlinkId") or parsed.get("messageId")
        return {
            "provider_ref": str(reference) if reference else None,
            "statuses": ["accepted_by_network"],
            "response": parsed,
        }


class AkenzaAdapter:
    key: ClassVar[str] = "akenza"
    label: ClassVar[str] = "akenza.io"
    push: ClassVar[bool] = True
    acquisition_channel: ClassVar[AcquisitionChannel] = AcquisitionChannel.LORAWAN
    default_capabilities: ClassVar[AdapterCapabilities] = AdapterCapabilities(
        uplink=True,
        downlink=True,
        join_events=False,
        downlink_status=False,
        mac_events=False,
        device_management=False,
        gateway_metadata=False,
        gateway_management=False,
        gateway_status=False,
        statistics=False,
    )
    default_link_templates: ClassVar[dict[str, str]] = {
        "OPEN_DEVICE": "{web_url}/#/{workspace_id}/devices/{external_id}",
    }
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "api_url": {"type": "string", "default": DEFAULT_API_URL},
            "web_url": {"type": "string", "default": DEFAULT_WEB_URL},
            "workspace_id": {"type": "string", "description": "For deep links"},
        },
    }
    config_example: ClassVar[dict[str, Any]] = {
        "api_url": DEFAULT_API_URL,
        "web_url": DEFAULT_WEB_URL,
        "workspace_id": "",
    }
    credentials_schema: ClassVar[dict[str, str]] = {"api_key": "Organization API key (downlinks)"}
    setup_hint: ClassVar[str] = (
        "Add a Webhook output connector on the data flow with the webhook URL and an "
        "Authorization header holding the bearer token; the device type must keep the raw "
        "frame (port and payloadHex). Devices are identified by their akenza id."
    )

    def event_connector(self, source: DataSourceContext) -> EventConnector | None:
        return None

    def parse_webhook(
        self, source: DataSourceContext, body: Any, headers: dict[str, str]
    ) -> list[InboundMessage]:
        items = body if isinstance(body, list) else [body]
        return [parse_sample(source, item) for item in items]

    def command_connector(self, source: DataSourceContext) -> AkenzaCommands:
        return AkenzaCommands(source)
