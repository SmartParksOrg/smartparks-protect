"""CRA IoT, the platform of České Radiokomunikace behind the Czech national LoRaWAN network
(decision D90).

Built from the public documentation (github.com/cra-iot/documentation, read 2026-09-04: the
HTTP output, the message structure, the API guide and release notes) and the Swagger document
at `https://api.iot.cra.cz/cxf/api/v1/swagger.json` (IoT Backend API 0.3.1):

- Events: the platform's "HTTP endpoint" output posts an integration envelope
  `{"type": "D", "data": "<message as a JSON string>", "tech": "L", "tags": [...]}`. The
  message has LORIOT's shape: `cmd` (`rx` the first gateway's copy, `gw` the deduplicated
  message with every gateway), `seqno`, `EUI`, `ts` (server time, milliseconds), `fcnt`,
  `port`, `freq`, `toa`, `dr`, `ack`, `gws` (`gweui`, `rssi`, `snr`, `ts`, `time`, `tmms`,
  `ant`, `lat`, `lon`; the coordinates and times were dropped in the 2024-07 release), `bat`
  (the DevStatus byte: 0 external power, 255 unknown, 1 to 254 as 0 to 100 %), `data` (the
  decrypted frame in hex, present when the AppSKey is on the platform) or `encdata`, `_id`.
  `geo` messages carried the network geolocation (`lat`, `lon`, `alt`, `accuracy`,
  `method`), a service no longer offered.
- API: every call carries `Authorization: Bearer <access_token>`; the token comes from the CRA
  single sign-on (`POST https://sso.cra.cz/auth/realms/CRA/protocol/openid-connect/token`,
  password grant, `client_id=iot-api-client` with the client secret printed in the guide).
  Answers wrap `status`, `metadata` (`count`, `result`) and `data`; errors carry
  `status: error`, `code` and `errors`. Lists page with `offset` and `limit`.
- Downlinks: `POST /lora/devices/{id}/down/messages` with `{"cmd": "tx", "port", "data",
  "EUI", "confirmed", "clear"}` answers `{"status": "success"}`.
- Devices: `GET /lora/devices` items carry `deviceId` (the DevEUI for LoRa), `custDeviceName`,
  `status`, `enabled`, `lastMessageIn`, `signalStrength`, `bateryStatus`.

Config: `api_url`, `sso_url`, `client_id`, `uplink_cmd` (`gw` by default; `rx` on a platform
that sends only those), `web_url`. Credentials: `username`, `password`, optional
`client_secret` (the documented value is the default). Live verification waits for an
account with a LoRa device.
"""

import json
import time
from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx

from shared.connectivity.adapters.loriot import _millis, _spreading_factor
from shared.connectivity.base import (
    AdapterCapabilities,
    DataSourceContext,
    EventConnector,
    GatewayReceptionData,
    InboundMessage,
)
from shared.enums import AcquisitionChannel, ErrorCode, IngestionMethod
from shared.logger import get_logger
from shared.trace import ApplicationError

log = get_logger("adapter.cra_iot")

DEFAULT_API_URL = "https://api.iot.cra.cz/cxf/api/v1"
DEFAULT_SSO_URL = "https://sso.cra.cz/auth/realms/CRA/protocol/openid-connect/token"
DEFAULT_CLIENT_ID = "iot-api-client"
DOCUMENTED_CLIENT_SECRET = "41a113b7-5486-45e3-8a3d-e0b106a5d446"  # the same for every user
DEFAULT_WEB_URL = "https://portal.iot.cra.cz"
DEFAULT_UPLINK_CMD = "gw"
UPLINK_CMDS = ("gw", "rx")
HTTP_TIMEOUT = 30.0
PAGE_SIZE = 100
MAX_PAGES = 100
TOKEN_MARGIN_SECONDS = 30

_tokens: dict[str, tuple[float, str]] = {}


def _error(message: str, code: ErrorCode = ErrorCode.PAYLOAD_DECODE_FAILED) -> ApplicationError:
    return ApplicationError(
        code=code, message=message, component="adapter.cra_iot", user_actionable=True
    )


def battery_percent(bat: Any) -> int | None:
    """The DevStatus byte as a percentage: 1 to 254 span 0 to 100 %, 0 and 255 carry none."""
    try:
        value = int(bat)
    except (TypeError, ValueError):
        return None
    if value <= 0 or value >= 255:
        return None
    return round((value - 1) / 253 * 100)


