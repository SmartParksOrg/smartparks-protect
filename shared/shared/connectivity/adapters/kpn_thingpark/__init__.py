"""KPN LoRa on Actility ThingPark (architecture 7.2, decisions D53 and D95).

Events: ThingPark's HTTP application server pushes one JSON document per report to the source's
webhook URL: `DevEUI_uplink` (uplink), `DevEUI_downlink_Sent` (downlink status),
`DevEUI_location` (network geolocation) and `DevEUI_notification` (a join when its `Type`
is join). Each reception by an LRR
(gateway) is listed under `Lrrs`. ThingPark authenticates every push itself: the URL query
carries `LrnDevEui`, `LrnFPort`, `LrnInfos`, `AS_ID`, `Time` and a `Token`, the SHA-256 of body
elements that depend on the report type, the query parameters in that order and the tunnel
interface authentication key (the AS key). With the `as_key` credential stored the adapter
verifies that token, so the push needs no custom header; the source's bearer token stays
accepted as the alternative.

Downlinks go to the ThingPark downlink API: `POST {downlink_url}` with `DevEUI`, `FPort`,
`Payload` (hex), optional `Confirmed` and `FlushDownlinkQueue`, then `AS_ID`, `Time`, a
`CorrelationID` (64 bits of hex derived from the command id) and a `Token` over the query and
the same AS key. The `DevEUI_downlink_Sent` report echoes the CorrelationID, which is how a
command becomes `transmitted`. One key, both directions; ThingPark has no other scheme, so the
adapter offers none. Capabilities differ per subscription (architecture 8.2): a public KPN
account exposes no gateway management and no statistics.

Config keys: `as_id` (the AS ID entered in ThingPark's security settings), `downlink_url`
(KPN's endpoint by default), `web_url` (the portal, for deep links), `flush_downlinks`
(default false). Credential: `as_key`, the tunnel interface authentication key.

Built from the ThingPark tunnel interface documentation and Actility's published examples; the
live run against a KPN account adds recorded payloads to the fixtures.
"""

import hashlib
import hmac
import json
import uuid
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

