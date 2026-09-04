"""The Things Stack (architecture 7.2, decision D84).

Built from The Things Stack documentation (https://www.thethingsindustries.com/docs, fetched
2026-09-04): the webhook integration, its data formats, downlink scheduling and the gateway API.

- Webhooks: the Application Server POSTs one JSON document per message to the base URL plus a
  per-type path (uplink message, join accept, downlink ack, nack, sent, failed, queued, location
  solved, service data). Every document carries `end_device_ids` (`device_id`,
  `application_ids.application_id`, `dev_eui`, `join_eui`, `dev_addr`), `correlation_ids` and
  `received_at`, and one of `uplink_message`, `join_accept`, `downlink_queued`, `downlink_sent`,
  `downlink_ack`, `downlink_nack`, `downlink_failed`, `location_solved`, `service_data`. An
  uplink has `f_port`, `f_cnt`, `frm_payload` (base64), `decoded_payload`, `rx_metadata` (one per
  gateway: `gateway_ids.gateway_id`, `gateway_ids.eui`, `rssi`, `channel_rssi`, `snr`, `time`,
  `channel_index`, `location`), `settings.data_rate.lora.spreading_factor`, `settings.frequency`
  and `consumed_airtime`. Request authentication is HTTP basic or a header; this source takes
  its bearer token in the `Authorization` header, which the webhook's additional headers carry.
- Downlinks: `POST {api_url}/api/v3/as/applications/{application_id}/devices/{device_id}/down/push`
  with `Authorization: Bearer <api key>` (traffic writing rights) and
  `{"downlinks": [{"frm_payload": <base64>, "f_port": n, "priority": "NORMAL",
  "confirmed": bool, "correlation_ids": [...]}]}`; `.../down/replace` with an empty list flushes
  the queue. The correlation id comes back in the downlink events, which is how a command is
  followed.
- Gateways: `GET {api_url}/api/v3/gateways?field_mask=...` lists the gateways the key may see
  (`ids.gateway_id`, `ids.eui`, `name`, `antennas[].location`); the Gateway Server's
  `GET /api/v3/gs/gateways/{id}/connection/stats` gives `connected_at`,
  `last_status_received_at`, `last_uplink_received_at`, `uplink_count`, `downlink_count`.
  Devices: `GET /api/v3/applications/{application_id}/devices`.

The TTS `device_id` is not the DevEUI; the DevEUI is the identity and the device id an
identity attribute the downlink path needs, learnt from the first uplink or the device list.
Deep links target the Console (`web_url`).
"""

import base64
from datetime import datetime
from typing import Any, ClassVar

import httpx

from shared.connectivity.base import (
    AdapterCapabilities,
    DataSourceContext,
    EventConnector,
    GatewayReceptionData,
    GatewayUpdate,
    InboundMessage,
)
from shared.connectivity.transports.http import require_object
from shared.enums import AcquisitionChannel, ErrorCode, IngestionMethod
from shared.logger import get_logger
from shared.timeutil import require_aware
from shared.trace import ApplicationError

log = get_logger("adapter.tts")

DEFAULT_API_URL = "https://eu1.cloud.thethings.network"
HTTP_TIMEOUT = 20.0
CORRELATION_PREFIX = "smartparks-protect:"

MESSAGE_KEYS: dict[str, str] = {
    "uplink_message": "uplink",
    "join_accept": "join",
    "downlink_queued": "downlink_queued",
    "downlink_sent": "downlink_transmitted",
    "downlink_ack": "downlink_ack",
    "downlink_nack": "downlink_ack",
    "downlink_failed": "log",
    "location_solved": "location",
    "service_data": "service_data",
}


def _error(message: str, code: ErrorCode = ErrorCode.PAYLOAD_DECODE_FAILED) -> ApplicationError:
    return ApplicationError(
        code=code, message=message, component="adapter.tts", user_actionable=True
    )


