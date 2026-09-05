"""Netmore LoRaWAN (decision D57), from the Netmore documentation at
docs.connect.netmoregroup.com (export format, HTTP push, MQTT, downlink) and the Netmore Connect
OpenAPI document at api.connect.netmoregroup.com/docs/swagger.json.

Events: the export format is a JSON array with one element per message: `devEui`, `sensorType`,
`messageType`, `timestamp`, `payload` (hex), `fPort` (string), `fCntUp`, `freq`, `dr`,
`spreadingFactor`, `rssi`, `snr`, `batteryLevel`, `ack`, `latitude`, `longitude`, `tags` and,
in the "Default (All)" and "Connect (All)" variants, `gateways` with `gwEui`, `rssi`, `snr`.
Two delivery paths: HTTP push to the source's webhook URL with the bearer token as a static
header (Export Configs), or the Netmore MQTT broker (`mqtts://mq.netmoregroup.com:8883`,
portal login, topics `sensor/<service_provider>/<customer>/payload` and
`.../downlink-response`).

Downlinks depend on the platform (decision D58, `platform` setting):

- `lorawan_portal` (portal.blink.services): the Blink Portal API at
  `https://api.blink.services/rest`,
  `POST /core/login/{username}` with the password gives a bearer token, then
  `POST /net/sensors/{devEui}/downlink?fPort=&payloadHex=&confirmed=&validity=&requestId=`;
  `GET /net/sensors/{devEui}/downlink` lists the queue with `deliveryStatus`, `POST
  .../downlink/clear` empties it.
- `connect` (Netmore Connect): `POST {api_url}/devices/LoRaWAN/{devEui}/LoRaWAN/downlink`
with `payloadHex`, `fPort`, `confirmed` and `validity` and the `api-key` header; the answer is the
  numeric message id; `POST .../clearDownlink`.

On the MQTT path a `downlink-response` message reports `QUEUED`, `DOWNLINK_SENT` or
`ERROR_SENDING` for a `requestId`, which the portal connector sets to the command id.

Config: `platform` (`lorawan_portal`, the default, or `connect`), `api_url` (default per
platform), `web_url`, `mqtt_host` (empty for HTTP push only), `mqtt_port` (8883), `mqtt_tls`
(true), `topics` (list, default `sensor/+/+/payload` and `sensor/+/+/downlink-response`),
`validity_seconds` (default 3600). Credentials: `username` and `password` (portal login, also
the MQTT login) for `lorawan_portal`, `api_key` for `connect`.

Verified against the published documentation only; recorded messages from a Netmore account
replace the fixtures.
"""

import json
from datetime import datetime
from typing import Any, ClassVar

import httpx

from shared.connectivity.base import (
    AdapterCapabilities,
    DataSourceContext,
    Emit,
    EventConnector,
    GatewayReceptionData,
    InboundMessage,
)
from shared.connectivity.transports.mqtt import MqttSettings, subscribe_forever
from shared.enums import AcquisitionChannel, ErrorCode, IngestionMethod
from shared.logger import get_logger
from shared.timeutil import require_aware
from shared.trace import ApplicationError

log = get_logger("adapter.netmore")