# Body elements of the push Token per report, in the order the tunnel interface concatenates
# them (docs.thingpark.com, HTTP connector, "Token"): a missing FPort counts as 0, a missing
# payload_hex as empty.
REPORT_BODY_ELEMENTS: dict[str, tuple[str, ...]] = {
    "DevEUI_uplink": ("CustomerID", "DevEUI", "FPort", "FCntUp", "payload_hex"),
    "DevEUI_downlink_Sent": ("CustomerID", "DevEUI", "FPort", "FCntDn"),
    "DevEUI_location": ("CustomerID", "DevEUI"),
    "DevEUI_notification": ("CustomerID", "DevEUI"),
}
# The query parameters of a push, in the order ThingPark hashes them (Token excluded).
PUSH_QUERY_ORDER: tuple[str, ...] = ("LrnDevEui", "LrnFPort", "LrnInfos", "AS_ID", "Time")
KPN_DOWNLINK_URL = "https://api.kpn-lora.com/thingpark/lrc/rest/downlink"
# `DeliveryStatus` of a downlink sent report: 1 sent by an LRR, 0 not sent. The causes per
# transmission slot (docs.thingpark.com, Wireless Logger, downlink unicast packets).
DELIVERY_FAILED_CAUSES: dict[str, str] = {
    "A0": "radio stopped",
    "A1": "downlink radio stopped",
    "A3": "radio busy",
    "A4": "listen before talk",
    "A5": "radio board error",
    "A6": "packet forwarder failure",
    "B0": "too late for RX1/RX2",
    "C0": "LRC selected RX2",
    "D0": "duty cycle constraint detected by LRR",
    "DA": "duty cycle constraint detected by LRC",
    "DB": "max dwell time constraint",
    "DE": "duty cycle not allowed by peering operator",
    "DF": "wrong NetID",
    "E1": "queue full",
    "E2": "invalid FCntDn",
    "E3": "validity time expired",
    "E4": "queue reset following rejoin",
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


def report_kind(document: dict[str, Any]) -> str | None:
    return next((k for k in EVENT_TYPES if k in document), None)


def push_token(document: dict[str, Any], query: dict[str, str], as_key: str) -> str | None:
    """The Token ThingPark puts in the URL of a push, recomputed: SHA-256 of the report's body
    elements, the query parameters in their order (without Token) and the AS key. None when
    the document is not a known report. Values are used as they came: ThingPark hashes the
    unencoded strings, so the caller must not turn the `+` of the Time offset into a space."""
    kind = report_kind(document)
    if kind is None or not isinstance(document.get(kind), dict):
        return None
    data = document[kind]
    body_elements = ""
    for field in REPORT_BODY_ELEMENTS[kind]:
        value = data.get(field)
        if value is None or value == "":
            value = "0" if field == "FPort" else ""
        body_elements += str(value)
    query_elements = "&".join(f"{k}={query[k]}" for k in PUSH_QUERY_ORDER if k in query)
    return hashlib.sha256((body_elements + query_elements + as_key).encode()).hexdigest()


def verify_push(documents: list[Any], query: dict[str, str], as_key: str) -> bool:
    """True when every document of the push carries the Token ThingPark computed with our key."""
    token = str(query.get("Token") or "").lower()
    if not as_key or not token or not documents:
        return False
    for document in documents:
        if not isinstance(document, dict):
            return False
        expected = push_token(document, query, as_key)
        if expected is None or not hmac.compare_digest(expected, token):
            kind = report_kind(document) or "unknown"
            data = document.get(kind) if isinstance(document.get(kind), dict) else {}
            log.warning(
                "ThingPark push token did not verify",
                report=kind,
                dev_eui=str((data or {}).get("DevEUI") or query.get("LrnDevEui") or ""),
                as_id=query.get("AS_ID"),
            )
            return False
    return True


def parse_event(source: DataSourceContext, body: Any) -> InboundMessage:
    document = require_object(body, "kpn_thingpark")
    kind = report_kind(document)
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
    # ThingPark gives the coordinates of the best receiving LRR at the top level (LrrLAT and
    # LrrLON next to Lrrid); the gateway registry reads them from the reception's `location`.
    best_lrr = str(data.get("Lrrid") or "").lower()
    latitude, longitude = _number(data.get("LrrLAT")), _number(data.get("LrrLON"))
    if best_lrr and latitude is not None and longitude is not None:
        for reception in receptions:
            if reception.gateway_id == best_lrr:
                reception.attributes["location"] = {"latitude": latitude, "longitude": longitude}
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
    frequency = _number(data.get("Frequency"))  # MHz
    if frequency:
        metadata["frequency_hz"] = round(frequency * 1_000_000)
    event_type = EVENT_TYPES[kind]
    if kind == "DevEUI_notification":
        # ThingPark's notification report carries `Type`; "join" is the device joining the
        # network (seen live on KPN, 2026-09-06), other types stay platform log lines.
        notification = str(data.get("Type") or "").lower()
        metadata["notification_type"] = notification or None
        if notification == "join":
            event_type = "join"
    if kind == "DevEUI_downlink_Sent":
        status = data.get("DeliveryStatus")
        metadata["delivery_status"] = int(status) if status not in (None, "") else None
        causes = []
        for slot, cause in (
            ("RX1", data.get("DeliveryFailedCause1")),
            ("RX2", data.get("DeliveryFailedCause2")),
            ("ping slot", data.get("DeliveryFailedCause3")),
        ):
            code = str(cause or "").upper()
            if code and code != "00":
                causes.append(f"{slot} {code}: {DELIVERY_FAILED_CAUSES.get(code, 'unknown cause')}")
        if causes:
            metadata["delivery_causes"] = causes
        # The CorrelationID we sent with the downlink comes back here; upper case like ours.
        reference = data.get("CorrelationID") or data.get("FlowId")
        metadata["queue_ref"] = str(reference).upper() if reference else None
        if metadata["delivery_status"] == 0:
            # Not sent over the air: the command path reads a platform error (level, description).
            event_type = "log"
            metadata["level"] = "ERROR"
            metadata["description"] = "downlink not sent: " + (
                "; ".join(causes) or "no cause given"
            )
    return InboundMessage(
        external_id=dev_eui,
        event_type=event_type,
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
                # The name ThingPark knows the device by, for onboarding from Needs attention.
                "name": (data.get("CustomerData") or {}).get("name")
                if isinstance(data.get("CustomerData"), dict)
                else None,
            }.items()
            if v not in (None, "")
        },
        gateway_receptions=receptions,
    )


