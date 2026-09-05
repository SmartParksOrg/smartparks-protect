"""ChirpStack v4 adapter: the full-feature reference LoRaWAN implementation (architecture 7.2).

Events arrive over the ChirpStack MQTT integration (JSON marshaler) on
`application/{application_id}/device/{dev_eui}/event/{event}`. Management and downlinks use the
ChirpStack REST API (`chirpstack-rest-api`) with an API token (decision D50): a command becomes
a device queue item, `txack` and `ack` events carry its `queueItemId` back.

Config keys: `mqtt_host` (empty for the HTTP integration), `mqtt_port` (1883), `mqtt_tls`
(false), `api_url` (REST API base, for
example `http://chirpstack-rest-api:8090`), `web_url` (the ChirpStack web UI, for deep links),
`tenant_id`, `topic_prefix` (empty by default; ChirpStack can prefix integration topics).
Credentials: `api_token`, optional `mqtt_username` and `mqtt_password`.
"""

import base64
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
    GatewayUpdate,
    InboundMessage,
)
from shared.connectivity.transports.mqtt import MqttSettings, subscribe_forever
from shared.enums import AcquisitionChannel, ErrorCode, IngestionMethod
from shared.logger import get_logger
from shared.timeutil import require_aware
from shared.trace import ApplicationError

log = get_logger("adapter.chirpstack")

# ChirpStack event name to the normalized LoRaWAN event type (architecture 8.1).
EVENT_TYPES: dict[str, str] = {
    "up": "uplink",
    "join": "join",
    "ack": "downlink_ack",
    "txack": "downlink_transmitted",
    "log": "log",
    "status": "status",
    "location": "location",
    "integration": "integration",
}


def parse_chirpstack_time(value: Any) -> datetime | None:
    """ChirpStack writes RFC 3339 with nanoseconds; Python parses at most microseconds."""
    if not value:
        return None
    text = str(value)
    if "." in text:
        head, rest = text.split(".", 1)
        digits = ""
        while rest and rest[0].isdigit():
            digits += rest[0]
            rest = rest[1:]
        text = f"{head}.{digits[:6].ljust(6, '0')}{rest}"
    return require_aware(datetime.fromisoformat(text.replace("Z", "+00:00")))


def parse_event(source: DataSourceContext, topic: str, payload: bytes) -> InboundMessage:
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApplicationError(
            code=ErrorCode.PAYLOAD_DECODE_FAILED,
            message=f"ChirpStack event is not JSON: {exc}",
            component="adapter.chirpstack",
            context={"topic": topic},
        ) from exc
    if not isinstance(data, dict):
        raise ApplicationError(
            code=ErrorCode.PAYLOAD_DECODE_FAILED,
            message="ChirpStack event must be a JSON object",
            component="adapter.chirpstack",
            context={"topic": topic},
        )
    parts = topic.split("/")
    event_name = parts[-1] if len(parts) >= 2 and parts[-2] == "event" else "up"
    info = data.get("deviceInfo") or {}
    dev_eui = str(info.get("devEui") or "").upper() or None
    if dev_eui is None and len(parts) >= 4 and parts[-3] == "device":
        dev_eui = parts[-4].upper() if parts[-4] else None
    receptions = [
        GatewayReceptionData(
            gateway_id=str(rx.get("gatewayId", "")).lower(),
            rssi=rx.get("rssi"),
            snr=rx.get("snr"),
            frequency_hz=(data.get("txInfo") or {}).get("frequency"),
            channel=rx.get("channel"),
            attributes={k: v for k, v in rx.items() if k in ("uplinkId", "location", "metadata")},
        )
        for rx in data.get("rxInfo") or []
        if rx.get("gatewayId")
    ]
    best = max(receptions, key=lambda r: r.rssi if r.rssi is not None else -999, default=None)
    modulation = ((data.get("txInfo") or {}).get("modulation") or {}).get("lora") or {}
    return InboundMessage(
        external_id=dev_eui,
        event_type=EVENT_TYPES.get(event_name, event_name),
        payload=data,
        acquisition_channel=AcquisitionChannel.LORAWAN,
        ingestion_method=IngestionMethod.MQTT,
        provider_metadata={
            "chirpstack_event": event_name,
            "f_port": data.get("fPort"),
            "f_cnt": data.get("fCnt"),
            "dr": data.get("dr"),
            "confirmed": data.get("confirmed"),
            "frequency_hz": (data.get("txInfo") or {}).get("frequency"),
            "spreading_factor": modulation.get("spreadingFactor"),
            "bandwidth": modulation.get("bandwidth"),
            "gateway_count": len(receptions),
            "best_rssi": best.rssi if best else None,
            "best_snr": best.snr if best else None,
            "deduplication_id": data.get("deduplicationId"),
            "topic": topic,
        },
        network_received_at=parse_chirpstack_time(data.get("time")),
        identity_type="dev_eui",
        identity_attributes={
            k: v
            for k, v in {
                "tenant_id": info.get("tenantId"),
                "tenant_name": info.get("tenantName"),
                "application_id": info.get("applicationId"),
                "application_name": info.get("applicationName"),
                "device_profile_id": info.get("deviceProfileId"),
                "device_profile_name": info.get("deviceProfileName"),
                "device_name": info.get("deviceName"),
                "tags": info.get("tags"),
            }.items()
            if v not in (None, {}, "")
        },
        gateway_receptions=receptions,
    )


