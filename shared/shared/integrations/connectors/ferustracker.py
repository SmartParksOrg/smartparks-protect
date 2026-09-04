"""FerusTracker (decision D89): the platform at ferustracker.nl that receives Smart Parks
collar data today through a Node-RED flow.

FerusTracker publishes no API documentation; the contract is the flow Tim shared on
2026-09-04 ("Ferustracker" tab): for every uplink of a known payload type the flow decodes
the frame with the collar's JavaScript decoder and posts, without authentication, to
`https://ferustracker.nl/api/smartparks`:

    {
      "devEUI": "<DevEUI>", "fPort": <port>,
      "tags": {"payloadType": "opencollar_edge_6", "subType": ""},
      "deviceName": "<DevEUI>",
      "objectJSON": "<the decoded fields as a JSON string>",
      "provider": "kpn", "site": "<site>"
    }

The decoded fields are the decoder's own names: for OpenCollar Edge, port 2 location
messages carry `latitude`, `longitude`, `altitude`, `fix_timestamp`, `SIV`, `h_acc_est`, and
port 4 status messages carry `bat` (millivolts), `temp` (degrees Celsius) and `acc_x`, `acc_y`,
`acc_z`; for OpenCollar v2, port 1 carries `latitude`, `longitude`, `alt`, `satellites`,
`hdop`, `gps_time`, and port 12 carries `battery` (millivolts) and `temperature`. Payload
types seen in the flow: `opencollar_v2`, `opencollar_edge_2`, `opencollar_edge_4`,
`opencollar_edge_6`, `dragino_lgt92_v1`, `ideetron_hp_gps_v1`, `opencollar_edge_cat_1_6`
(the last three without a decoder in the flow).

This connector renders the same document from canonical positions and measurements: the
device's identity is the DevEUI, the payload type comes from the device type (configurable),
the fields use the decoder's names for that family, and one extra top-level `time` (ISO 8601)
states the record time, which the flow left to the receiver. Events are skipped. Live
verification waits for a site value and a look at what FerusTracker shows.
"""

import json
from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx

from shared.integrations.base import (
    DeliveryItem,
    DeliveryResult,
    IntegrationContext,
    PermanentFailure,
    Skipped,
    TransientFailure,
    iso,
)

DEFAULT_URL = "https://ferustracker.nl/api/smartparks"
DEFAULT_PROVIDER = "kpn"
DEFAULT_PAYLOAD_TYPE = "opencollar_edge_6"
KNOWN_PAYLOAD_TYPES = (
    "opencollar_v2",
    "dragino_lgt92_v1",
    "opencollar_edge_2",
    "opencollar_edge_cat_1_6",
    "ideetron_hp_gps_v1",
    "opencollar_edge_4",
    "opencollar_edge_6",
)
REQUEST_TIMEOUT_SECONDS = 30
BATTERY_METRICS = ("battery_voltage",)
TEMPERATURE_METRICS = ("device_temperature", "temperature")


def payload_type_for(integration: IntegrationContext, item: DeliveryItem) -> str:
    mapping = integration.config.get("payload_types") or {}
    if isinstance(mapping, dict) and item.device_type_key and mapping.get(item.device_type_key):
        return str(mapping[item.device_type_key])
    return str(integration.config.get("default_payload_type") or DEFAULT_PAYLOAD_TYPE)


def dev_eui_for(item: DeliveryItem) -> str:
    value = item.device_identity or item.device_serial
    if not value:
        raise Skipped(f"{item.object_type} {item.object_id}: the device has no identity to send")
    return value


def _epoch(moment: datetime) -> int:
    return int(moment.timestamp())


def position_fields(payload_type: str, item: DeliveryItem) -> tuple[int, dict[str, Any]]:
    if item.location is None:
        raise Skipped(f"position {item.object_id} has no location")
    latitude, longitude = item.location
    if payload_type == "opencollar_v2":
        fields: dict[str, Any] = {
            "latitude": latitude,
            "longitude": longitude,
            "gps_time": _epoch(item.time),
        }
        if item.data.get("altitude_m") is not None:
            fields["alt"] = item.data["altitude_m"]
        if item.data.get("satellites") is not None:
            fields["satellites"] = item.data["satellites"]
        return 1, fields
    fields = {"latitude": latitude, "longitude": longitude, "fix_timestamp": _epoch(item.time)}
    if item.data.get("altitude_m") is not None:
        fields["altitude"] = item.data["altitude_m"]
    if item.data.get("satellites") is not None:
        fields["SIV"] = item.data["satellites"]
    if item.data.get("accuracy_m") is not None:
        fields["h_acc_est"] = item.data["accuracy_m"]
    return 2, fields