def parse_tts_time(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    # RFC 3339 with nanoseconds: Python parses at most six fractional digits
    if "." in text:
        head, _, tail = text.partition(".")
        digits = ""
        rest = tail
        while rest and rest[0].isdigit():
            digits += rest[0]
            rest = rest[1:]
        text = f"{head}.{digits[:6]}{rest}"
    try:
        return require_aware(datetime.fromisoformat(text))
    except ValueError as exc:
        raise ApplicationError(
            code=ErrorCode.TIMESTAMP_INVALID,
            message=f"The Things Stack time {value!r} is not RFC 3339: {exc}",
            component="adapter.tts",
        ) from exc


def _section(container: Any, key: str) -> dict[str, Any]:
    value = container.get(key) if isinstance(container, dict) else None
    return dict(value) if isinstance(value, dict) else {}


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _correlation_ref(ids: Any) -> str | None:
    for item in ids or []:
        if isinstance(item, str) and item.startswith(CORRELATION_PREFIX):
            return item[len(CORRELATION_PREFIX) :]
    return None


def parse_message(source: DataSourceContext, body: Any) -> InboundMessage:
    document = require_object(body, "tts")
    key = next((k for k in MESSAGE_KEYS if k in document), None)
    if key is None:
        raise _error(f"not a The Things Stack message: expected one of {', '.join(MESSAGE_KEYS)}")
    ids = _section(document, "end_device_ids")
    dev_eui = str(ids.get("dev_eui") or "").upper() or None
    application_id = _section(ids, "application_ids").get("application_id")
    data: dict[str, Any] = _section(document, key)
    received = parse_tts_time(document.get("received_at")) or parse_tts_time(
        data.get("received_at")
    )
    metadata: dict[str, Any] = {
        "tts_message": key,
        "application_id": application_id,
        "device_id": ids.get("device_id"),
        "dev_addr": ids.get("dev_addr"),
        "correlation_ids": document.get("correlation_ids"),
    }
    receptions: list[GatewayReceptionData] = []
    if key == "uplink_message":
        frame = data.get("frm_payload")
        if isinstance(frame, str) and frame:
            try:
                metadata["frame_hex"] = base64.b64decode(frame, validate=True).hex()
            except (ValueError, TypeError) as exc:
                raise _error(f"frm_payload is not base64: {exc}") from exc
        metadata["f_port"] = int(data["f_port"]) if data.get("f_port") not in (None, "") else None
        metadata["f_cnt"] = int(data["f_cnt"]) if data.get("f_cnt") not in (None, "") else None
        settings = _section(data, "settings")
        lora = _section(_section(settings, "data_rate"), "lora")
        metadata["spreading_factor"] = lora.get("spreading_factor")
        metadata["bandwidth"] = lora.get("bandwidth")
        metadata["frequency"] = settings.get("frequency")
        metadata["consumed_airtime"] = data.get("consumed_airtime")
        best_rssi: float | None = None
        best_snr: float | None = None
        for rx in data.get("rx_metadata") or []:
            if not isinstance(rx, dict):
                continue
            gateway_ids = _section(rx, "gateway_ids")
            gateway_id = str(gateway_ids.get("gateway_id") or gateway_ids.get("eui") or "").lower()
            if not gateway_id:
                continue
            rssi, snr = _number(rx.get("rssi")), _number(rx.get("snr"))
            if rssi is not None and (best_rssi is None or rssi > best_rssi):
                best_rssi = rssi
            if snr is not None and (best_snr is None or snr > best_snr):
                best_snr = snr
            location = _section(rx, "location")
            receptions.append(
                GatewayReceptionData(
                    gateway_id=gateway_id,
                    rssi=rssi,
                    snr=snr,
                    channel=int(rx["channel_index"])
                    if rx.get("channel_index") not in (None, "")
                    else None,
                    attributes={
                        k: v
                        for k, v in {
                            "eui": gateway_ids.get("eui"),
                            "channel_rssi": rx.get("channel_rssi"),
                            "time": rx.get("time"),
                            "latitude": location.get("latitude"),
                            "longitude": location.get("longitude"),
                        }.items()
                        if v not in (None, "")
                    },
                )
            )
        metadata["best_rssi"] = best_rssi
        metadata["best_snr"] = best_snr
        metadata["gateway_count"] = len(receptions)
    elif key in ("downlink_queued", "downlink_sent", "downlink_ack", "downlink_nack"):
        metadata["f_port"] = data.get("f_port")
        metadata["f_cnt_down"] = data.get("f_cnt")
        metadata["queue_ref"] = _correlation_ref(data.get("correlation_ids")) or _correlation_ref(
            document.get("correlation_ids")
        )
        metadata["acknowledged"] = key != "downlink_nack"
    elif key == "downlink_failed":
        downlink = _section(data, "downlink")
        error = _section(data, "error")
        metadata["queue_ref"] = _correlation_ref(
            downlink.get("correlation_ids")
        ) or _correlation_ref(document.get("correlation_ids"))
        metadata["level"] = "ERROR"
        metadata["description"] = error.get("message_format") or error.get("name")
    elif key == "location_solved":
        location = _section(data, "location")
        metadata["latitude"] = location.get("latitude")
        metadata["longitude"] = location.get("longitude")
        metadata["location_source"] = location.get("source")
    return InboundMessage(
        external_id=dev_eui,
        event_type=MESSAGE_KEYS[key],
        payload=document,
        acquisition_channel=AcquisitionChannel.LORAWAN,
        ingestion_method=IngestionMethod.WEBHOOK,
        provider_metadata={k: v for k, v in metadata.items() if v is not None},
        network_received_at=received,
        identity_type="dev_eui",
        identity_attributes={
            k: v
            for k, v in {
                "application_id": application_id,
                "device_id": ids.get("device_id"),
                "join_eui": ids.get("join_eui"),
                "dev_addr": ids.get("dev_addr"),
            }.items()
            if v not in (None, "")
        },
        gateway_receptions=receptions,
    )


class TtsClient:
    def __init__(self, source: DataSourceContext) -> None:
        self.source = source
        self.base = str(source.config.get("api_url") or DEFAULT_API_URL).rstrip("/")
        self.api_key = str(source.credentials.get("api_key") or "").strip()
        self.application_id = str(source.config.get("application_id") or "").strip()
        if not self.api_key:
            raise _error(
                "the data source needs `api_key` in credentials", ErrorCode.CONNECTIVITY_AUTH_FAILED
            )

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self.base,
            timeout=HTTP_TIMEOUT,
            headers={"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"},
        )

    @staticmethod
    def _check(response: httpx.Response, what: str) -> Any:
        if response.status_code in (401, 403):
            raise _error(
                f"The Things Stack refused the API key for {what} ({response.status_code})",
                ErrorCode.CONNECTIVITY_AUTH_FAILED,
            )
        if response.status_code == 404:
            raise _error(f"The Things Stack does not know {what}", ErrorCode.DEVICE_NOT_FOUND)
        if response.status_code >= 500:
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
                message=f"The Things Stack answered {response.status_code}: {response.text[:200]}",
                component="adapter.tts",
                retryable=True,
            )
        if response.status_code >= 400:
            raise _error(
                f"The Things Stack rejected {what} ({response.status_code}): {response.text[:200]}",
                ErrorCode.COMMAND_REJECTED,
            )
        try:
            return response.json()
        except ValueError:
            return {}

    async def get(self, path: str, **params: Any) -> Any:
        async with self._client() as client:
            response = await client.get(path, params=params or None)
        return self._check(response, path)

    async def post(self, path: str, body: dict[str, Any]) -> Any:
        async with self._client() as client:
            response = await client.post(path, json=body)
        return self._check(response, path)