GATEWAY_STATES = {"ONLINE": "online", "OFFLINE": "offline", "NEVER_SEEN": "unknown"}


def _gateway_location(data: dict[str, Any]) -> tuple[Any, Any, Any]:
    location = data.get("location") or {}
    if not isinstance(location, dict):
        return None, None, None
    return location.get("latitude"), location.get("longitude"), location.get("altitude")


def parse_gateway_event(source: DataSourceContext, topic: str, payload: bytes) -> InboundMessage:
    """`gateway/{id}/event/stats` (counters and location every stats interval) and
    `gateway/{id}/state/conn` (ONLINE or OFFLINE) to a gateway update (architecture 20)."""
    try:
        data = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ApplicationError(
            code=ErrorCode.PAYLOAD_DECODE_FAILED,
            message=f"ChirpStack gateway event is not JSON: {exc}",
            component="adapter.chirpstack",
            context={"topic": topic},
        ) from exc
    if not isinstance(data, dict):
        raise ApplicationError(
            code=ErrorCode.PAYLOAD_DECODE_FAILED,
            message="ChirpStack gateway event must be a JSON object",
            component="adapter.chirpstack",
            context={"topic": topic},
        )
    parts = topic.split("/")
    kind = parts[-1] if len(parts) >= 2 else "stats"
    gateway_id = str(data.get("gatewayId") or (parts[-3] if len(parts) >= 3 else "")).lower()
    if not gateway_id:
        raise ApplicationError(
            code=ErrorCode.PAYLOAD_DECODE_FAILED,
            message="ChirpStack gateway event without gatewayId",
            component="adapter.chirpstack",
            context={"topic": topic},
        )
    latitude, longitude, altitude = _gateway_location(data)
    update = GatewayUpdate(
        gateway_id=gateway_id,
        latitude=latitude,
        longitude=longitude,
        altitude_m=altitude,
        seen_at=parse_chirpstack_time(data.get("time")),
    )
    if kind == "conn":
        update.status = GATEWAY_STATES.get(str(data.get("state") or "").upper(), "unknown")
    else:
        update.stats = {
            k: v
            for k, v in {
                "rx_packets": data.get("rxPacketsReceived"),
                "rx_packets_ok": data.get("rxPacketsReceivedOk"),
                "tx_packets": data.get("txPacketsReceived"),
                "tx_packets_emitted": data.get("txPacketsEmitted"),
            }.items()
            if v is not None
        }
        update.attributes = {
            k: v
            for k, v in {
                "metadata": data.get("metadata"),
                "tx_packets_per_status": data.get("txPacketsPerStatus"),
            }.items()
            if v
        }
    return InboundMessage(
        external_id=None,
        event_type=f"gateway_{kind}",
        payload=data,
        acquisition_channel=AcquisitionChannel.LORAWAN,
        ingestion_method=IngestionMethod.MQTT,
        provider_metadata={"chirpstack_event": f"gateway_{kind}", "topic": topic},
        network_received_at=update.seen_at,
        gateway=update,
    )


def gateway_updates_from_listing(items: list[dict[str, Any]]) -> list[GatewayUpdate]:
    """`GET /api/gateways` items (gatewayId, name, description, location, state, lastSeenAt)
    to registry updates, for the sync action."""
    updates = []
    for item in items:
        gateway_id = str(item.get("gatewayId") or "").lower()
        if not gateway_id:
            continue
        latitude, longitude, altitude = _gateway_location(item)
        updates.append(
            GatewayUpdate(
                gateway_id=gateway_id,
                name=item.get("name") or None,
                status=GATEWAY_STATES.get(str(item.get("state") or "").upper(), "unknown"),
                latitude=latitude,
                longitude=longitude,
                altitude_m=altitude,
                attributes={
                    k: v
                    for k, v in {
                        "description": item.get("description"),
                        "tenant_id": item.get("tenantId"),
                        "properties": item.get("properties"),
                    }.items()
                    if v
                },
                seen_at=parse_chirpstack_time(item.get("lastSeenAt")),
            )
        )
    return updates


