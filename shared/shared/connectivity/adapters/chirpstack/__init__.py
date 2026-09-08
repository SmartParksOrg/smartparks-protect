"""ChirpStack v4 adapter: the full-feature reference LoRaWAN implementation (architecture 7.2).

Events arrive over the ChirpStack MQTT integration (JSON marshaler) on
`application/{application_id}/device/{dev_eui}/event/{event}`. Management and downlinks use the
ChirpStack REST API (`chirpstack-rest-api`) with an API token (decision D50): a command becomes
a device queue item, `txack` and `ack` events carry its `queueItemId` back.

Config keys: `mqtt_host` (empty for the HTTP integration), `mqtt_port` (1883), `mqtt_tls`
(false), `api_url` (grpcs://host:443 or grpc://host:8080 for native gRPC, https://host for
grpc-web through the web UI's own path, decision D131; for
example `http://chirpstack-rest-api:8090`), `web_url` (the ChirpStack web UI, for deep links),
`tenant_id`, `topic_prefix` (empty by default; ChirpStack can prefix integration topics).
Credentials: `api_token`, optional `mqtt_username` and `mqtt_password`.
"""

import json
import re
from datetime import datetime
from typing import Any, ClassVar
from urllib.parse import urlsplit

from shared.connectivity.adapters.chirpstack.grpc_api import (
    _ChirpStackCalls,
    client_for,
    is_api_url,
)
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
            source_id=self.source.id,
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


def merge_endpoints(existing: str | None, url: str) -> tuple[str, str]:
    """ChirpStack's HTTP integration takes a comma-separated list of event endpoint URLs and
    sends every event, with one header map, to each (decision D125). Put `url` in the list:
    kept as it is when present (`already`), replaced when an entry is the same webhook with
    another token (`updated`, after a token rotation), appended otherwise (`connected`).
    Nothing else in the list is touched."""
    base = url.split("?", 1)[0]
    entries = [e.strip() for e in (existing or "").split(",") if e.strip()]
    if url in entries:
        return ",".join(entries), "already"
    merged = []
    replaced = False
    for entry in entries:
        if entry.split("?", 1)[0] == base:
            if not replaced:
                merged.append(url)
                replaced = True
            continue
        merged.append(entry)
    if replaced:
        return ",".join(merged), "updated"
    return ",".join([*merged, url]), "connected"


def endpoint_state(existing: str | None, base: str) -> str:
    """`connected` when the list holds this webhook, `other` when it holds only other URLs,
    `none` when there is no integration or no URL."""
    entries = [e.strip() for e in (existing or "").split(",") if e.strip()]
    if any(e.split("?", 1)[0] == base for e in entries):
        return "connected"
    return "other" if entries else "none"


