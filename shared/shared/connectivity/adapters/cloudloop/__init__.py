"""Cloudloop (Ground Control), the Iridium platform of RockBLOCK modems (architecture 25.9,
decision D78).

Built from the Cloudloop knowledge base (https://knowledge.cloudloop.com, fetched 2026-09-04)
and its public Postman collection (https://api.cloudloop.com/swagger/postman_collection.json):

- Every API call is `POST https://api.cloudloop.com/<Area>/<Action>` with form fields; the
  `token` field carries the account's API token (requested from help@groundcontrol.com,
  regenerated with `User/DoGenerateToken`). `Platform/Ping` validates a token.
- Inbound (mobile-originated) messages reach a customer's server through the HTTP webhook
  destination: a POST with the LingoMO JSON (format "JSON (Lingo)", the recommended one). The
  fields used here: `id`, `receivedAt` (broken-down UTC time), `identity.thingId`,
  `identity.hardware.imei`, `identity.subscriber.id`, `sbd.imei`, `sbd.momsn`, `sbd.mtmsn`,
  `sbd.cdrReference`, `sbd.sessionAt`, `sbd.status`, `sbd.location` (latitude, longitude,
  `cep`), and `message`, the payload in base64. The server must answer 200 within 5 seconds;
  Cloudloop retries with exponential backoff for about twelve hours; requests come from
  35.178.100.117 or 52.56.155.169. Cloudloop sends no authentication header, so the source's
  token travels in the URL (`?token=`), and the source may restrict the caller addresses.
  The deprecated "JSON (Core)" shape (`imei`, `momsn`, `transmit_time`, `data` in hex) is
  accepted as well.
- Outbound (mobile-terminated) SBD messages: `Data/DoSendSbdMessage` with `thing` (the
  Cloudloop thing id) and `message` (hex, at most 270 bytes). Delivery status of SBD messages
  is reported by the platform's LingoDelivery statuses (`DELIVERY_SUBMITTED`,
  `DELIVERY_ERROR`, `iridiumSbdMt` values), not available through a pull endpoint.
- Things: `Data/GetThings` lists the account's things with `id`, `supportsSbd`,
  `subscriberSbd`, `account`; a thing's name and IMEI belong to its subscriber and hardware.

An OpenCollar with a RockBLOCK sends its satellite buffer as stacked stored records
(`[port][msg_id][len][data][timestamp]`, wiki satellite page); the payload is passed to the
device driver untouched with `data_hex`. The IMEI is the device identity; the thing id arrives
as an identity attribute with the first message, or by linking the thing identity from the
management sync. Deep link path is a guess until seen live.
"""

import base64
from datetime import UTC, datetime
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
from shared.trace import ApplicationError

log = get_logger("adapter.cloudloop")

API_URL = "https://api.cloudloop.com/"
HTTP_TIMEOUT = 20.0
SBD_MAX_BYTES = 270
IDENTITY_TYPE = "imei"
THING_IDENTITY_TYPE = "cloudloop_thing"
SOURCE_ADDRESSES = ("35.178.100.117", "52.56.155.169")


def _error(message: str, code: ErrorCode = ErrorCode.PAYLOAD_DECODE_FAILED) -> ApplicationError:
    return ApplicationError(
        code=code, message=message, component="adapter.cloudloop", user_actionable=True
    )


def lingo_time(value: Any) -> datetime | None:
    """Lingo writes times as `{"year":..,"month":..,"day":..,"hour":..,"minute":..,"second":..}`
    in UTC; the Core shape uses ISO 8601 strings."""
    if isinstance(value, dict):
        try:
            return datetime(
                int(value["year"]),
                int(value["month"]),
                int(value["day"]),
                int(value.get("hour", 0)),
                int(value.get("minute", 0)),
                int(value.get("second", 0)),
                tzinfo=UTC,
            )
        except (KeyError, TypeError, ValueError):
            return None
    if isinstance(value, str) and value:
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
    return None


def _float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _section(container: dict[str, Any], key: str) -> dict[str, Any]:
    value = container.get(key)
    return dict(value) if isinstance(value, dict) else {}


