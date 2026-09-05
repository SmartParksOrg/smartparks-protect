"""KPN LoRa on Actility ThingPark (architecture 7.2, decision D53).

Events: ThingPark's HTTP application server pushes one JSON document per event to the source's
webhook URL with the per-source bearer token: `DevEUI_uplink` (uplink), `DevEUI_downlink_Sent`
(downlink status), `DevEUI_location` (network geolocation) and `DevEUI_notification`. Each
reception by an LRR (gateway) is listed under `Lrrs`. Downlinks go to the ThingPark downlink
API: `POST {downlink_url}` with `DevEUI`, `FPort`, `Payload` (hex) and, in `token` mode, the
application server id, a time and a SHA-256 token over the query and the AS key; in `bearer`
mode an `Authorization: Bearer` header. Capabilities differ per subscription (architecture 8.2):
a public KPN account exposes no gateway management and no statistics.

Config keys: `downlink_url` (the ThingPark downlink endpoint), `auth_mode` (`token` or
`bearer`), `as_id`, `web_url` (the ThingPark portal, for deep links), `flush_downlinks`
(default false). Credentials: `as_key` (token mode) or `api_token` (bearer mode).

Built from the ThingPark documentation; the live run against a KPN account adds recorded
payloads to the fixtures and confirms the downlink security scheme.
"""

import hashlib
import json
from datetime import datetime
from typing import Any, ClassVar

import httpx

from shared.connectivity.base import (
    AdapterCapabilities,
    DataSourceContext,
    EventConnector,
    GatewayReceptionData,
    InboundMessage,
)
from shared.connectivity.transports.http import require_object
from shared.enums import AcquisitionChannel, ErrorCode, IngestionMethod
from shared.logger import get_logger
from shared.timeutil import require_aware, utc_now
from shared.trace import ApplicationError

log = get_logger("adapter.kpn_thingpark")

EVENT_TYPES: dict[str, str] = {
    "DevEUI_uplink": "uplink",
    "DevEUI_downlink_Sent": "downlink_transmitted",
    "DevEUI_location": "location",
    "DevEUI_notification": "log",
}