class TtsCommands:
    """Command connector: the application's downlink queue."""

    def __init__(self, source: DataSourceContext) -> None:
        self.source = source

    def _device_path(self, external_id: str, options: dict[str, Any]) -> tuple[str, str]:
        attributes = options.get("identity_attributes") or {}
        application_id = str(
            attributes.get("application_id") or self.source.config.get("application_id") or ""
        )
        device_id = str(attributes.get("device_id") or "")
        if not application_id or not device_id:
            raise _error(
                f"no The Things Stack device id is known for {external_id}: it arrives with the "
                "first uplink, or run the device sync",
                ErrorCode.COMMAND_REJECTED,
            )
        return application_id, device_id

    async def submit(
        self, external_id: str, payload: bytes, options: dict[str, Any]
    ) -> dict[str, Any]:
        application_id, device_id = self._device_path(external_id, options)
        reference = str(options.get("reference") or "")
        body = {
            "downlinks": [
                {
                    "frm_payload": base64.b64encode(payload).decode(),
                    "f_port": int(options["f_port"]),
                    "priority": "NORMAL",
                    "confirmed": bool(options.get("confirmed", False)),
                    "correlation_ids": [f"{CORRELATION_PREFIX}{reference}"] if reference else [],
                }
            ]
        }
        await TtsClient(self.source).post(
            f"/api/v3/as/applications/{application_id}/devices/{device_id}/down/push", body
        )
        return {
            "provider_ref": reference or None,
            "statuses": ["accepted_by_network", "queued"],
            "application_id": application_id,
            "device_id": device_id,
        }

    async def flush(self, external_id: str) -> None:
        """Replace the queue with nothing. Needs the device id, like a downlink."""
        raise _error(
            "flushing a The Things Stack queue needs the device id; use the Console",
            ErrorCode.COMMAND_REJECTED,
        )


def gateway_updates_from_listing(
    items: list[dict[str, Any]], stats: dict[str, dict[str, Any]] | None = None
) -> list[GatewayUpdate]:
    """`GET /api/v3/gateways` items with optional connection stats to registry updates."""
    updates: list[GatewayUpdate] = []
    for item in items:
        ids = _section(item, "ids")
        gateway_id = str(ids.get("gateway_id") or "").lower()
        if not gateway_id:
            continue
        antennas = item.get("antennas") if isinstance(item.get("antennas"), list) else []
        location = (
            antennas[0].get("location") if antennas and isinstance(antennas[0], dict) else None
        ) or {}
        stat = (stats or {}).get(gateway_id) or {}
        seen = parse_tts_time(stat.get("last_uplink_received_at")) or parse_tts_time(
            stat.get("last_status_received_at")
        )
        status = "unknown"
        if stat:
            status = (
                "online"
                if stat.get("connected_at") and not stat.get("disconnected_at")
                else "offline"
            )
        updates.append(
            GatewayUpdate(
                gateway_id=gateway_id,
                name=item.get("name") or None,
                status=status,
                latitude=_number(location.get("latitude")),
                longitude=_number(location.get("longitude")),
                altitude_m=_number(location.get("altitude")),
                stats={k: v for k, v in stat.items() if k in ("uplink_count", "downlink_count")},
                attributes={
                    k: v
                    for k, v in {
                        "eui": ids.get("eui"),
                        "description": item.get("description"),
                        "frequency_plan_id": item.get("frequency_plan_id"),
                    }.items()
                    if v
                },
                seen_at=seen,
            )
        )
    return updates