class ChirpStackManagement:
    """Control plane through ChirpStack's gRPC API, the only API of ChirpStack v4 (its REST
    gateway is not used): `api_url` is `grpcs://host:443` or `grpc://host:8080`."""

    def __init__(self, source: DataSourceContext) -> None:
        self.base = str(source.config.get("api_url", "")).strip()
        self.token = str(source.credentials.get("api_token", "") or "")
        self.tenant_id = str(source.config.get("tenant_id") or "")
        self._grpc: _ChirpStackCalls | None = None

    @property
    def grpc(self) -> _ChirpStackCalls:
        """The client, checked on first use so a source without an API channel fails the
        call that needs it, with the reason, not the ingest of its uplinks."""
        if self._grpc is not None:
            return self._grpc
        if not self.base:
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_AUTH_FAILED,
                message="the data source needs `api_url` (https://host for grpc-web, "
                "grpcs://host:443 or grpc://host:8080 for native gRPC)",
                component="adapter.chirpstack",
                user_actionable=True,
            )
        if not is_api_url(self.base):
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_AUTH_FAILED,
                message=(
                    f"api_url {self.base!r} is not an API address: grpcs://host:443 or "
                    "grpc://host:8080 for native gRPC, https://host for grpc-web through the "
                    "address of the web UI"
                ),
                component="adapter.chirpstack",
                user_actionable=True,
            )
        if not self.token:
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_AUTH_FAILED,
                message="the data source needs the `api_token` credential (a tenant API key)",
                component="adapter.chirpstack",
                user_actionable=True,
            )
        self._grpc = client_for(self.base, self.token)
        return self._grpc

    async def list_applications(self) -> list[dict[str, Any]]:
        return await self.grpc.list_applications(self.tenant_id)

    async def list_devices(self) -> list[dict[str, Any]]:
        devices: list[dict[str, Any]] = []
        for application in await self.list_applications():
            for device in await self.grpc.list_devices(str(application["id"])):
                dev_eui = str(device.get("devEui") or "").upper()
                if not dev_eui:
                    continue
                devices.append(
                    {
                        "external_id": dev_eui,
                        "identity_type": "dev_eui",
                        "name": device.get("name") or dev_eui,
                        "attributes": {
                            k: v
                            for k, v in {
                                "application_id": application["id"],
                                "application_name": application.get("name"),
                                "device_profile_id": device.get("deviceProfileId"),
                                "device_profile_name": device.get("deviceProfileName"),
                                "last_seen_at": device.get("lastSeenAt"),
                                "description": device.get("description"),
                            }.items()
                            if v
                        },
                    }
                )
        return devices

    async def list_gateways(self) -> list[dict[str, Any]]:
        return await self.grpc.list_gateways(self.tenant_id)

    async def list_gateway_updates(self) -> list[GatewayUpdate]:
        return gateway_updates_from_listing(await self.list_gateways())

    async def test_connection(self) -> dict[str, Any]:
        applications = await self.list_applications()
        return {"ok": True, "applications": len(applications)}

    async def connect_applications(
        self, url: str, *, dry_run: bool = False
    ) -> list[dict[str, Any]]:
        """Put this source's webhook URL (with its token in the query, decision D127) on the
        HTTP integration of every application of the tenant (decision D125): created where
        there is none, the URL merged into the list where one exists, headers and the other
        URLs left alone. One entry per application with the outcome. A dry run reads every
        integration and reports what would change without writing (D129)."""
        results: list[dict[str, Any]] = []
        for application in await self.list_applications():
            application_id = str(application["id"])
            entry: dict[str, Any] = {
                "application_id": application_id,
                "name": application.get("name") or application_id,
            }
            try:
                current = await self.grpc.get_http_integration(application_id)
                if current is None:
                    if not dry_run:
                        await self.grpc.create_http_integration(application_id, url, {})
                    entry.update(outcome="connected", urls=[url], before=[])
                else:
                    before = [
                        e.strip()
                        for e in str(current.get("eventEndpointUrl") or "").split(",")
                        if e.strip()
                    ]
                    entry["before"] = before
                    entry["headers"] = sorted((current.get("headers") or {}).keys())
                    merged, outcome = merge_endpoints(current.get("eventEndpointUrl"), url)
                    if outcome != "already" and not dry_run:
                        await self.grpc.update_http_integration(
                            application_id,
                            merged,
                            dict(current.get("headers") or {}),
                            str(current.get("encoding") or "JSON"),
                        )
                    entry.update(outcome=outcome, urls=merged.split(","))
            except ApplicationError as error:
                entry.update(outcome="failed", error=str(error))
            results.append(entry)
        return results

    async def integration_status(self, base_url: str) -> list[dict[str, Any]]:
        """Per application: whether its HTTP integration posts to this webhook (`connected`),
        to other URLs only (`other`), or nowhere (`none`), for Test connection (D126)."""
        results: list[dict[str, Any]] = []
        for application in await self.list_applications():
            application_id = str(application["id"])
            current = await self.grpc.get_http_integration(application_id)
            urls = [
                e.strip()
                for e in str((current or {}).get("eventEndpointUrl") or "").split(",")
                if e.strip()
            ]
            results.append(
                {
                    "application_id": application_id,
                    "name": application.get("name") or application_id,
                    "state": endpoint_state((current or {}).get("eventEndpointUrl"), base_url),
                    "urls": [u.split("?", 1)[0] for u in urls],
                }
            )
        return results


