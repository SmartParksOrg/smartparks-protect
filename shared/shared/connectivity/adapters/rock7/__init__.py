"""Rock7 RockBLOCK (Ground Control's older platform, "Rock 7 Core") for the Iridium devices
still registered there rather than in Cloudloop (architecture 25.9, decision D156).

Built from the RockBLOCK web services documentation
(https://docs.groundcontrol.com/iot/rockblock/web-services, fetched 2026-09-09):

- Inbound (mobile-originated) messages reach a customer's server through a delivery group's
  delivery address (the RockBLOCK admin, seen on 2026-09-10: a group holds RockBLOCKs, a
  delivery address is a URL and a format, no headers; the formats offered are HTTP_JSON,
  HTTP_POST, HTTP_THINGSPEAK, EMAIL_ROCKBLOCK, SBD_ROCKBLOCK, HTTP_POST_INSECURE and
  HTTP_POST_GEOJSON) as `application/x-www-form-urlencoded` (`HTTP_POST`) or JSON
  (`HTTP_JSON`) with the fields `imei`, `serial`, `momsn`, `transmit_time` (UTC as
  `YY-MM-DD HH:MM:SS`), `iridium_latitude`, `iridium_longitude`, `iridium_cep` (an accuracy
  estimate in km) and `data`, the payload hex encoded; the first live delivery (2026-09-10)
  also carried `device_type` (`ROCKBLOCK`) and `iridium_session_status`, kept as provider
  metadata, and no name: the device is named by hand. The server answers 200 within three
  seconds; failures are retried with a doubling backoff for fourteen attempts (almost six
  days). Rock7 sends no authentication, so the source's token travels in the URL (`?token=`)
  and the source may restrict the caller addresses (none are documented).
- Outbound (mobile-terminated) messages: `POST https://rockblock.rock7.com/rockblock/MT`
  with `imei`, `username`, `password` (the portal login) and `data` in hex, optionally
  `flush=yes` to clear the queue first. The body answers `OK,<mtId>` or
  `FAILED,<code>,<description>`: 10 invalid login, 11 IMEI not on the account, 12 no active
  line rental, 13 insufficient credit, 14 data is not hex, 15 message too long, 16 empty
  message, 99 server error. The message is queued and delivered at the modem's next SBD
  session; a ring alert wakes a powered modem in coverage.
- No API lists devices or credit: the management system is the web UI. The connection test
  sends an empty message to a placeholder IMEI and reads the failure code: 10 means the
  login is wrong, any other code means the login was accepted (confirmed live on 2026-09-10:
  the right login answers `FAILED,16,No Data`).

The payload is the same satellite frame the Cloudloop route carries: stacked stored records
for the device driver, untouched, as `data_hex`. The IMEI is the device identity.
"""

from datetime import UTC, datetime
from typing import Any, ClassVar

import httpx

from shared.connectivity.base import (
    AdapterCapabilities,
    DataSourceContext,
    EventConnector,
    InboundMessage,
)
from shared.connectivity.satellite import SatelliteSession, status_from_code
from shared.connectivity.transports.http import require_object
from shared.enums import AcquisitionChannel, ErrorCode, IngestionMethod
from shared.logger import get_logger
from shared.trace import ApplicationError

log = get_logger("adapter.rock7")

MT_URL = "https://rockblock.rock7.com/rockblock/MT"
HTTP_TIMEOUT = 20.0
SBD_MAX_BYTES = 270
IDENTITY_TYPE = "imei"
PROBE_IMEI = "000000000000000"
FAILURE_CODES: dict[int, str] = {
    10: "invalid login credentials",
    11: "no RockBLOCK with this IMEI on the account",
    12: "the RockBLOCK has no active line rental",
    13: "insufficient credit on the account",
    14: "the data could not be decoded as hex",
    15: "the message is too long",
    16: "the message is empty",
    99: "Rock7 reported a system error",
}


def _error(message: str, code: ErrorCode = ErrorCode.PAYLOAD_DECODE_FAILED) -> ApplicationError:
    return ApplicationError(
        code=code, message=message, component="adapter.rock7", user_actionable=True
    )


