"""LORIOT (architecture 7.2, decision D54).

Events: the application's websocket output, `wss://{server}/app?token={token}`. LORIOT sends
JSON frames: `rx` (an uplink with hex data, port, frame counter, RSSI, SNR, data rate and the
LORIOT receive time in milliseconds), `gw` (the gateways that received an uplink), `txd` (a
downlink was transmitted, with its sequence number), `txq`/`ack` variants where enabled, and
`cq`/`err` housekeeping. Downlinks are `tx` frames on the same websocket; the command connector
opens a short-lived connection, sends the frame and reads LORIOT's answer.

Config keys: `server` (for example `eu1.loriot.io`), `app_id` (hex application id, for deep
links), `web_url` (default `https://{server}`). Credentials: `token` (the application output
token).

Built from the LORIOT documentation; the live run adds recorded frames to the fixtures.
"""

import asyncio
import json
from datetime import UTC, datetime
from typing import Any, ClassVar

import websockets

from shared.connectivity.base import (
    AdapterCapabilities,
    DataSourceContext,
    Emit,
    EventConnector,
    GatewayReceptionData,
    InboundMessage,
)
from shared.connectivity.transports.websocket import WebsocketConnector
from shared.enums import AcquisitionChannel, ErrorCode, IngestionMethod
from shared.logger import get_logger
from shared.trace import ApplicationError

log = get_logger("adapter.loriot")

EVENT_TYPES: dict[str, str] = {
    "rx": "uplink",
    "gw": "gateway_receptions",
    "txd": "downlink_transmitted",
    "ack": "downlink_ack",
    "err": "log",
}
IGNORED = {"cq", "txq", "tx"}


def ws_url(source: DataSourceContext) -> str:
    server = str(source.config.get("server") or "").strip().rstrip("/")
    token = str(source.credentials.get("token") or "")
    if not server or not token:
        raise ApplicationError(
            code=ErrorCode.CONNECTIVITY_AUTH_FAILED,
            message="the LORIOT source needs `server` in config and `token` in credentials",
            component="adapter.loriot",
            user_actionable=True,
        )
    return f"wss://{server}/app?token={token}"


def _millis(value: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC) if value is not None else None
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _spreading_factor(dr: Any) -> int | None:
    """`SF9 BW125 4/5` to 9."""
    text = str(dr or "")
    if text.startswith("SF"):
        digits = "".join(ch for ch in text[2:4] if ch.isdigit())
        return int(digits) if digits else None
    return None


