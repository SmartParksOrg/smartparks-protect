"""The satellite session behind an Iridium delivery (architecture 25.9, decision D158): what
the network knows about the transfer, normalised across Cloudloop and Rock7 so the ingest, the
decoder, the traffic view and the map read one shape.

An SBD session reports a status (the Iridium DirectIP codes, which Cloudloop names and Rock7
numbers), a mobile-originated sequence number (MOMSN, counted by the modem per completed
session), the sequence number of the mobile-terminated message transferred in the session
(MTMSN, 0 when none), and a network estimate of the modem's position with its circular error
probable in kilometres, "(very) approximate" in Cloudloop's words. The estimate is never a
canonical position: it is provenance, kept on the source event and shown as a circle.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from shared.timeutil import require_aware

# Iridium SBD mobile-originated session status (DirectIP), by code and by Cloudloop's names.
STATUS_BY_CODE: dict[int, str] = {
    0: "ok",
    1: "mt_too_large",
    2: "location_unacceptable",
    10: "timeout",
    12: "mo_too_large",
    13: "rf_link_loss",
    14: "imei_anomaly",
    15: "prohibited",
}
STATUS_BY_NAME: dict[str, str] = {
    "SESSION_STATUS_OK": "ok",
    "SESSION_STATUS_ERROR_MT_TOO_LARGE": "mt_too_large",
    "SESSION_STATUS_ERROR_UNACCEPTABLE_QUALITY": "location_unacceptable",
    "SESSION_STATUS_ERROR_SESSION_TIMEOUT": "timeout",
    "SESSION_STATUS_ERROR_MO_TOO_LARGE": "mo_too_large",
    "SESSION_STATUS_ERROR_RF_LINK_LOSS": "rf_link_loss",
    "SESSION_STATUS_ERROR_IMEI_ANOMALY": "imei_anomaly",
    "SESSION_STATUS_ERROR_IMEI_PROHIBITED": "prohibited",
}
STATUS_TEXT: dict[str, str] = {
    "ok": "session completed",
    "mt_too_large": "the queued message for the device is too large for one session",
    "location_unacceptable": "session completed, the network's location estimate is poor",
    "timeout": "the session timed out",
    "mo_too_large": "the device's message is too large for one session",
    "rf_link_loss": "the radio link was lost during the session",
    "imei_anomaly": "protocol anomaly during the session",
    "prohibited": "the modem is barred from the Iridium gateway",
    "unknown": "status not reported",
}
# The data of the session arrived (the MO transfer succeeded) for these statuses; the others
# describe a session that carried nothing.
DELIVERED_STATUSES = frozenset({"ok", "mt_too_large", "location_unacceptable"})
# The estimate is only worth showing when the network did not disown it.
ESTIMATE_STATUSES = frozenset({"ok", "mt_too_large"})
EARTH_RADIUS_M = 6_371_008.8


def status_from_code(code: Any) -> str:
    try:
        return STATUS_BY_CODE.get(int(code), "unknown") if code not in (None, "") else "unknown"
    except (TypeError, ValueError):
        return "unknown"


def status_from_name(name: Any) -> str:
    return STATUS_BY_NAME.get(str(name or ""), "unknown")


def status_level(status: str) -> str:
    """The health level of the last session: a failed session warns, a barred modem is
    critical, a poor location estimate is not the device's fault."""
    if status == "prohibited":
        return "critical"
    if status in DELIVERED_STATUSES or status == "unknown":
        return "ok"
    return "warn"


@dataclass(slots=True)
class SatelliteSession:
    status: str = "unknown"
    status_code: int | None = None
    sequence: int | None = None
    mt_sequence: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    cep_km: float | None = None
    bytes: int = 0
    session_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.session_at is not None:
            require_aware(self.session_at)

    @property
    def status_text(self) -> str:
        return STATUS_TEXT.get(self.status, STATUS_TEXT["unknown"])

    @property
    def has_estimate(self) -> bool:
        return (
            self.latitude is not None
            and self.longitude is not None
            and self.status in ESTIMATE_STATUSES
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["session_at"] = self.session_at.isoformat() if self.session_at else None
        data["status_text"] = self.status_text
        return data

    @classmethod
    def from_dict(cls, data: Any) -> SatelliteSession | None:
        if not isinstance(data, dict):
            return None
        session_at = data.get("session_at")
        return cls(
            status=str(data.get("status") or "unknown"),
            status_code=_int(data.get("status_code")),
            sequence=_int(data.get("sequence")),
            mt_sequence=_int(data.get("mt_sequence")),
            latitude=_float(data.get("latitude")),
            longitude=_float(data.get("longitude")),
            cep_km=_float(data.get("cep_km")),
            bytes=_int(data.get("bytes")) or 0,
            session_at=datetime.fromisoformat(str(session_at)) if session_at else None,
        )


def _int(value: Any) -> int | None:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres (haversine)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(a))


# A fix this many CEP radii from the estimate is worth a note: the CEP holds half of the
# outcomes, so three of them cover almost every honest session.
OUTSIDE_CEP_FACTOR = 3.0


def estimate_disagreement(
    session: SatelliteSession, latitude: float, longitude: float
) -> float | None:
    """Metres between a decoded fix and the network estimate when the fix lies outside the
    estimate's circle by `OUTSIDE_CEP_FACTOR`; None when the estimate is absent or poor, or
    the fix lies within it."""
    if not session.has_estimate or session.cep_km is None:
        return None
    assert session.latitude is not None and session.longitude is not None
    metres = distance_m(session.latitude, session.longitude, latitude, longitude)
    if metres <= session.cep_km * 1000 * OUTSIDE_CEP_FACTOR:
        return None
    return metres