DEFAULT_API_URL = "https://api.connect.netmoregroup.com/api/v1"
PORTAL_API_URL = "https://api.blink.services/rest"
PLATFORMS = ("lorawan_portal", "connect")
DEFAULT_TOPICS = ["sensor/+/+/payload", "sensor/+/+/downlink-response"]
DELIVERY_STATUS = {
    "QUEUED": "downlink_queued",
    "DOWNLINK_SENT": "downlink_transmitted",
    "ERROR_SENDING": "log",
}


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return require_aware(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except ValueError as exc:
        raise ApplicationError(
            code=ErrorCode.TIMESTAMP_INVALID,
            message=f"Netmore timestamp {value!r} is not ISO 8601: {exc}",
            component="adapter.netmore",
        ) from exc


def parse_message(source: DataSourceContext, data: Any, method: IngestionMethod) -> InboundMessage:
    """One export element, or one downlink response."""
    if not isinstance(data, dict):
        raise ApplicationError(
            code=ErrorCode.PAYLOAD_DECODE_FAILED,
            message="Netmore message must be a JSON object",
            component="adapter.netmore",
        )
    dev_eui = str(data.get("devEui") or "").upper() or None
    if "deliveryStatus" in data:
        status = str(data.get("deliveryStatus") or "")
        return InboundMessage(
            external_id=dev_eui,
            event_type=DELIVERY_STATUS.get(status, "log"),
            payload=data,
            acquisition_channel=AcquisitionChannel.LORAWAN,
            ingestion_method=method,
            provider_metadata={
                "netmore_event": "downlink-response",
                "delivery_status": status,
                "queue_ref": data.get("requestId"),
                "level": "ERROR" if status == "ERROR_SENDING" else "INFO",
                "code": data.get("errorCode"),
                "description": data.get("errorDescription"),
            },
            identity_type="dev_eui",
        )
    if "data" in data and "payload" not in data:
        raise ApplicationError(
            code=ErrorCode.PAYLOAD_DECODE_FAILED,
            message=(
                "Netmore export is a decoded (Decoding v2) format; select a raw format "
                "(Default or Connect) on the export config"
            ),
            component="adapter.netmore",
            user_actionable=True,
        )
    receptions = [
        GatewayReceptionData(
            gateway_id=str(gw.get("gwEui") or gw.get("mac") or gw.get("gatewayIdentifier")).lower(),
            rssi=_number(gw.get("rssi")),
            snr=_number(gw.get("snr")),
            attributes={
                k: v for k, v in gw.items() if k in ("gatewayIdentifier", "mac", "antenna")
            },
        )
        for gw in data.get("gateways") or []
        if isinstance(gw, dict)
        and (gw.get("gwEui") or gw.get("mac") or gw.get("gatewayIdentifier"))
    ]
    if not receptions and data.get("gatewayIdentifier"):
        receptions.append(
            GatewayReceptionData(
                gateway_id=str(data["gatewayIdentifier"]).lower(),
                rssi=_number(data.get("rssi")),
                snr=_number(data.get("snr")),
                attributes={"gatewayIdentifier": data["gatewayIdentifier"]},
            )
        )
    payload_hex = data.get("payload")
    metadata: dict[str, Any] = {
        "netmore_event": data.get("messageType") or "payload",
        "f_port": _int(data.get("fPort")),
        "f_cnt": _int(data.get("fCntUp")),
        "spreading_factor": _int(data.get("spreadingFactor")),
        "data_rate": data.get("dr"),
        "frequency_hz": _int(data.get("freq")),
        "best_rssi": _number(data.get("rssi")),
        "best_snr": _number(data.get("snr")),
        "confirmed": data.get("ack"),
        "battery_level": data.get("batteryLevel"),
        "time_on_air": data.get("toa"),
        "gateway_count": len(receptions) or None,
        "sensor_type": data.get("sensorType"),
        "latitude": data.get("latitude"),
        "longitude": data.get("longitude"),
    }
    if isinstance(payload_hex, str) and payload_hex:
        metadata["frame_hex"] = payload_hex
    identity = {
        k: v
        for k, v in {
            "device_id": data.get("device-id") or data.get("deviceId"),
            "device_group_id": data.get("device-group-id") or data.get("deviceGroupId"),
            "sensor_type": data.get("sensorType"),
            "tags": data.get("tags"),
        }.items()
        if v not in (None, "", {})
    }
    return InboundMessage(
        external_id=dev_eui,
        event_type="uplink",
        payload=data,
        acquisition_channel=AcquisitionChannel.LORAWAN,
        ingestion_method=method,
        provider_metadata={k: v for k, v in metadata.items() if v is not None},
        network_received_at=parse_time(data.get("timestamp")),
        identity_type="dev_eui",
        identity_attributes=identity,
        gateway_receptions=receptions,
    )


def parse_body(
    source: DataSourceContext, body: Any, method: IngestionMethod
) -> list[InboundMessage]:
    items = body if isinstance(body, list) else [body]
    return [parse_message(source, item, method) for item in items]


class NetmoreMqttConnector:
    """The Netmore broker: portal login, TLS, the payload and downlink-response topics."""

    def __init__(self, source: DataSourceContext) -> None:
        self.source = source

    async def run(self, emit: Emit) -> None:
        config, credentials = self.source.config, self.source.credentials
        user = credentials.get("username") or credentials.get("mqtt_username") or "protect"
        settings = MqttSettings(
            host=str(config["mqtt_host"]),
            port=int(config.get("mqtt_port", 8883)),
            username=credentials.get("username") or credentials.get("mqtt_username"),
            password=credentials.get("password") or credentials.get("mqtt_password"),
            tls=bool(config.get("mqtt_tls", True)),
            client_id=f"{user}-protect-{self.source.id.hex[:8]}",
            source_id=self.source.id,
        )
        topics = [str(t) for t in (config.get("topics") or DEFAULT_TOPICS)]

        async def callback(topic: str, payload: bytes) -> None:
            try:
                body = json.loads(payload.decode("utf-8"))
                messages = parse_body(self.source, body, IngestionMethod.MQTT)
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                log.warning("netmore message is not JSON", topic=topic, error=str(exc))
                return
            except ApplicationError as error:
                log.warning("netmore message dropped", topic=topic, error=str(error))
                return
            for message in messages:
                message.provider_metadata["topic"] = topic
                await emit(message)

        await subscribe_forever(settings, topics, callback)


class NetmoreConnectCommands:
    """Command connector for Netmore Connect: the REST downlink endpoint with an API key."""

    def __init__(self, source: DataSourceContext) -> None:
        self.source = source
        self.base = str(source.config.get("api_url") or DEFAULT_API_URL).rstrip("/")
        self.api_key = str(source.credentials.get("api_key") or "")
        self.validity = int(source.config.get("validity_seconds") or 3600)

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base,
            headers={"api-key": self.api_key, "Accept": "application/json"},
            timeout=15,
        )

    def _check(self, response: httpx.Response, what: str) -> None:
        if response.status_code in (401, 403):
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_AUTH_FAILED,
                message=f"Netmore refused the API key ({response.status_code})",
                component="adapter.netmore",
                user_actionable=True,
            )
        if response.status_code == 404:
            raise ApplicationError(
                code=ErrorCode.DEVICE_NOT_FOUND,
                message=f"Netmore does not know the device for {what}",
                component="adapter.netmore",
                user_actionable=True,
            )
        if response.status_code >= 500:
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
                message=f"Netmore answered {response.status_code}: {response.text[:200]}",
                component="adapter.netmore",
                retryable=True,
            )
        if response.status_code >= 400:
            raise ApplicationError(
                code=ErrorCode.COMMAND_REJECTED,
                message=f"Netmore rejected {what} ({response.status_code}): {response.text[:200]}",
                component="adapter.netmore",
                user_actionable=True,
            )

    async def submit(
        self, external_id: str, payload: bytes, options: dict[str, Any]
    ) -> dict[str, Any]:
        if not self.api_key:
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_AUTH_FAILED,
                message="the Netmore source has no api_key credential",
                component="adapter.netmore",
                user_actionable=True,
            )
        dev_eui = external_id.lower()
        params = {
            "payloadHex": payload.hex(),
            "fPort": str(int(options["f_port"])),
            "confirmed": "true" if options.get("confirmed") else "false",
            "validity": str(int(options.get("validity_seconds") or self.validity)),
        }
        async with self._client() as client:
            response = await client.post(
                f"/devices/LoRaWAN/{dev_eui}/LoRaWAN/downlink", params=params
            )
        self._check(response, "the downlink")
        try:
            parsed: Any = response.json()
        except ValueError:
            parsed = response.text[:200]
        reference = parsed if isinstance(parsed, int | float | str) else None
        return {
            "provider_ref": str(int(reference))
            if isinstance(reference, int | float)
            else (str(reference) if reference else None),
            "statuses": ["accepted_by_network", "queued"],
            "response": parsed,
        }

    async def flush(self, external_id: str) -> None:
        async with self._client() as client:
            response = await client.post(
                f"/devices/LoRaWAN/{external_id.lower()}/LoRaWAN/clearDownlink"
            )
        self._check(response, "clearing the queue")