def downlink_token(query: dict[str, str], as_key: str) -> str:
    """ThingPark `Token`: SHA-256 over the query string (in this order) followed by the AS key."""
    ordered = "&".join(f"{k}={v}" for k, v in query.items())
    return hashlib.sha256((ordered + as_key).encode()).hexdigest()


def correlation_id(reference: str) -> str:
    """ThingPark's `CorrelationID` is a 64 bits hexadecimal value: the first 64 bits of the
    command id (a random UUID), or of a hash when the reference is not a UUID."""
    try:
        return uuid.UUID(reference).hex[:16].upper()
    except ValueError:
        return hashlib.sha256(reference.encode()).hexdigest()[:16].upper()


class ThingParkCommands:
    """Command connector: the ThingPark downlink API."""

    def __init__(self, source: DataSourceContext, default_url: str | None = None) -> None:
        self.source = source
        self.url = str(source.config.get("downlink_url") or default_url or "").strip()
        self.as_id = str(source.config.get("as_id") or "").strip()
        self.as_key = str(source.credentials.get("as_key") or "").strip()

    def _require(self) -> None:
        missing = [
            name
            for name, value in (
                ("downlink_url", self.url),
                ("as_id", self.as_id),
                ("as_key credential", self.as_key),
            )
            if not value
        ]
        if missing:
            raise ApplicationError(
                code=ErrorCode.COMMAND_REJECTED,
                message=f"the data source has no {' and no '.join(missing)}",
                component="adapter.kpn_thingpark",
                user_actionable=True,
            )

    async def submit(
        self, external_id: str, payload: bytes, options: dict[str, Any]
    ) -> dict[str, Any]:
        self._require()
        reference = str(options.get("reference") or "")
        correlation = correlation_id(reference) if reference else None
        # The order is the one ThingPark hashes: mandatory fields, options, AS_ID and Time,
        # CorrelationID, then the Token (Actility's send_downlink_with_token example).
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
        query["AS_ID"] = self.as_id
        query["Time"] = utc_now().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "+00:00"
        if correlation:
            query["CorrelationID"] = correlation
        query["Token"] = downlink_token(query, self.as_key)
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(self.url, params=query)
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
        parsed: Any
        try:
            parsed = response.json()
        except ValueError:
            parsed = response.text[:500]
        return {
            "provider_ref": correlation,
            "statuses": ["accepted_by_network"],
            "response": parsed,
        }


def thingpark_channels(downlink_url_required: bool) -> list[dict[str, Any]]:
    """The two channels of a ThingPark source. One AS key serves both: it is asked for once,
    under the channel that receives, and the downlink channel says it uses the same key."""
    return [
        {
            "key": "http",
            "label": "Application server (HTTP)",
            "direction": "in",
            "purpose": "ThingPark posts uplinks and downlink reports to the webhook URL",
            "config_keys": [],
            "credential_keys": ["as_key"],
            "hint": (
                "The tunnel interface authentication key from the application server's "
                "uplink/downlink security in ThingPark; it verifies every push"
            ),
        },
        {
            "key": "api",
            "label": "Downlink API",
            "direction": "out",
            "purpose": "Downlinks through the LRC downlink endpoint, signed with the same AS key",
            "config_keys": ["as_id", "downlink_url"] if downlink_url_required else ["as_id"],
            "optional_keys": ["flush_downlinks"]
            if downlink_url_required
            else ["downlink_url", "flush_downlinks"],
            "credential_keys": [],
            "capabilities": ["downlink"],
            "hint": "as_id is the AS ID shown under the application server's security status",
        },
    ]