def parse_thingpark_time(value: Any) -> datetime | None:
    """ISO 8601 with offset, for example `2026-09-04T10:12:03.421+02:00`."""
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return require_aware(datetime.fromisoformat(text))
    except ValueError as exc:
        raise ApplicationError(
            code=ErrorCode.TIMESTAMP_INVALID,
            message=f"ThingPark time {value!r} is not ISO 8601 with offset: {exc}",
            component="adapter.kpn_thingpark",
        ) from exc


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _spreading_factor(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def parse_event(source: DataSourceContext, body: Any) -> InboundMessage:
    document = require_object(body, "kpn_thingpark")
    kind = next((k for k in EVENT_TYPES if k in document), None)
    if kind is None:
        raise ApplicationError(
            code=ErrorCode.PAYLOAD_DECODE_FAILED,
            message=f"not a ThingPark event: expected one of {', '.join(EVENT_TYPES)}",
            component="adapter.kpn_thingpark",
            user_actionable=True,
        )
    data = require_object(document[kind], "kpn_thingpark")
    dev_eui = str(data.get("DevEUI") or "").upper() or None
    receptions: list[GatewayReceptionData] = []
    for lrr in (
        ((data.get("Lrrs") or {}).get("Lrr") or []) if isinstance(data.get("Lrrs"), dict) else []
    ):
        if not isinstance(lrr, dict) or not lrr.get("Lrrid"):
            continue
        receptions.append(
            GatewayReceptionData(
                gateway_id=str(lrr["Lrrid"]).lower(),
                rssi=_number(lrr.get("LrrRSSI")),
                snr=_number(lrr.get("LrrSNR")),
                attributes={k: v for k, v in lrr.items() if k in ("Chain", "LrrESP")},
            )
        )
    payload_hex = data.get("payload_hex")
    metadata: dict[str, Any] = {
        "thingpark_event": kind,
        "f_port": int(data["FPort"]) if data.get("FPort") not in (None, "") else None,
        "f_cnt": int(data["FCntUp"]) if data.get("FCntUp") not in (None, "") else None,
        "f_cnt_down": int(data["FCntDn"]) if data.get("FCntDn") not in (None, "") else None,
        "spreading_factor": _spreading_factor(data.get("SpFact")),
        "channel": data.get("Channel"),
        "sub_band": data.get("SubBand"),
        "best_rssi": _number(data.get("LrrRSSI")),
        "best_snr": _number(data.get("LrrSNR")),
        "gateway_count": int(data.get("DevLrrCnt") or len(receptions) or 0),
        "late": data.get("Late"),
        "dev_addr": data.get("DevAddr"),
        "customer_id": data.get("CustomerID"),
    }
    if isinstance(payload_hex, str) and payload_hex:
        metadata["frame_hex"] = payload_hex
    if kind == "DevEUI_downlink_Sent":
        metadata["delivery_status"] = data.get("DeliveryStatus")
        metadata["queue_ref"] = data.get("CorrelationID") or data.get("FlowId") or data.get("Lrcid")
    return InboundMessage(
        external_id=dev_eui,
        event_type=EVENT_TYPES[kind],
        payload=document,
        acquisition_channel=AcquisitionChannel.LORAWAN,
        ingestion_method=IngestionMethod.WEBHOOK,
        provider_metadata={k: v for k, v in metadata.items() if v is not None},
        network_received_at=parse_thingpark_time(data.get("Time")),
        identity_type="dev_eui",
        identity_attributes={
            k: v
            for k, v in {
                "customer_id": data.get("CustomerID"),
                "dev_addr": data.get("DevAddr"),
                "model_cfg": data.get("ModelCfg"),
            }.items()
            if v not in (None, "")
        },
        gateway_receptions=receptions,
    )


def downlink_token(query: dict[str, str], as_key: str) -> str:
    """ThingPark `Token`: SHA-256 over the query string (in this order) followed by the AS key."""
    ordered = "&".join(f"{k}={v}" for k, v in query.items())
    return hashlib.sha256((ordered + as_key).encode()).hexdigest()


class ThingParkCommands:
    """Command connector: the ThingPark downlink API."""

    def __init__(self, source: DataSourceContext) -> None:
        self.source = source
        self.url = str(source.config.get("downlink_url") or "").strip()
        self.auth_mode = str(source.config.get("auth_mode") or "token")
        self.as_id = str(source.config.get("as_id") or "")
        self.as_key = str(source.credentials.get("as_key") or "")
        self.api_token = str(source.credentials.get("api_token") or "")

    async def submit(
        self, external_id: str, payload: bytes, options: dict[str, Any]
    ) -> dict[str, Any]:
        if not self.url:
            raise ApplicationError(
                code=ErrorCode.COMMAND_REJECTED,
                message="the data source has no downlink_url",
                component="adapter.kpn_thingpark",
                user_actionable=True,
            )
        query: dict[str, str] = {
            "DevEUI": external_id.upper(),
            "FPort": str(int(options["f_port"])),
            "Payload": payload.hex().upper(),
        }
        if options.get("confirmed"):
            query["Confirmed"] = "1"
        if str(options.get("flush", self.source.config.get("flush_downlinks", False))).lower() in (
            "1",
            "true",
        ):
            query["FlushDownlinkQueue"] = "1"
        headers: dict[str, str] = {}
        if self.auth_mode == "bearer":
            headers["Authorization"] = f"Bearer {self.api_token}"
        else:
            query["AS_ID"] = self.as_id
            query["Time"] = utc_now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+00:00"
            query["Token"] = downlink_token(query, self.as_key)
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(self.url, params=query, headers=headers)
        if response.status_code in (401, 403):
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_AUTH_FAILED,
                message=f"ThingPark refused the downlink credentials ({response.status_code})",
                component="adapter.kpn_thingpark",
                user_actionable=True,
            )
        if response.status_code >= 500:
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
                message=f"ThingPark answered {response.status_code}: {response.text[:200]}",
                component="adapter.kpn_thingpark",
                retryable=True,
            )
        if response.status_code >= 400:
            raise ApplicationError(
                code=ErrorCode.COMMAND_REJECTED,
                message=(
                    f"ThingPark rejected the downlink ({response.status_code}): "
                    f"{response.text[:200]}"
                ),
                component="adapter.kpn_thingpark",
                user_actionable=True,
            )
        reference = None
        try:
            parsed = response.json()
            if isinstance(parsed, dict):
                reference = parsed.get("CorrelationID") or parsed.get("FlowId") or parsed.get("id")
        except ValueError:
            parsed = response.text[:500]
        return {
            "provider_ref": str(reference) if reference else None,
            "statuses": ["accepted_by_network"],
            "response": parsed,
        }