class ChirpStackCommands(ChirpStackManagement):
    """Command connector: the device queue over gRPC."""

    async def submit(
        self, external_id: str, payload: bytes, options: dict[str, Any]
    ) -> dict[str, Any]:
        dev_eui = external_id.lower()
        item_id = await self.grpc.enqueue(
            dev_eui, payload, int(options["f_port"]), bool(options.get("confirmed", False))
        )
        return {
            "provider_ref": item_id,
            "statuses": ["accepted_by_network", "queued"],
            "queue_item_id": item_id,
        }

    async def queue(self, external_id: str) -> list[dict[str, Any]]:
        return await self.grpc.queue(external_id.lower())

    async def flush(self, external_id: str) -> None:
        await self.grpc.flush(external_id.lower())


class ChirpStackAdapter:
    key: ClassVar[str] = "chirpstack"
    label: ClassVar[str] = "ChirpStack"
    push: ClassVar[bool] = (
        True  # the HTTP integration posts to the webhook; MQTT/websocket is optional
    )
    # The token may travel in the URL (decision D127): ChirpStack sends one header map to every
    # URL of an application, so a managed integration never touches the headers.
    webhook_token_in_query: ClassVar[bool] = True
    # An encrypted copy of the webhook token is kept so Connect applications can write it (D125).
    keeps_webhook_token: ClassVar[bool] = True
    acquisition_channel: ClassVar[AcquisitionChannel] = AcquisitionChannel.LORAWAN
    config_example: ClassVar[dict[str, Any]] = {}
    # Quick setup (decision D128): the address and a tenant API key are enough; the gRPC
    # address is derived and the tenant looked up through the key on save.
    quick_setup: ClassVar[dict[str, Any]] = {
        "address_key": "web_url",
        "address_label": "ChirpStack address",
        "address_placeholder": "https://chirpstack.example.org/#/tenants/<id>/applications",
        "credential_key": "api_token",
        "credential_label": "Tenant API key",
        "channels_on": ["http", "api"],
        "derived_keys": ["api_url", "tenant_id"],
        "hint": "Copy the address from the ChirpStack browser tab while inside the tenant "
        "(it holds /tenants/<id>) and add an API key of that tenant: saving keeps the origin as "
        "the address, reads the tenant id, and reaches the API the way the web UI does "
        "(grpc-web), so any ChirpStack you can open in a browser works. The webhook token is "
        "shown next, with Connect applications. Advanced holds MQTT, the API address "
        "(grpcs://host:443 for native gRPC) and the tenant id.",
    }
    credentials_schema: ClassVar[dict[str, str]] = {
        "api_token": "ChirpStack API key (tenant or global) for the gRPC API",
        "mqtt_username": "Broker login, when the broker asks for one",
        "mqtt_password": "Broker password",
    }
    setup_hint: ClassVar[str] = (
        "With the gRPC API channel on, Connect applications puts this source's webhook on the "
        "HTTP integration of every application of the tenant. By hand: point the application's "
        "HTTP integration (JSON) at the webhook URL with an `Authorization` header holding "
        "`Bearer <token>`, or the URL with `?token=`. Switch the MQTT channel on only when "
        "the broker ChirpStack publishes to is reachable from this server. The gRPC API "
        "channel (grpcs://host:443 through a proxy, or grpc://host:8080) with a tenant API key "
        "enables downlinks and the device and gateway sync."
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
    channels: ClassVar[list[dict[str, Any]]] = [
        {
            "key": "http",
            "label": "HTTP integration",
            "direction": "in",
            "purpose": "ChirpStack posts every event to the webhook URL; enough for uplinks, "
            "joins and downlink acknowledgements",
            "config_keys": [],
            "credential_keys": [],
            "hint": "Application, Integrations, HTTP: JSON, the webhook URL, header "
            "Authorization with Bearer <token>",
        },
        {
            "key": "mqtt",
            "label": "MQTT subscription",
            "direction": "in",
            "purpose": "The ingest service subscribes to ChirpStack's broker for the same "
            "events plus gateway statistics; needs the broker reachable from this server",
            "config_keys": ["mqtt_host"],
            "optional_keys": ["mqtt_port", "mqtt_tls", "topic_prefix"],
            "credential_keys": [],
            "optional_credential_keys": ["mqtt_username", "mqtt_password"],
            "hint": "mqtt_username and mqtt_password only when the broker asks for them",
        },
        {
            "key": "api",
            "label": "gRPC API",
            "direction": "out",
            "purpose": "Downlinks, device sync, gateway sync and Test connection over "
            "ChirpStack's gRPC API",
            "config_keys": ["api_url"],
            "credential_keys": ["api_token"],
            "hint": "api_url is https://host (grpc-web, the web UI's address), or "
            "grpcs://host:443 / grpc://host:8080 for native gRPC; api_token a tenant API key",
            "capabilities": [
                "downlink",
                "device_management",
                "gateway_management",
                "gateway_status",
            ],
        },
    ]
    default_link_templates: ClassVar[dict[str, str]] = {
        ""
        "OPEN_DEVICE": "{web_url}/#/tenants/{tenant_id}/applications/{application_id}/devices/{external_id_lower}",  # noqa: E501
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
            "api_url": {
                "type": "string",
                "description": "ChirpStack's API: https://host for grpc-web through the web "
                "UI's address (works behind any proxy), grpcs://host:443 for native gRPC "
                "through a TLS proxy with grpc_pass, or grpc://host:8080 on a private network",
            },
            "web_url": {"type": "string", "description": "ChirpStack web UI, for deep links"},
            "tenant_id": {"type": "string"},
        },
    }

    async def complete_config(self, source: DataSourceContext) -> dict[str, Any]:
        """Quick setup (decision D128): the address as copied from the ChirpStack browser tab
        gives `web_url` (its origin) and, inside a tenant, `tenant_id` (`/tenants/<id>` in the
        fragment); `api_url` defaults to the origin, grpc-web through whatever serves the web
        UI (D131). A tenant id still missing is asked of the key: a global key with one tenant
        gives it, a tenant key cannot tell (ChirpStack refuses the call), several tenants need
        the choice made under Advanced."""
        config = dict(source.config)
        web = str(config.get("web_url") or "").strip()
        parts = urlsplit(web)
        if web and parts.hostname:
            found = re.search(r"/tenants/([0-9a-fA-F-]{36})", parts.fragment or parts.path)
            if found and not config.get("tenant_id"):
                config["tenant_id"] = found.group(1).lower()
            config["web_url"] = f"{parts.scheme}://{parts.netloc}"
        if "chirpstack.example.org" in str(config.get("api_url") or ""):
            config.pop("api_url")  # the old form's example, never a real address
        if config.get("web_url") and not config.get("api_url"):
            config["api_url"] = str(config["web_url"])
        token = str(source.credentials.get("api_token") or "")
        if token and config.get("api_url") and not config.get("tenant_id"):
            try:
                tenants = await client_for(str(config["api_url"]), token).list_tenants()
            except ApplicationError as error:
                if error.code != ErrorCode.CONNECTIVITY_AUTH_FAILED:
                    raise
                raise ApplicationError(
                    code=ErrorCode.CONNECTIVITY_AUTH_FAILED,
                    message="a tenant API key cannot tell its tenant: copy the address from "
                    "the browser while inside the tenant (it contains /tenants/<id>), or fill "
                    "the tenant id in under Advanced",
                    component="adapter.chirpstack",
                    user_actionable=True,
                ) from error
            if len(tenants) == 1:
                config["tenant_id"] = str(tenants[0]["id"])
            elif not tenants:
                raise ApplicationError(
                    code=ErrorCode.CONNECTIVITY_AUTH_FAILED,
                    message="the API key sees no tenant: use a tenant API key and copy the "
                    "address from the browser while inside the tenant",
                    component="adapter.chirpstack",
                    user_actionable=True,
                )
            else:
                names = ", ".join(str(t.get("name") or t.get("id")) for t in tenants[:5])
                raise ApplicationError(
                    code=ErrorCode.CONNECTIVITY_AUTH_FAILED,
                    message=f"the API key sees {len(tenants)} tenants ({names}): a global key "
                    "needs the tenant id filled in under Advanced",
                    component="adapter.chirpstack",
                    user_actionable=True,
                )
        return config

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
        message = parse_event(source, f"application/-/device/-/event/{event_name}", payload)
        message.ingestion_method = IngestionMethod.WEBHOOK  # so the HTTP channel counts it
        return [message]