class NetmorePortalCommands:
    """Command connector for the LoRaWAN Portal (portal.blink.services): login for a bearer
    token, then the sensor downlink queue."""

    def __init__(self, source: DataSourceContext) -> None:
        self.source = source
        self.base = str(source.config.get("api_url") or PORTAL_API_URL).rstrip("/")
        self.username = str(source.credentials.get("username") or "")
        self.password = str(source.credentials.get("password") or "")
        self.validity = int(source.config.get("validity_seconds") or 3600)
        self._token: str | None = None

    async def _login(self, client: httpx.AsyncClient) -> str:
        if not self.username or not self.password:
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_AUTH_FAILED,
                message="the Netmore source needs username and password credentials",
                component="adapter.netmore",
                user_actionable=True,
            )
        response = await client.post(
            f"/core/login/{self.username}", json={"password": self.password}
        )
        body: dict[str, Any] = response.json() if response.content else {}
        token = body.get("token") if isinstance(body, dict) else None
        if response.status_code >= 400 or not token:
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_AUTH_FAILED,
                message=(
                    f"Netmore portal login failed ({response.status_code}): "
                    f"{body.get('message') if isinstance(body, dict) else response.text[:120]}"
                ),
                component="adapter.netmore",
                user_actionable=True,
            )
        self._token = str(token)
        return self._token

    async def _request(
        self, method: str, path: str, *, params: dict[str, str] | None = None
    ) -> httpx.Response:
        """One call with the cached token; a 401 logs in again once."""
        async with httpx.AsyncClient(base_url=self.base, timeout=15) as client:
            token = self._token or await self._login(client)
            response = await client.request(
                method, path, params=params, headers={"authorization": f"Bearer {token}"}
            )
            if response.status_code == 401:
                token = await self._login(client)
                response = await client.request(
                    method, path, params=params, headers={"authorization": f"Bearer {token}"}
                )
            return response

    def _check(self, response: httpx.Response, what: str) -> None:
        if response.status_code in (401, 403):
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_AUTH_FAILED,
                message=f"Netmore portal refused the login ({response.status_code})",
                component="adapter.netmore",
                user_actionable=True,
            )
        if response.status_code == 404:
            raise ApplicationError(
                code=ErrorCode.DEVICE_NOT_FOUND,
                message=f"Netmore portal does not know the sensor for {what}",
                component="adapter.netmore",
                user_actionable=True,
            )
        if response.status_code >= 500:
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
                message=f"Netmore portal answered {response.status_code}: {response.text[:200]}",
                component="adapter.netmore",
                retryable=True,
            )
        if response.status_code >= 400:
            detail = response.text[:200]
            try:
                parsed = response.json()
                if isinstance(parsed, dict) and parsed.get("message"):
                    detail = str(parsed["message"])
            except ValueError:
                pass
            raise ApplicationError(
                code=ErrorCode.COMMAND_REJECTED,
                message=f"Netmore portal rejected {what} ({response.status_code}): {detail}",
                component="adapter.netmore",
                user_actionable=True,
            )

    async def submit(
        self, external_id: str, payload: bytes, options: dict[str, Any]
    ) -> dict[str, Any]:
        dev_eui = external_id.upper()
        params = {
            "fPort": str(int(options["f_port"])),
            "payloadHex": payload.hex().upper(),
            "confirmed": "true" if options.get("confirmed") else "false",
            "validity": str(int(options.get("validity_seconds") or self.validity)),
        }
        reference = options.get("reference")
        if reference:
            params["requestId"] = str(reference)
        response = await self._request("POST", f"/net/sensors/{dev_eui}/downlink", params=params)
        self._check(response, "the downlink")
        try:
            parsed: Any = response.json() if response.content else {}
        except ValueError:
            parsed = response.text[:200]
        return {
            "provider_ref": str(reference) if reference else None,
            "statuses": ["accepted_by_network", "queued"],
            "response": parsed,
        }

    async def queue(self, external_id: str) -> list[dict[str, Any]]:
        response = await self._request(
            "GET", f"/net/sensors/{external_id.upper()}/downlink", params={"limit": "20"}
        )
        self._check(response, "the queue")
        items: Any = response.json() if response.content else []
        rows = items if isinstance(items, list) else [items]
        return [
            {
                "id": str(row.get("id")),
                "fPort": _int(row.get("requestFPort")),
                "data": None,
                "data_hex": row.get("requestPayloadHex"),
                "confirmed": None,
                "isPending": row.get("deliveryStatus") in (None, "", "QUEUED"),
                "fCntDown": row.get("requestFCnt"),
                "deliveryStatus": row.get("deliveryStatus"),
            }
            for row in rows
            if isinstance(row, dict)
        ]

    async def flush(self, external_id: str) -> None:
        response = await self._request("POST", f"/net/sensors/{external_id.upper()}/downlink/clear")
        self._check(response, "clearing the queue")