def transmit_time(value: Any) -> datetime | None:
    """`YY-MM-DD HH:MM:SS` in UTC (the documented form), or an ISO time."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    try:
        return datetime.strptime(text, "%y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        pass
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def parse_message(body: dict[str, Any]) -> InboundMessage:
    imei = str(body.get("imei") or "").strip()
    if not imei:
        raise _error("Rock7 message without an imei")
    data_hex = str(body.get("data") or "").strip()
    try:
        data = bytes.fromhex(data_hex) if data_hex else b""
    except ValueError as exc:
        raise _error(f"Rock7 data is not hex: {exc}") from exc
    transmitted = transmit_time(body.get("transmit_time"))
    payload: dict[str, Any] = {"format": "rock7", "raw": body}
    if data:
        payload["data_hex"] = data.hex()
    location = {
        k: v
        for k, v in {
            "latitude": _float(body.get("iridium_latitude")),
            "longitude": _float(body.get("iridium_longitude")),
            "cep_km": _float(body.get("iridium_cep")),
        }.items()
        if v is not None
    }
    return InboundMessage(
        external_id=imei,
        event_type="uplink" if data else "sbd_session",
        payload=payload,
        acquisition_channel=AcquisitionChannel.IRIDIUM,
        ingestion_method=IngestionMethod.WEBHOOK,
        provider_metadata={
            k: v
            for k, v in {
                "momsn": body.get("momsn"),
                "serial": body.get("serial"),
                "device_type": body.get("device_type"),
                "session_status": body.get("iridium_session_status"),
                "transmit_time": transmitted.isoformat() if transmitted else None,
                "iridium_location": location or None,
                "bytes": len(data),
            }.items()
            if v not in (None, "")
        },
        satellite_delivered_at=transmitted,
        identity_type=IDENTITY_TYPE,
        identity_attributes={
            k: v for k, v in {"serial": body.get("serial")}.items() if v not in (None, "")
        },
        satellite_session=SatelliteSession(
            # `iridium_session_status` is not documented; the live deliveries carry the Iridium
            # code (2 with a 64 km estimate on the first one). Absent, a delivery with data
            # was a completed session.
            status=status_from_code(body.get("iridium_session_status"))
            if body.get("iridium_session_status") not in (None, "")
            else ("ok" if data else "unknown"),
            status_code=_code(body.get("iridium_session_status")),
            sequence=_code(body.get("momsn")),
            latitude=_float(body.get("iridium_latitude")),
            longitude=_float(body.get("iridium_longitude")),
            cep_km=_float(body.get("iridium_cep")),
            bytes=len(data),
            session_at=transmitted,
        ),
    )


def _code(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def parse_mt_response(text: str) -> str:
    """`OK,<mtId>` gives the id; `FAILED,<code>,<description>` raises with the code's
    meaning, an auth failure for 10 and a retryable outage for 99."""
    parts = [p.strip() for p in text.strip().split(",")]
    if parts and parts[0] == "OK":
        return parts[1] if len(parts) > 1 else ""
    if parts and parts[0] == "FAILED":
        code = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 0
        description = parts[2] if len(parts) > 2 else FAILURE_CODES.get(code, "unknown failure")
        meaning = FAILURE_CODES.get(code, description)
        if code == 10:
            raise _error(f"Rock7 refused the login ({meaning})", ErrorCode.CONNECTIVITY_AUTH_FAILED)
        if code == 99:
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
                message=f"Rock7 failed the request ({meaning})",
                component="adapter.rock7",
                retryable=True,
            )
        raise _error(f"Rock7 rejected the message ({code}: {meaning})", ErrorCode.COMMAND_REJECTED)
    raise _error(f"Rock7 answered something unexpected: {text[:200]}", ErrorCode.COMMAND_REJECTED)


class Rock7Client:
    def __init__(self, source: DataSourceContext) -> None:
        self.source = source
        self.url = str(source.config.get("mt_url") or MT_URL)
        self.username = str(source.credentials.get("username") or "").strip()
        self.password = str(source.credentials.get("password") or "")
        if not self.username or not self.password:
            raise _error(
                "the Rock7 source needs `username` and `password` in credentials",
                ErrorCode.CONNECTIVITY_AUTH_FAILED,
            )

    async def send(self, imei: str, data_hex: str, flush: bool = False) -> str:
        fields = {
            "imei": imei,
            "username": self.username,
            "password": self.password,
            "data": data_hex,
        }
        if flush:
            fields["flush"] = "yes"
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            response = await client.post(self.url, data=fields)
        if response.status_code >= 500:
            raise ApplicationError(
                code=ErrorCode.CONNECTIVITY_UNAVAILABLE,
                message=f"Rock7 answered {response.status_code}: {response.text[:200]}",
                component="adapter.rock7",
                retryable=True,
            )
        if response.status_code >= 400:
            raise _error(
                f"Rock7 rejected the call ({response.status_code}): {response.text[:200]}",
                ErrorCode.COMMAND_REJECTED,
            )
        return response.text


class Rock7Commands:
    """Command connector: the satellite frame `[port][msg_id][len][data]` as an MT message."""

    def __init__(self, source: DataSourceContext) -> None:
        self.source = source

    async def submit(
        self, external_id: str, payload: bytes, options: dict[str, Any]
    ) -> dict[str, Any]:
        frame = bytes([int(options["f_port"])]) + payload
        if len(frame) > SBD_MAX_BYTES:
            raise _error(
                f"satellite frame of {len(frame)} bytes exceeds the SBD maximum of {SBD_MAX_BYTES}",
                ErrorCode.COMMAND_REJECTED,
            )
        text = await Rock7Client(self.source).send(
            external_id, frame.hex(), flush=bool(options.get("flush"))
        )
        reference = parse_mt_response(text)
        return {
            "provider_ref": reference or None,
            "statuses": ["accepted_by_network", "queued"],
            "frame_hex": frame.hex(),
            "response": text.strip(),
        }


class Rock7Management:
    """No device list on Rock7 (the management system is the web UI); the connection test is
    the empty-message probe described in the module docstring."""

    def __init__(self, source: DataSourceContext) -> None:
        self.source = source

    async def test_connection(self) -> dict[str, Any]:
        text = await Rock7Client(self.source).send(PROBE_IMEI, "")
        try:
            parse_mt_response(text)
        except ApplicationError as error:
            if error.code == ErrorCode.CONNECTIVITY_AUTH_FAILED:
                raise
            return {"ok": True, "response": text.strip(), "note": "login accepted"}
        return {"ok": True, "response": text.strip()}


class Rock7Adapter:
    key: ClassVar[str] = "rock7"
    label: ClassVar[str] = "Rock7 RockBLOCK (Iridium)"
    push: ClassVar[bool] = True
    webhook_token_in_query: ClassVar[bool] = True
    acquisition_channel: ClassVar[AcquisitionChannel] = AcquisitionChannel.IRIDIUM
    config_example: ClassVar[dict[str, Any]] = {
        "allowed_source_ips": [],
        "web_url": "https://rockblock.rock7.com",
    }
    credentials_schema: ClassVar[dict[str, str]] = {
        "username": "Rock7 portal username (for commands only; not needed for inbound)",
        "password": "Rock7 portal password",
    }
    setup_hint: ClassVar[str] = (
        "At rockblock.rock7.com under Delivery Groups: make a group, add the RockBLOCKs to it, "
        "and under Delivery Addresses paste the webhook URL of this source, with its token, as "
        "the address with the format HTTP_POST (HTTP_JSON works as well; not the GeoJSON, "
        "ThingSpeak, email or SBD formats). There is no field for headers, which is why the "
        "token sits in the URL. The IMEI is the device identity."
    )
    default_capabilities: ClassVar[AdapterCapabilities] = AdapterCapabilities(
        uplink=True, downlink=True
    )
    channels: ClassVar[list[dict[str, Any]]] = [
        {
            "key": "http",
            "label": "Webhook",
            "direction": "in",
            "purpose": "A delivery group's delivery address, format HTTP_POST, with the token "
            "in the URL",
            "config_keys": [],
            "credential_keys": [],
        },
        {
            "key": "api",
            "label": "Rock7 MT endpoint",
            "direction": "out",
            "purpose": "Commands as MT messages with the portal login",
            "config_keys": [],
            "optional_keys": ["mt_url"],
            "credential_keys": ["username", "password"],
            "capabilities": ["downlink"],
        },
    ]
    default_link_templates: ClassVar[dict[str, str]] = {"OPEN_DEVICE": "{web_url}/"}
    config_schema: ClassVar[dict[str, Any]] = {
        "type": "object",
        "properties": {
            "allowed_source_ips": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Only these caller addresses may post; empty means any",
            },
            "web_url": {"type": "string", "description": "The management system, for links"},
            "mt_url": {"type": "string", "description": "Override of the MT endpoint"},
        },
    }

    def event_connector(self, source: DataSourceContext) -> EventConnector | None:
        return None

    def command_connector(self, source: DataSourceContext) -> Rock7Commands:
        return Rock7Commands(source)

    def management_connector(self, source: DataSourceContext) -> Rock7Management:
        return Rock7Management(source)

    def parse_webhook(
        self, source: DataSourceContext, body: Any, headers: dict[str, str]
    ) -> list[InboundMessage]:
        return [parse_message(require_object(body, self.key))]
