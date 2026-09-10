"""A location the network provides about a device (decision D162, ADR 0024): an Iridium
session's estimate the network stands by, ThingPark's `DevEUI_location` (network
geolocation), The Things Stack's `location_solved`. Adapters put it on the inbound message,
the ingest stores it as `provider_metadata["network_location"]`, and the decoder writes it as
a position of `record_type` "network" with the radius as accuracy, kept apart from the
device's own fixes by the canonical key and left out of every reader unless asked.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from shared.connectivity.satellite import SatelliteSession
from shared.timeutil import require_aware

NETWORK_RECORD_TYPE = "network"


@dataclass(slots=True)
class NetworkLocation:
    latitude: float
    longitude: float
    time: datetime
    method: str = "network"
    accuracy_m: float | None = None
    altitude_m: float | None = None
    attributes: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        require_aware(self.time)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["time"] = self.time.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: Any) -> NetworkLocation | None:
        if not isinstance(data, dict):
            return None
        try:
            latitude, longitude = float(data["latitude"]), float(data["longitude"])
            time = datetime.fromisoformat(str(data["time"]))
        except (KeyError, TypeError, ValueError):
            return None
        return cls(
            latitude=latitude,
            longitude=longitude,
            time=time,
            method=str(data.get("method") or "network"),
            accuracy_m=_float(data.get("accuracy_m")),
            altitude_m=_float(data.get("altitude_m")),
            attributes=data.get("attributes") if isinstance(data.get("attributes"), dict) else None,
        )

    @classmethod
    def from_satellite(cls, session: SatelliteSession) -> NetworkLocation | None:
        """The Iridium estimate as a location, only when the session stands by it."""
        if not session.has_estimate or session.session_at is None:
            return None
        assert session.latitude is not None and session.longitude is not None
        return cls(
            latitude=session.latitude,
            longitude=session.longitude,
            time=session.session_at,
            method="iridium_estimate",
            accuracy_m=session.cep_km * 1000 if session.cep_km is not None else None,
            attributes={"cep_km": session.cep_km, "sequence": session.sequence},
        )


def _float(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None