def parse_lingo(body: dict[str, Any]) -> InboundMessage:
    identity = _section(body, "identity")
    sbd = _section(body, "sbd")
    hardware = _section(identity, "hardware")
    subscriber = _section(identity, "subscriber")
    imei = sbd.get("imei") or hardware.get("imei") or identity.get("identifier")
    if not imei:
        raise _error("Cloudloop message without an IMEI (sbd.imei or identity.hardware.imei)")
    raw_message = body.get("message")
    data = b""
    if isinstance(raw_message, str) and raw_message:
        try:
            data = base64.b64decode(raw_message, validate=True)
        except (ValueError, TypeError) as exc:
            raise _error(f"Cloudloop message is not base64: {exc}") from exc
    location = _section(sbd, "location")
    session_at = lingo_time(sbd.get("sessionAt"))
    received_at = lingo_time(body.get("receivedAt"))
    payload: dict[str, Any] = {"format": "lingo", "raw": body}
    if data:
        payload["data"] = raw_message
        payload["data_hex"] = data.hex()
    attributes = {
        k: v
        for k, v in {
            "thing_id": identity.get("thingId"),
            "subscriber_id": subscriber.get("id"),
            "subscriber_type": subscriber.get("type"),
            "description": subscriber.get("description"),
            "hardware_id": hardware.get("id"),
            "hardware_type": hardware.get("type"),
            "serial": hardware.get("serial"),
            "account_id": identity.get("accountId"),
        }.items()
        if v not in (None, "")
    }
    return InboundMessage(
        external_id=str(imei),
        event_type="uplink" if data else "sbd_session",
        payload=payload,
        acquisition_channel=AcquisitionChannel.IRIDIUM,
        ingestion_method=IngestionMethod.WEBHOOK,
        provider_metadata={
            "cloudloop_message_id": body.get("id"),
            "thing_id": identity.get("thingId"),
            "momsn": sbd.get("momsn"),
            "mtmsn": sbd.get("mtmsn"),
            "cdr_reference": sbd.get("cdrReference"),
            "session_status": sbd.get("status"),
            "session_at": session_at.isoformat() if session_at else None,
            "iridium_latitude": _float(location.get("latitude")),
            "iridium_longitude": _float(location.get("longitude")),
            "iridium_cep_km": _float(location.get("cep")),
            "bytes": len(data),
        },
        network_received_at=received_at,
        satellite_delivered_at=session_at or received_at,
        identity_type=IDENTITY_TYPE,
        identity_attributes=attributes,
    )


def parse_core(body: dict[str, Any]) -> InboundMessage:
    """The deprecated Core and form shapes: `imei`, `momsn`, `transmit_time`, `data` (hex),
    `iridium_latitude`, `iridium_longitude`, `iridium_cep`."""
    imei = body.get("imei")
    if not imei:
        raise _error("Cloudloop message without an imei")
    data_hex = str(body.get("data") or "")
    try:
        data = bytes.fromhex(data_hex) if data_hex else b""
    except ValueError as exc:
        raise _error(f"Cloudloop data is not hex: {exc}") from exc
    transmit = lingo_time(body.get("transmit_time") or body.get("txAt"))
    payload: dict[str, Any] = {"format": "core", "raw": body}
    if data:
        payload["data_hex"] = data.hex()
    return InboundMessage(
        external_id=str(imei),
        event_type="uplink" if data else "sbd_session",
        payload=payload,
        acquisition_channel=AcquisitionChannel.IRIDIUM,
        ingestion_method=IngestionMethod.WEBHOOK,
        provider_metadata={
            "cloudloop_message_id": body.get("id"),
            "momsn": body.get("momsn"),
            "session_at": transmit.isoformat() if transmit else None,
            "iridium_latitude": _float(body.get("iridium_latitude")),
            "iridium_longitude": _float(body.get("iridium_longitude")),
            "iridium_cep_km": _float(body.get("iridium_cep") or body.get("cep")),
            "bytes": len(data),
        },
        network_received_at=transmit,
        satellite_delivered_at=transmit,
        identity_type=IDENTITY_TYPE,
        identity_attributes={
            k: v
            for k, v in {
                "hardware_type": body.get("device_type"),
                "serial": body.get("serial"),
            }.items()
            if v not in (None, "")
        },
    )


class CloudloopClient:
    """`POST <Area>/<Action>` with form fields; the token is a field of every call."""

    def __init__(self, source: DataSourceContext) -> None:
        self.source = source
        self.base = str(source.config.get("api_url") or API_URL).rstrip("/") + "/"
        self.token = str(source.credentials.get("token") or "").strip()
        if not self.token:
            raise _error(
                "the Cloudloop source needs `token` in credentials",
                ErrorCode.CONNECTIVITY_AUTH_FAILED,
            )

    async def call(self, path: str, **fields: Any) -> Any:
        async with httpx.AsyncClient(base_url=self.base, timeout=HTTP_TIMEOUT) as client:
            response = await client.post(
                path,
                data={"token": self.token, **{k: v for k, v in fields.items() if v is not None}},
            )
        if response.status_code in (401, 403):
            raise _error(
                f"Cloudloop refused the token ({response.status_code})",
                ErrorCode.CONNECTIVITY_AUTH_FAILED,
            )
        if response.status_code >= 500:
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
                message=f"Cloudloop answered {response.status_code}: {response.text[:200]}",
                component="adapter.cloudloop",
                retryable=True,
            )
        if response.status_code >= 400:
            raise _error(
                f"Cloudloop rejected the call ({response.status_code}): {response.text[:200]}",
                ErrorCode.COMMAND_REJECTED,
            )
        try:
            body: Any = response.json()
        except ValueError:
            body = {"text": response.text[:500]}
        if isinstance(body, dict) and body.get("error"):
            raise _error(f"Cloudloop reported an error: {body.get('error')}")
        return body