def _number(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def parse_message(source: DataSourceContext, data: Any) -> InboundMessage | None:
    """One platform message (the inner JSON) to a message, or None for what is ignored."""
    if not isinstance(data, dict):
        raise _error("CRA IoT message must be a JSON object")
    cmd = str(data.get("cmd") or "")
    uplink_cmd = str(source.config.get("uplink_cmd") or DEFAULT_UPLINK_CMD)
    dev_eui = str(data.get("EUI") or "").upper() or None
    if cmd in UPLINK_CMDS and cmd != uplink_cmd:
        return None
    if cmd not in (*UPLINK_CMDS, "geo"):
        return None
    receptions = [
        GatewayReceptionData(
            gateway_id=str(gw.get("gweui") or "").lower(),
            rssi=_number(gw.get("rssi")),
            snr=_number(gw.get("snr")),
            attributes={
                k: v
                for k, v in gw.items()
                if k in ("ant", "lat", "lon", "ts", "tmms", "time") and v not in (None, 0, "")
            },
        )
        for gw in data.get("gws") or []
        if isinstance(gw, dict) and gw.get("gweui")
    ]
    metadata: dict[str, Any] = {
        "cra_cmd": cmd,
        "message_id": data.get("_id"),
        "f_port": data.get("port"),
        "f_cnt": data.get("fcnt"),
        "spreading_factor": _spreading_factor(data.get("dr")),
        "data_rate": data.get("dr"),
        "frequency_hz": data.get("freq"),
        "time_on_air_ms": data.get("toa"),
        "best_rssi": data.get("rssi"),
        "best_snr": data.get("snr"),
        "confirmed": data.get("ack"),
        "battery_raw": data.get("bat"),
        "battery_percent": battery_percent(data.get("bat")),
        "sequence": data.get("seqno"),
        "gateway_count": len(receptions) or None,
    }
    if cmd == "geo":
        metadata.update(
            {
                "latitude": _number(data.get("lat")),
                "longitude": _number(data.get("lon")),
                "altitude_m": _number(data.get("alt")),
                "accuracy_m": _number(data.get("accuracy")),
                "method": data.get("method"),
            }
        )
        event_type = "location"
    else:
        frame = data.get("data")
        if isinstance(frame, str) and frame:
            metadata["frame_hex"] = frame
        elif data.get("encdata"):
            raise _error(
                f"CRA IoT sent an encrypted payload for {dev_eui}: the platform has no AppSKey "
                "for the device"
            )
        event_type = "uplink"
    received = data.get("ts")
    network_time = _millis(received) if isinstance(received, int | float) else None
    if network_time is None and isinstance(received, str):
        try:
            network_time = datetime.fromisoformat(received.replace("Z", "+00:00")).astimezone(UTC)
        except ValueError:
            network_time = None
    return InboundMessage(
        external_id=dev_eui,
        event_type=event_type,
        payload=data,
        acquisition_channel=AcquisitionChannel.LORAWAN,
        ingestion_method=IngestionMethod.WEBHOOK,
        provider_metadata={k: v for k, v in metadata.items() if v is not None},
        network_received_at=network_time,
        identity_type="dev_eui",
        identity_attributes={},
        gateway_receptions=receptions,
    )


def unwrap_envelope(body: Any) -> list[tuple[Any, list[str]]]:
    """The HTTP endpoint's envelope, a bare message, or a list of either: (message, tags)."""
    items = body if isinstance(body, list) else [body]
    unwrapped: list[tuple[Any, list[str]]] = []
    for item in items:
        if isinstance(item, dict) and "type" in item and "cmd" not in item:
            if str(item.get("type")) != "D":
                continue
            data = item.get("data")
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except json.JSONDecodeError as exc:
                    raise _error(f"CRA IoT envelope data is not JSON: {exc}") from exc
            tags = (
                [str(t) for t in item.get("tags") or []]
                if isinstance(item.get("tags"), list)
                else []
            )
            unwrapped.append((data, tags))
        else:
            unwrapped.append((item, []))
    return unwrapped


class CraClient:
    """The REST API with a single sign-on token, cached until it expires."""

    def __init__(self, source: DataSourceContext) -> None:
        self.source = source
        self.base = str(source.config.get("api_url") or DEFAULT_API_URL).rstrip("/")
        self.sso_url = str(source.config.get("sso_url") or DEFAULT_SSO_URL)
        self.client_id = str(source.config.get("client_id") or DEFAULT_CLIENT_ID)
        self.username = str(source.credentials.get("username") or "").strip()
        self.password = str(source.credentials.get("password") or "")
        self.client_secret = str(
            source.credentials.get("client_secret") or DOCUMENTED_CLIENT_SECRET
        )
        if not self.username or not self.password:
            raise _error(
                "the data source needs `username` and `password` in credentials",
                ErrorCode.CONNECTIVITY_AUTH_FAILED,
            )

    async def token(self) -> str:
        key = f"{self.sso_url}|{self.client_id}|{self.username}"
        cached = _tokens.get(key)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        form = {
            "username": self.username,
            "password": self.password,
            "grant_type": "password",
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                response = await client.post(self.sso_url, data=form)
        except httpx.HTTPError as exc:
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
                message=f"CRA single sign-on: {type(exc).__name__}: {exc}",
                component="adapter.cra_iot",
                retryable=True,
            ) from exc
        if response.status_code >= 500:
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
                message=f"CRA single sign-on answered {response.status_code}",
                component="adapter.cra_iot",
                retryable=True,
            )
        body = response.json() if response.content else {}
        if (
            response.status_code >= 400
            or not isinstance(body, dict)
            or not body.get("access_token")
        ):
            detail = (
                body.get("error_description") or body.get("error") if isinstance(body, dict) else ""
            )
            reason = detail or response.text[:200]
            raise _error(
                f"CRA IoT refused the login ({response.status_code}): {reason}",
                ErrorCode.CONNECTIVITY_AUTH_FAILED,
            )
        expires = _number(body.get("expires_in")) or 300
        access_token = str(body["access_token"])
        _tokens[key] = (time.monotonic() + max(expires - TOKEN_MARGIN_SECONDS, 30), access_token)
        return access_token

    @staticmethod
    def _check(response: httpx.Response, what: str) -> Any:
        if response.status_code in (401, 403):
            raise _error(
                f"CRA IoT refused the token for {what} ({response.status_code})",
                ErrorCode.CONNECTIVITY_AUTH_FAILED,
            )
        if response.status_code == 404:
            raise _error(f"CRA IoT does not know {what}", ErrorCode.DEVICE_NOT_FOUND)
        if response.status_code >= 500:
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
                message=f"CRA IoT answered {response.status_code}: {response.text[:200]}",
                component="adapter.cra_iot",
                retryable=True,
            )
        try:
            body = response.json() if response.content else {}
        except ValueError:
            body = {}
        if response.status_code >= 400 or (
            isinstance(body, dict) and body.get("status") == "error"
        ):
            errors = body.get("errors") if isinstance(body, dict) else None
            detail = "; ".join(str(e) for e in errors) if errors else response.text[:200]
            raise _error(
                f"CRA IoT rejected {what} ({response.status_code}): {detail}",
                ErrorCode.COMMAND_REJECTED,
            )
        return body

    async def request(self, method: str, path: str, **kwargs: Any) -> Any:
        headers = {"Authorization": f"Bearer {await self.token()}", "Accept": "application/json"}
        async with httpx.AsyncClient(
            base_url=self.base, timeout=HTTP_TIMEOUT, headers=headers
        ) as client:
            response = await client.request(method, path, **kwargs)
        return self._check(response, path)