class TtsManagement:
    def __init__(self, source: DataSourceContext) -> None:
        self.source = source

    async def list_devices(self) -> list[dict[str, Any]]:
        client = TtsClient(self.source)
        body = await client.get(
            f"/api/v3/applications/{client.application_id}/devices",
            field_mask="name,description,ids",
        )
        devices = body.get("end_devices") if isinstance(body, dict) else None
        result = []
        for device in devices or []:
            ids = _section(device, "ids")
            if not ids.get("dev_eui"):
                continue
            result.append(
                {
                    "external_id": str(ids["dev_eui"]).upper(),
                    "identity_type": "dev_eui",
                    "name": device.get("name") or ids.get("device_id"),
                    "attributes": {
                        "application_id": client.application_id,
                        "device_id": ids.get("device_id"),
                        "join_eui": ids.get("join_eui"),
                    },
                }
            )
        return result

    async def list_gateway_updates(self) -> list[GatewayUpdate]:
        client = TtsClient(self.source)
        body = await client.get(
            "/api/v3/gateways", field_mask="name,description,antennas,frequency_plan_id"
        )
        items = body.get("gateways") if isinstance(body, dict) else None
        stats: dict[str, dict[str, Any]] = {}
        for item in items or []:
            gateway_id = str(_section(item, "ids").get("gateway_id") or "")
            if not gateway_id:
                continue
            try:
                stat = await client.get(f"/api/v3/gs/gateways/{gateway_id}/connection/stats")
            except ApplicationError:
                # not connected, or the key lacks the right: the registry still updates
                continue
            if isinstance(stat, dict):
                stats[gateway_id.lower()] = stat
        return gateway_updates_from_listing(list(items or []), stats)

    async def test_connection(self) -> dict[str, Any]:
        client = TtsClient(self.source)
        body = await client.get(f"/api/v3/applications/{client.application_id}", field_mask="name")
        return {"ok": True, "application": body.get("name") if isinstance(body, dict) else None}


class TtsAdapter:
    key: ClassVar[str] = "tts"
    label: ClassVar[str] = "The Things Stack"
    push: ClassVar[bool] = True
    acquisition_channel: ClassVar[AcquisitionChannel] = AcquisitionChannel.LORAWAN
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
        "OPEN_DEVICE": "{web_url}/applications/{application_id}/devices/{device_id}",
        "OPEN_APPLICATION": "{web_url}/applications/{application_id}",
        "OPEN_GATEWAY": "{web_url}/gateways/{gateway_id}",
    }
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "required": ["application_id"],
        "properties": {
            "api_url": {
                "type": "string",
                "default": DEFAULT_API_URL,
                "description": "Cluster address",
            },
            "application_id": {"type": "string"},
            "web_url": {"type": "string", "description": "The Console, for deep links"},
        },
    }
    config_example: ClassVar[dict[str, Any]] = {
        "api_url": DEFAULT_API_URL,
        "application_id": "smart-parks-collars",
        "web_url": "https://eu1.cloud.thethings.network/console",
    }
    credentials_schema: ClassVar[dict[str, str]] = {
        "api_key": "Application API key with traffic writing rights (downlinks, device list); "
        "add gateway rights for the gateway sync"
    }
    setup_hint: ClassVar[str] = (
        "In the Console add a webhook (format JSON) with this source's webhook URL as base URL, "
        "an `Authorization: Bearer <token>` additional header, and every message type enabled "
        "with an empty path. The DevEUI is the device identity."
    )

    def event_connector(self, source: DataSourceContext) -> EventConnector | None:
        return None

    def parse_webhook(
        self, source: DataSourceContext, body: Any, headers: dict[str, str]
    ) -> list[InboundMessage]:
        items = body if isinstance(body, list) else [body]
        return [parse_message(source, item) for item in items]

    def command_connector(self, source: DataSourceContext) -> TtsCommands:
        return TtsCommands(source)

    def management_connector(self, source: DataSourceContext) -> TtsManagement:
        return TtsManagement(source)