class ChirpStackConnector:
    def __init__(self, source: DataSourceContext) -> None:
        self.source = source

    async def run(self, emit: Emit) -> None:
        config, credentials = self.source.config, self.source.credentials
        settings = MqttSettings(
            host=config["mqtt_host"],
            port=int(config.get("mqtt_port", 1883)),
            username=credentials.get("mqtt_username"),
            password=credentials.get("mqtt_password"),
            tls=bool(config.get("mqtt_tls", False)),
            client_id=f"protect-ingest-{self.source.id.hex[:8]}",
        )
        prefix = str(config.get("topic_prefix", "")).strip("/")
        head = f"{prefix}/" if prefix else ""
        topics = [
            f"{head}application/+/device/+/event/+",
            f"{head}gateway/+/event/stats",
            f"{head}gateway/+/state/conn",
        ]

        async def callback(received_topic: str, payload: bytes) -> None:
            try:
                if "/gateway/" in f"/{received_topic}":
                    message = parse_gateway_event(self.source, received_topic, payload)
                else:
                    message = parse_event(self.source, received_topic, payload)
            except ApplicationError as error:
                log.warning(
                    "chirpstack event dropped",
                    source=self.source.name,
                    topic=received_topic,
                    error=str(error),
                )
                return
            await emit(message)

        await subscribe_forever(settings, topics, callback)


class ChirpStackManagement:
    """Read-only control plane through the REST API."""

    def __init__(self, source: DataSourceContext) -> None:
        self.base = str(source.config.get("api_url", "")).rstrip("/")
        self.token = source.credentials.get("api_token", "")
        self.tenant_id = source.config.get("tenant_id")

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base,
            headers={"Grpc-Metadata-Authorization": f"Bearer {self.token}"},
            timeout=15,
        )

    async def _list(self, path: str, key: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        offset = 0
        async with self._client() as client:
            while True:
                response = await client.get(path, params={**params, "limit": 100, "offset": offset})
                if response.status_code in (401, 403):
                    raise ApplicationError(
                        code=ErrorCode.CONNECTIVITY_AUTH_FAILED,
                        message=f"ChirpStack API refused the token ({response.status_code})",
                        component="adapter.chirpstack",
                        user_actionable=True,
                    )
                response.raise_for_status()
                body = response.json()
                items.extend(body.get(key) or [])
                offset += 100
                if offset >= int(body.get("totalCount") or 0):
                    return items

    async def list_applications(self) -> list[dict[str, Any]]:
        return await self._list("/api/applications", "result", {"tenantId": self.tenant_id})

    async def list_devices(self) -> list[dict[str, Any]]:
        devices: list[dict[str, Any]] = []
        for application in await self.list_applications():
            for device in await self._list(
                "/api/devices", "result", {"applicationId": application["id"]}
            ):
                devices.append(
                    {
                        **device,
                        "applicationId": application["id"],
                        "applicationName": application.get("name"),
                    }
                )
        return devices

    async def list_gateways(self) -> list[dict[str, Any]]:
        return await self._list("/api/gateways", "result", {"tenantId": self.tenant_id})

    async def list_gateway_updates(self) -> list[GatewayUpdate]:
        return gateway_updates_from_listing(await self.list_gateways())

    async def test_connection(self) -> dict[str, Any]:
        applications = await self.list_applications()
        return {"ok": True, "applications": len(applications)}


class ChirpStackCommands(ChirpStackManagement):
    """Command connector: the device queue of the REST API."""

    async def submit(
        self, external_id: str, payload: bytes, options: dict[str, Any]
    ) -> dict[str, Any]:
        dev_eui = external_id.lower()
        body = {
            "queueItem": {
                "devEui": dev_eui,
                "confirmed": bool(options.get("confirmed", False)),
                "data": base64.b64encode(payload).decode(),
                "fPort": int(options["f_port"]),
            }
        }
        async with self._client() as client:
            response = await client.post(f"/api/devices/{dev_eui}/queue", json=body)
        if response.status_code in (401, 403):
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_AUTH_FAILED,
                message=f"ChirpStack API refused the token ({response.status_code})",
                component="adapter.chirpstack",
                user_actionable=True,
            )
        if response.status_code == 404:
            raise ApplicationError(
                code=ErrorCode.DEVICE_NOT_FOUND,
                message=f"ChirpStack does not know device {dev_eui}",
                component="adapter.chirpstack",
                user_actionable=True,
            )
        if response.status_code >= 500:
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
                message=f"ChirpStack answered {response.status_code}: {response.text[:200]}",
                component="adapter.chirpstack",
                retryable=True,
            )
        if response.status_code >= 400:
            raise ApplicationError(
                code=ErrorCode.COMMAND_REJECTED,
                message=(
                    f"ChirpStack rejected the downlink ({response.status_code}): "
                    f"{response.text[:200]}"
                ),
                component="adapter.chirpstack",
                user_actionable=True,
            )
        item_id = str(response.json().get("id") or "")
        return {
            "provider_ref": item_id,
            "statuses": ["accepted_by_network", "queued"],
            "queue_item_id": item_id,
        }

    async def queue(self, external_id: str) -> list[dict[str, Any]]:
        async with self._client() as client:
            response = await client.get(f"/api/devices/{external_id.lower()}/queue")
        response.raise_for_status()
        items: list[dict[str, Any]] = response.json().get("result") or []
        return items

    async def flush(self, external_id: str) -> None:
        async with self._client() as client:
            response = await client.delete(f"/api/devices/{external_id.lower()}/queue")
        response.raise_for_status()