class CloudloopCommands:
    """Command connector: the satellite frame `[port][msg_id][len][data]` as an SBD message."""

    def __init__(self, source: DataSourceContext) -> None:
        self.source = source

    @staticmethod
    def thing_for(external_id: str, options: dict[str, Any]) -> str:
        if options.get("identity_type") == THING_IDENTITY_TYPE:
            return external_id
        attributes = options.get("identity_attributes") or {}
        thing = attributes.get("thing_id")
        if not thing:
            raise _error(
                f"no Cloudloop thing id is known for IMEI {external_id}: it arrives with the "
                "first message, or link the thing identity from the management sync",
                ErrorCode.COMMAND_REJECTED,
            )
        return str(thing)

    async def submit(
        self, external_id: str, payload: bytes, options: dict[str, Any]
    ) -> dict[str, Any]:
        frame = bytes([int(options["f_port"])]) + payload
        if len(frame) > SBD_MAX_BYTES:
            raise _error(
                f"satellite frame of {len(frame)} bytes exceeds the SBD maximum of {SBD_MAX_BYTES}",
                ErrorCode.COMMAND_REJECTED,
            )
        thing = self.thing_for(external_id, options)
        body = await CloudloopClient(self.source).call(
            "Data/DoSendSbdMessage", thing=thing, message=frame.hex().upper()
        )
        reference = None
        if isinstance(body, dict):
            reference = (
                body.get("id") or (body.get("message") or {}).get("id")
                if isinstance(body.get("message"), dict)
                else body.get("id")
            )
        return {
            "provider_ref": str(reference) if reference else None,
            "statuses": ["accepted_by_network", "queued"],
            "thing": thing,
            "frame_hex": frame.hex(),
            "response": body,
        }


class CloudloopManagement:
    def __init__(self, source: DataSourceContext) -> None:
        self.source = source

    async def list_devices(self) -> list[dict[str, Any]]:
        body = await CloudloopClient(self.source).call("Data/GetThings")
        things = body.get("things") if isinstance(body, dict) else None
        return [
            {
                "external_id": str(thing["id"]),
                "identity_type": THING_IDENTITY_TYPE,
                "name": None,
                "attributes": {
                    k: v
                    for k, v in {
                        "thing_id": thing.get("id"),
                        "subscriber_sbd": thing.get("subscriberSbd"),
                        "supports_sbd": thing.get("supportsSbd"),
                        "account_id": thing.get("account"),
                    }.items()
                    if v not in (None, "")
                },
            }
            for thing in (things or [])
            if isinstance(thing, dict) and thing.get("id")
        ]

    async def test_connection(self) -> dict[str, Any]:
        body = await CloudloopClient(self.source).call("Platform/Ping")
        return {"ok": True, "response": body}


class CloudloopAdapter:
    key: ClassVar[str] = "cloudloop"
    label: ClassVar[str] = "Cloudloop (Iridium)"
    push: ClassVar[bool] = True
    webhook_token_in_query: ClassVar[bool] = True
    acquisition_channel: ClassVar[AcquisitionChannel] = AcquisitionChannel.IRIDIUM
    config_example: ClassVar[dict[str, Any]] = {
        "allowed_source_ips": list(SOURCE_ADDRESSES),
        "web_url": "https://data.cloudloop.com",
    }
    credentials_schema: ClassVar[dict[str, str]] = {
        "token": "Cloudloop API token (for commands and the thing list; not needed for inbound)"
    }
    setup_hint: ClassVar[str] = (
        "In Cloudloop Data, add an HTTP Webhook destination with format JSON (Lingo) and the "
        "webhook URL of this source including its token. The IMEI is the device identity."
    )
    default_capabilities: ClassVar[AdapterCapabilities] = AdapterCapabilities(
        uplink=True, downlink=True, device_management=True
    )
    default_link_templates: ClassVar[dict[str, str]] = {
        "OPEN_DEVICE": "{web_url}/things/{thing_id}",
    }
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "allowed_source_ips": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Only these caller addresses may post; empty means any",
            },
            "web_url": {"type": "string", "description": "Cloudloop Data, for deep links"},
            "api_url": {"type": "string", "description": "Override of the API base URL"},
        },
    }

    def event_connector(self, source: DataSourceContext) -> EventConnector | None:
        return None

    def command_connector(self, source: DataSourceContext) -> CloudloopCommands:
        return CloudloopCommands(source)

    def management_connector(self, source: DataSourceContext) -> CloudloopManagement:
        return CloudloopManagement(source)

    def parse_webhook(
        self, source: DataSourceContext, body: Any, headers: dict[str, str]
    ) -> list[InboundMessage]:
        data = require_object(body, self.key)
        if "identity" in data or "receivedAt" in data or "sbd" in data:
            return [parse_lingo(data)]
        if "imei" in data:
            return [parse_core(data)]
        raise _error("Cloudloop webhook body is neither a Lingo nor a Core message")