def parse_frame(source: DataSourceContext, frame: str | bytes) -> InboundMessage | None:
    """One websocket frame to a message, or None for housekeeping frames."""
    try:
        data = json.loads(frame if isinstance(frame, str) else frame.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApplicationError(
            code=ErrorCode.PAYLOAD_DECODE_FAILED,
            message=f"LORIOT frame is not JSON: {exc}",
            component="adapter.loriot",
        ) from exc
    if not isinstance(data, dict):
        raise ApplicationError(
            code=ErrorCode.PAYLOAD_DECODE_FAILED,
            message="LORIOT frame must be a JSON object",
            component="adapter.loriot",
        )
    cmd = str(data.get("cmd") or "")
    if cmd in IGNORED or cmd not in EVENT_TYPES:
        return None
    dev_eui = str(data.get("EUI") or "").upper() or None
    receptions = [
        GatewayReceptionData(
            gateway_id=str(gw.get("gweui") or "").lower(),
            rssi=gw.get("rssi"),
            snr=gw.get("snr"),
            attributes={k: v for k, v in gw.items() if k in ("ant", "lat", "lon", "ts", "tmms")},
        )
        for gw in data.get("gws") or []
        if isinstance(gw, dict) and gw.get("gweui")
    ]
    metadata: dict[str, Any] = {
        "loriot_cmd": cmd,
        "f_port": data.get("port"),
        "f_cnt": data.get("fcnt"),
        "spreading_factor": _spreading_factor(data.get("dr")),
        "data_rate": data.get("dr"),
        "frequency_hz": data.get("freq"),
        "best_rssi": data.get("rssi"),
        "best_snr": data.get("snr"),
        "confirmed": data.get("ack"),
        "battery": data.get("bat"),
        "sequence": data.get("seqno"),
        "sequence_down": data.get("seqdn"),
        "gateway_count": len(receptions) or None,
    }
    if cmd == "rx" and isinstance(data.get("data"), str):
        metadata["frame_hex"] = data["data"]
    if cmd == "txd":
        metadata["queue_ref"] = data.get("seqdn")
    return InboundMessage(
        external_id=dev_eui,
        event_type=EVENT_TYPES[cmd],
        payload=data,
        acquisition_channel=AcquisitionChannel.LORAWAN,
        ingestion_method=IngestionMethod.WEBSOCKET,
        provider_metadata={k: v for k, v in metadata.items() if v is not None},
        network_received_at=_millis(data.get("ts")),
        identity_type="dev_eui",
        identity_attributes={"app_id": source.config.get("app_id")}
        if source.config.get("app_id")
        else {},
        gateway_receptions=receptions,
    )


class LoriotConnector(WebsocketConnector):
    def __init__(self, source: DataSourceContext) -> None:
        super().__init__(ws_url(source), source_id=source.id)
        self.source = source

    async def on_frame(self, frame: str | bytes, emit: Emit) -> None:
        try:
            message = parse_frame(self.source, frame)
        except ApplicationError as error:
            log.warning("loriot frame dropped", source=self.source.name, error=str(error))
            return
        if message is not None:
            await emit(message)


async def send_tx(url: str, frame: dict[str, Any], wait_seconds: float = 15.0) -> dict[str, Any]:
    """Open a websocket, send one frame, return LORIOT's first `tx` answer. Separate from the
    connector so tests replace it."""
    async with websockets.connect(url) as connection:
        await connection.send(json.dumps(frame))
        deadline = asyncio.get_running_loop().time() + wait_seconds
        while True:
            remaining = deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                raise TimeoutError("LORIOT did not answer the tx frame")
            raw = await asyncio.wait_for(connection.recv(), timeout=remaining)
            answer = json.loads(raw if isinstance(raw, str) else raw.decode("utf-8"))
            if isinstance(answer, dict) and answer.get("cmd") == "tx":
                return answer


class LoriotCommands:
    """Command connector: a `tx` frame on the application websocket."""

    def __init__(self, source: DataSourceContext) -> None:
        self.source = source

    async def submit(
        self, external_id: str, payload: bytes, options: dict[str, Any]
    ) -> dict[str, Any]:
        frame = {
            "cmd": "tx",
            "EUI": external_id.upper(),
            "port": int(options["f_port"]),
            "confirmed": bool(options.get("confirmed", False)),
            "data": payload.hex().upper(),
        }
        try:
            answer = await send_tx(ws_url(self.source), frame)
        except ApplicationError:
            raise
        except (TimeoutError, OSError, websockets.WebSocketException) as exc:
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
                message=f"LORIOT websocket: {type(exc).__name__}: {exc}",
                component="adapter.loriot",
                retryable=True,
            ) from exc
        if not answer.get("success", True) or answer.get("error"):
            raise ApplicationError(
                code=ErrorCode.COMMAND_REJECTED,
                message=f"LORIOT rejected the downlink: {answer.get('error') or answer}",
                component="adapter.loriot",
                user_actionable=True,
            )
        reference = answer.get("seqno") or answer.get("seqdn")
        return {
            "provider_ref": str(reference) if reference is not None else None,
            "statuses": ["accepted_by_network", "queued"],
            "response": answer,
        }


class LoriotAdapter:
    key: ClassVar[str] = "loriot"
    label: ClassVar[str] = "LORIOT"
    push: ClassVar[bool] = (
        True  # the HTTP integration posts to the webhook; MQTT/websocket is optional
    )
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
            "key": "stream",
            "label": "Websocket output",
            "direction": "in",
            "purpose": "The ingest service connects to the application's websocket output; "
            "downlinks go over the same connection",
            "config_keys": ["server"],
            "credential_keys": ["token"],
            "capabilities": ["downlink"],
        },
        {
            "key": "http",
            "label": "HTTP output",
            "direction": "in",
            "purpose": "LORIOT's HTTP output posts the same frames to the webhook URL",
            "config_keys": [],
            "credential_keys": [],
        },
    ]
    default_link_templates: ClassVar[dict[str, str]] = {
        "OPEN_DEVICE": "{web_url}/#/app/{app_id}/device/{external_id}",
        "OPEN_APPLICATION": "{web_url}/#/app/{app_id}",
    }
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "required": ["server"],
        "properties": {
            "server": {"type": "string", "description": "LORIOT server, for example eu1.loriot.io"},
            "app_id": {"type": "string", "description": "Application id, for deep links"},
            "web_url": {"type": "string", "description": "LORIOT web UI, for deep links"},
        },
    }
    config_example: ClassVar[dict[str, Any]] = {
        "server": "eu1.loriot.io",
        "app_id": "BE7A0001",
        "web_url": "https://eu1.loriot.io",
    }
    credentials_schema: ClassVar[dict[str, str]] = {"token": "Application websocket output token"}
    setup_hint: ClassVar[str] = (
        "Create a websocket output on the LORIOT application and paste its token; the ingest "
        "service connects within a minute."
    )

    def event_connector(self, source: DataSourceContext) -> EventConnector | None:
        return LoriotConnector(source)

    def parse_webhook(
        self, source: DataSourceContext, body: Any, headers: dict[str, str]
    ) -> list[InboundMessage]:
        """LORIOT's HTTP output posts the same frames as JSON; accept one or a list."""
        items = body if isinstance(body, list) else [body]
        messages = []
        for item in items:
            message = parse_frame(source, json.dumps(item))
            if message is not None:
                message.ingestion_method = IngestionMethod.WEBHOOK
                messages.append(message)
        return messages

    def command_connector(self, source: DataSourceContext) -> LoriotCommands:
        return LoriotCommands(source)