class KpnThingParkAdapter:
    key: ClassVar[str] = "kpn_thingpark"
    label: ClassVar[str] = "KPN LoRa (ThingPark)"
    push: ClassVar[bool] = True
    acquisition_channel: ClassVar[AcquisitionChannel] = AcquisitionChannel.LORAWAN
    default_capabilities: ClassVar[AdapterCapabilities] = AdapterCapabilities(
        uplink=True,
        downlink=True,
        join_events=False,
        downlink_status=True,
        mac_events=False,
        device_management=False,
        gateway_metadata=True,
        gateway_management=False,
        gateway_status=False,
        statistics=False,
    )
    channels: ClassVar[list[dict[str, Any]]] = [
        {
            "key": "http",
            "label": "Application server (HTTP)",
            "direction": "in",
            "purpose": "ThingPark posts uplinks and downlink events to the webhook URL",
            "config_keys": [],
            "credential_keys": [],
        },
        {
            "key": "api",
            "label": "Downlink API",
            "direction": "out",
            "purpose": "Downlinks through the LRC downlink endpoint",
            "config_keys": ["downlink_url"],
            "optional_keys": ["auth_mode", "as_id", "flush_downlinks"],
            "credential_keys": [],
            "optional_credential_keys": ["as_key", "api_token"],
            "capabilities": ["downlink"],
            "hint": "auth_mode token needs as_id and the as_key credential; bearer needs api_token",
        },
    ]
    default_link_templates: ClassVar[dict[str, str]] = {
        "OPEN_DEVICE": "{web_url}/devices/{external_id}",
    }
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "downlink_url": {"type": "string", "description": "ThingPark downlink API endpoint"},
            "auth_mode": {"type": "string", "enum": ["token", "bearer"], "default": "token"},
            "as_id": {"type": "string", "description": "Application server id (token mode)"},
            "web_url": {"type": "string", "description": "ThingPark portal, for deep links"},
            "flush_downlinks": {"type": "boolean", "default": False},
        },
    }
    config_example: ClassVar[dict[str, Any]] = {
        "downlink_url": "https://lrc.thingpark.com/thingpark/lrc/rest/downlink",
        "auth_mode": "token",
        "as_id": "TWA_100000000.1",
        "web_url": "https://wireless-logger.thingpark.com",
    }
    credentials_schema: ClassVar[dict[str, str]] = {
        "as_key": "Application server key (token mode)",
        "api_token": "Bearer token (bearer mode)",
    }
    setup_hint: ClassVar[str] = (
        "Push events from ThingPark to the webhook URL of this data source with the bearer "
        "token as Authorization header."
    )

    def event_connector(self, source: DataSourceContext) -> EventConnector | None:
        return None

    def parse_webhook(
        self, source: DataSourceContext, body: Any, headers: dict[str, str]
    ) -> list[InboundMessage]:
        items = body if isinstance(body, list) else [body]
        return [parse_event(source, item) for item in items]

    def command_connector(self, source: DataSourceContext) -> ThingParkCommands:
        return ThingParkCommands(source)


__all__ = [
    "KpnThingParkAdapter",
    "ThingParkCommands",
    "downlink_token",
    "json",
    "log",
    "parse_event",
]