class ChirpStackAdapter:
    key: ClassVar[str] = "chirpstack"
    label: ClassVar[str] = "ChirpStack"
    push: ClassVar[bool] = False
    acquisition_channel: ClassVar[AcquisitionChannel] = AcquisitionChannel.LORAWAN
    config_example: ClassVar[dict[str, Any]] = {
        "mqtt_host": "chirpstack-mosquitto",
        "mqtt_port": 1883,
        "api_url": "http://chirpstack-rest-api:8090",
        "web_url": "http://localhost:8080",
        "tenant_id": "",
    }
    credentials_schema: ClassVar[dict[str, str]] = {"api_token": "ChirpStack API key"}
    setup_hint: ClassVar[str] = (
        "Enable the MQTT integration with the JSON marshaler; the ingest service subscribes "
        "within a minute."
    )
    default_capabilities: ClassVar[AdapterCapabilities] = AdapterCapabilities(
        uplink=True,
        downlink=True,
        join_events=True,
        downlink_status=True,
        mac_events=False,
        device_management=True,
        gateway_metadata=True,
        gateway_management=True,
        gateway_status=True,
        statistics=True,
    )
    default_link_templates: ClassVar[dict[str, str]] = {
        ""
        "OPEN_DEVICE": "{web_url}/#/tenants/{tenant_id}/applications/{application_id}/devices/{external_id}",  # noqa: E501
        "OPEN_APPLICATION": "{web_url}/#/tenants/{tenant_id}/applications/{application_id}",
        "OPEN_GATEWAY": "{web_url}/#/tenants/{tenant_id}/gateways/{gateway_id}",
    }
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "mqtt_host": {
                "type": "string",
                "description": "The broker ChirpStack publishes to; leave empty to receive "
                "events through ChirpStack's HTTP integration on the webhook URL instead",
            },
            "mqtt_port": {"type": "integer", "default": 1883},
            "mqtt_tls": {"type": "boolean", "default": False},
            "topic_prefix": {"type": "string", "default": ""},
            "api_url": {"type": "string", "description": "ChirpStack REST API base URL"},
            "web_url": {"type": "string", "description": "ChirpStack web UI, for deep links"},
            "tenant_id": {"type": "string"},
        },
    }

    def event_connector(self, source: DataSourceContext) -> EventConnector | None:
        """The MQTT subscription when a broker is configured; without one the events arrive
        through the HTTP integration (`parse_webhook`) and no connector runs."""
        if not str(source.config.get("mqtt_host") or "").strip():
            return None
        return ChirpStackConnector(source)

    def command_connector(self, source: DataSourceContext) -> ChirpStackCommands:
        return ChirpStackCommands(source)

    def management_connector(self, source: DataSourceContext) -> ChirpStackManagement:
        return ChirpStackManagement(source)

    def parse_webhook(
        self, source: DataSourceContext, body: Any, headers: dict[str, str]
    ) -> list[InboundMessage]:
        """ChirpStack's HTTP integration posts the same JSON events with `?event=up`. The event
        name comes from the query string, which the caller passes as the `x-event` header."""
        event_name = headers.get("x-event") or headers.get("X-Event") or "up"
        payload = json.dumps(body).encode()
        return [parse_event(source, f"application/-/device/-/event/{event_name}", payload)]