def measurement_fields(payload_type: str, item: DeliveryItem) -> tuple[int, dict[str, Any]]:
    metric = str(item.data.get("metric_key") or "")
    value = item.data.get("value")
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise Skipped(f"measurement {item.object_id} has no numeric value")
    v2 = payload_type == "opencollar_v2"
    if metric in BATTERY_METRICS:
        return (12 if v2 else 4), {("battery" if v2 else "bat"): round(float(value) * 1000)}
    if metric in TEMPERATURE_METRICS:
        return (12 if v2 else 4), {("temperature" if v2 else "temp"): float(value)}
    raise Skipped(f"FerusTracker's status message has no field for {metric}")


def build_document(integration: IntegrationContext, item: DeliveryItem) -> dict[str, Any]:
    payload_type = payload_type_for(integration, item)
    if item.object_type == "position":
        port, fields = position_fields(payload_type, item)
    elif item.object_type == "measurement":
        port, fields = measurement_fields(payload_type, item)
    else:
        raise Skipped("FerusTracker receives collar positions and status only")
    dev_eui = dev_eui_for(item)
    document: dict[str, Any] = {
        "devEUI": dev_eui,
        "fPort": port,
        "tags": {"payloadType": payload_type, "subType": ""},
        "deviceName": dev_eui,
        "objectJSON": json.dumps(fields, separators=(",", ":")),
        "provider": str(integration.config.get("provider") or DEFAULT_PROVIDER),
        "time": iso(item.time),
    }
    site = integration.config.get("site")
    if site not in (None, ""):
        document["site"] = str(site)
    return document


class FerusTrackerConnector:
    key: ClassVar[str] = "ferustracker"
    label: ClassVar[str] = "FerusTracker"
    description: ClassVar[str] = (
        "Collar positions and status as the decoded uplink documents FerusTracker receives "
        "from the Node-RED flow today; events are skipped"
    )
    supports: ClassVar[frozenset[str]] = frozenset({"position", "measurement"})
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "default": DEFAULT_URL},
            "site": {
                "type": "string",
                "description": "The site name FerusTracker files the data under",
            },
            "provider": {"type": "string", "default": DEFAULT_PROVIDER},
            "default_payload_type": {
                "type": "string",
                "default": DEFAULT_PAYLOAD_TYPE,
                "description": "FerusTracker's payload type for devices without a mapping; "
                f"seen in the flow: {', '.join(KNOWN_PAYLOAD_TYPES)}",
            },
            "payload_types": {
                "type": "object",
                "description": "Smart Parks device type key to FerusTracker payload type",
                "additionalProperties": {"type": "string"},
            },
        },
    }
    config_example: ClassVar[dict[str, Any]] = {
        "url": DEFAULT_URL,
        "site": "Kempen-Broek",
        "provider": DEFAULT_PROVIDER,
        "default_payload_type": DEFAULT_PAYLOAD_TYPE,
        "payload_types": {"opencollar": "opencollar_edge_6"},
    }
    credentials_schema: ClassVar[dict[str, str]] = {}
    setup_hint: ClassVar[str] = (
        "FerusTracker's endpoint takes the documents without authentication, as the Node-RED "
        "flow sends them; it recognises collars by DevEUI. Give the site name FerusTracker "
        "expects and map each device type to the payload type its decoder had in the flow."
    )

    def render(self, integration: IntegrationContext, item: DeliveryItem) -> dict[str, Any]:
        return {
            "method": "POST",
            "url": str(integration.config.get("url") or DEFAULT_URL),
            "body": build_document(integration, item),
        }

    async def _post(self, url: str, body: dict[str, Any] | None) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
                response = await (
                    client.post(url, json=body) if body is not None else client.get(url)
                )
        except httpx.HTTPError as exc:
            raise TransientFailure(f"ferustracker: {type(exc).__name__}: {exc}") from exc
        if response.status_code >= 500 or response.status_code == 429:
            raise TransientFailure(f"ferustracker answered {response.status_code}")
        if body is not None and response.status_code >= 400:
            raise PermanentFailure(
                f"ferustracker answered {response.status_code}: {response.text[:300]}"
            )
        return {"status": response.status_code, "text": response.text[:300]}

    async def deliver(
        self, integration: IntegrationContext, item: DeliveryItem, payload: dict[str, Any]
    ) -> DeliveryResult:
        response = await self._post(str(payload["url"]), dict(payload["body"]))
        return DeliveryResult(external_id=None, response=response)

    async def test(
        self, integration: IntegrationContext, location: tuple[float, float] | None
    ) -> dict[str, Any]:
        """FerusTracker has no test call and every document is data, so the test only checks
        that the endpoint answers; any HTTP status short of a server error counts."""
        answer = await self._post(str(integration.config.get("url") or DEFAULT_URL), None)
        return {"status": answer["status"], "reachable": True, "checked_at": iso(datetime.now(UTC))}