def thingpark_config_schema(default_downlink_url: str | None) -> dict[str, Any]:
    downlink_url: dict[str, Any] = {
        "type": "string",
        "description": "ThingPark LRC downlink endpoint",
    }
    if default_downlink_url:
        downlink_url["default"] = default_downlink_url
    return {
        "type": "object",
        "properties": {
            "as_id": {
                "type": "string",
                "description": "Application server id, as shown under uplink/downlink security "
                "of the application server in ThingPark",
            },
            "downlink_url": downlink_url,
            "web_url": {"type": "string", "description": "ThingPark portal, for deep links"},
            "flush_downlinks": {
                "type": "boolean",
                "default": False,
                "description": "Replace the device's downlink queue with every command",
            },
        },
    }


class KpnThingParkAdapter:
    key: ClassVar[str] = "kpn_thingpark"
    label: ClassVar[str] = "KPN LoRa (ThingPark)"
    push: ClassVar[bool] = True
    acquisition_channel: ClassVar[AcquisitionChannel] = AcquisitionChannel.LORAWAN
    default_capabilities: ClassVar[AdapterCapabilities] = AdapterCapabilities(
        uplink=True,
        downlink=True,
        join_events=True,
        downlink_status=True,
        mac_events=False,
        device_management=False,
        gateway_metadata=True,
        gateway_management=False,
        gateway_status=False,
        statistics=False,
    )
    channels: ClassVar[list[dict[str, Any]]] = thingpark_channels(downlink_url_required=False)
    default_link_templates: ClassVar[dict[str, str]] = {
        "OPEN_DEVICE": "{web_url}/devices/{external_id}",
    }
    config_schema: ClassVar[dict[str, Any]] = thingpark_config_schema(KPN_DOWNLINK_URL)
    config_example: ClassVar[dict[str, Any]] = {"web_url": "https://www.kpn-lora.com/portal/web/"}
    credentials_schema: ClassVar[dict[str, str]] = {
        "as_key": "Tunnel interface authentication key of the application server (32 hex "
        "characters): verifies every push and signs every downlink",
    }
    setup_hint: ClassVar[str] = (
        "In the KPN ThingPark Device Manager add the webhook URL as a destination of the "
        "collars' HTTP application server (routing strategy Blast when it has other "
        "destinations), read the AS ID under its uplink/downlink security and store the key "
        "of that security here as as_key. Where the portal offers custom headers, "
        "Authorization: Bearer <webhook token> works as well."
    )
    default_downlink_url: ClassVar[str | None] = KPN_DOWNLINK_URL

    def event_connector(self, source: DataSourceContext) -> EventConnector | None:
        return None

    def parse_webhook(
        self, source: DataSourceContext, body: Any, headers: dict[str, str]
    ) -> list[InboundMessage]:
        items = body if isinstance(body, list) else [body]
        return [parse_event(source, item) for item in items]

    def verify_webhook(
        self, source: DataSourceContext, body: Any, headers: dict[str, str], query: dict[str, str]
    ) -> bool:
        """ThingPark signs its pushes: the Token in the URL is recomputed with the AS key."""
        documents = body if isinstance(body, list) else [body]
        return verify_push(documents, query, str(source.credentials.get("as_key") or ""))

    def command_connector(self, source: DataSourceContext) -> ThingParkCommands:
        return ThingParkCommands(source, default_url=self.default_downlink_url)


__all__ = [
    "KPN_DOWNLINK_URL",
    "KpnThingParkAdapter",
    "ThingParkCommands",
    "correlation_id",
    "downlink_token",
    "json",
    "log",
    "parse_event",
    "push_token",
    "thingpark_channels",
    "thingpark_config_schema",
    "verify_push",
]