class CraCommands:
    """Command connector: the platform's downlink queue for a LoRa device."""

    def __init__(self, source: DataSourceContext) -> None:
        self.source = source

    async def submit(
        self, external_id: str, payload: bytes, options: dict[str, Any]
    ) -> dict[str, Any]:
        dev_eui = external_id.upper()
        body = {
            "cmd": "tx",
            "EUI": dev_eui,
            "port": int(options["f_port"]),
            "data": payload.hex().upper(),
            "confirmed": bool(options.get("confirmed", False)),
            "clear": bool(options.get("clear", False)),
        }
        answer = await CraClient(self.source).request(
            "POST", f"/lora/devices/{dev_eui}/down/messages", json=body
        )
        return {
            "provider_ref": None,
            "statuses": ["accepted_by_network", "queued"],
            "response": answer if isinstance(answer, dict) else {},
        }

    async def flush(self, external_id: str) -> None:
        """The platform clears a queue only together with a new message (`clear`); a plain
        flush has no call."""
        raise _error(
            "CRA IoT clears the queue only with the next downlink (`clear`); use the portal",
            ErrorCode.COMMAND_REJECTED,
        )


def devices_from_listing(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for item in items:
        dev_eui = str(item.get("deviceId") or "").upper()
        if not dev_eui:
            continue
        attributes = {
            k: v
            for k, v in {
                "status": item.get("status"),
                "enabled": item.get("enabled"),
                "cust_service_id": item.get("custServiceId"),
                "project_id": item.get("projectId"),
                "last_message_in": item.get("lastMessageIn"),
                "signal_strength": item.get("signalStrength"),
                "battery_status": item.get("bateryStatus"),
                "hw_device_id": item.get("hwDeviceId"),
            }.items()
            if v not in (None, "")
        }
        result.append(
            {
                "external_id": dev_eui,
                "identity_type": "dev_eui",
                "name": item.get("custDeviceName") or dev_eui,
                "attributes": attributes,
            }
        )
    return result


class CraManagement:
    def __init__(self, source: DataSourceContext) -> None:
        self.source = source

    async def list_devices(self) -> list[dict[str, Any]]:
        client = CraClient(self.source)
        items: list[dict[str, Any]] = []
        for page in range(MAX_PAGES):
            body = await client.request(
                "GET", "/lora/devices", params={"offset": page * PAGE_SIZE, "limit": PAGE_SIZE}
            )
            data = body.get("data") if isinstance(body, dict) else None
            batch = [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []
            items.extend(batch)
            metadata = body.get("metadata") if isinstance(body, dict) else None
            total = metadata.get("count") if isinstance(metadata, dict) else None
            if len(batch) < PAGE_SIZE or (isinstance(total, int) and len(items) >= total):
                break
        return devices_from_listing(items)

    async def test_connection(self) -> dict[str, Any]:
        body = await CraClient(self.source).request(
            "GET", "/lora/devices", params={"offset": 0, "limit": 1}
        )
        metadata = body.get("metadata") if isinstance(body, dict) else None
        count = metadata.get("count") if isinstance(metadata, dict) else None
        return {"ok": True, "device_count": count}


class CraIotAdapter:
    key: ClassVar[str] = "cra_iot"
    label: ClassVar[str] = "CRA IoT (České Radiokomunikace)"
    push: ClassVar[bool] = True
    acquisition_channel: ClassVar[AcquisitionChannel] = AcquisitionChannel.LORAWAN
    default_capabilities: ClassVar[AdapterCapabilities] = AdapterCapabilities(
        uplink=True,
        downlink=True,
        join_events=False,
        downlink_status=False,
        mac_events=False,
        device_management=True,
        gateway_metadata=True,
        gateway_management=False,
        gateway_status=False,
        statistics=False,
    )
    channels: ClassVar[list[dict[str, Any]]] = [
        {
            "key": "http",
            "label": "HTTP endpoint",
            "direction": "in",
            "purpose": "The platform's HTTP endpoint output posts the envelope to the webhook URL",
            "config_keys": [],
            "credential_keys": [],
        },
        {
            "key": "api",
            "label": "REST API",
            "direction": "out",
            "purpose": "Downlinks and the device sync with a single sign-on token",
            "config_keys": [],
            "credential_keys": ["username", "password"],
            "capabilities": ["downlink", "device_management"],
        },
    ]
    default_link_templates: ClassVar[dict[str, str]] = {"OPEN_APPLICATION": "{web_url}"}
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "api_url": {"type": "string", "default": DEFAULT_API_URL},
            "sso_url": {"type": "string", "default": DEFAULT_SSO_URL},
            "client_id": {"type": "string", "default": DEFAULT_CLIENT_ID},
            "uplink_cmd": {
                "type": "string",
                "enum": list(UPLINK_CMDS),
                "default": DEFAULT_UPLINK_CMD,
                "description": "Which message is the uplink: `gw` (deduplicated, every "
                "gateway) or `rx` (the first gateway's copy); the other is ignored",
            },
            "web_url": {"type": "string", "default": DEFAULT_WEB_URL},
        },
    }
    config_example: ClassVar[dict[str, Any]] = {
        "api_url": DEFAULT_API_URL,
        "uplink_cmd": DEFAULT_UPLINK_CMD,
        "web_url": DEFAULT_WEB_URL,
    }
    credentials_schema: ClassVar[dict[str, str]] = {
        "username": "Portal account email (the API's single sign-on)",
        "password": "Portal account password",
        "client_secret": "Client secret of the API client (optional, the documented value is "
        "the default)",
    }
    setup_hint: ClassVar[str] = (
        "In the portal create an HTTP endpoint output with this source's webhook URL and an "
        "`Authorization: Bearer <token>` header, and assign the collars' data flow to it. The "
        "DevEUI is the device identity; downlinks and the device sync use the REST API with "
        "the portal account."
    )

    def event_connector(self, source: DataSourceContext) -> EventConnector | None:
        return None

    def parse_webhook(
        self, source: DataSourceContext, body: Any, headers: dict[str, str]
    ) -> list[InboundMessage]:
        messages = []
        for data, tags in unwrap_envelope(body):
            message = parse_message(source, data)
            if message is None:
                continue
            if tags:
                message.provider_metadata["cra_tags"] = tags
            messages.append(message)
        return messages

    def command_connector(self, source: DataSourceContext) -> CraCommands:
        return CraCommands(source)

    def management_connector(self, source: DataSourceContext) -> CraManagement:
        return CraManagement(source)


__all__ = [
    "CraClient",
    "CraCommands",
    "CraIotAdapter",
    "CraManagement",
    "battery_percent",
    "devices_from_listing",
    "parse_message",
    "unwrap_envelope",
]