def command_connector_for_platform(
    source: DataSourceContext,
) -> "NetmorePortalCommands | NetmoreConnectCommands":
    platform = str(source.config.get("platform") or "lorawan_portal")
    if platform not in PLATFORMS:
        raise ApplicationError(
            code=ErrorCode.COMMAND_REJECTED,
            message=f"unknown Netmore platform {platform!r}; one of {', '.join(PLATFORMS)}",
            component="adapter.netmore",
            user_actionable=True,
        )
    if platform == "connect":
        return NetmoreConnectCommands(source)
    return NetmorePortalCommands(source)


class NetmoreAdapter:
    key: ClassVar[str] = "netmore"
    label: ClassVar[str] = "Netmore LoRaWAN"
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
    default_link_templates: ClassVar[dict[str, str]] = {
        "OPEN_DEVICE": "{web_url}/devices/{external_id}",
    }
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "platform": {"type": "string", "enum": list(PLATFORMS), "default": "lorawan_portal"},
            "api_url": {
                "type": "string",
                "description": "Default per platform: api.blink.services/rest or the Connect API",
            },
            "web_url": {"type": "string", "description": "Netmore Connect portal, for deep links"},
            "mqtt_host": {"type": "string", "description": "Empty for HTTP push only"},
            "mqtt_port": {"type": "integer", "default": 8883},
            "mqtt_tls": {"type": "boolean", "default": True},
            "topics": {"type": "array", "items": {"type": "string"}, "default": DEFAULT_TOPICS},
            "validity_seconds": {"type": "integer", "default": 3600},
        },
    }
    config_example: ClassVar[dict[str, Any]] = {
        "platform": "lorawan_portal",
        "web_url": "https://portal.blink.services",
        "mqtt_host": "",
        "validity_seconds": 3600,
    }
    credentials_schema: ClassVar[dict[str, str]] = {
        "username": "Portal login (lorawan_portal downlinks and the MQTT path)",
        "password": "Portal password",
        "api_key": "Netmore Connect API key (platform connect)",
    }
    setup_hint: ClassVar[str] = (
        "Create an HTTP Push export config with the webhook URL and an Authorization header "
        "holding the bearer token, using a raw export format (Default or Connect, all fields). "
        "Or set mqtt_host to mq.netmoregroup.com with the portal login. Set platform to "
        "lorawan_portal (portal.blink.services) or connect."
    )

    def event_connector(self, source: DataSourceContext) -> EventConnector | None:
        return NetmoreMqttConnector(source) if source.config.get("mqtt_host") else None

    def parse_webhook(
        self, source: DataSourceContext, body: Any, headers: dict[str, str]
    ) -> list[InboundMessage]:
        return parse_body(source, body, IngestionMethod.WEBHOOK)

    def command_connector(
        self, source: DataSourceContext
    ) -> "NetmorePortalCommands | NetmoreConnectCommands":
        return command_connector_for_platform(source)
