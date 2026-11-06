"""The status a gateway is shown with (decision D370).

The registry stores the last word about a gateway: the platform's (its gateway list, a
connection event) or a reception's (an uplink the gateway relayed sets it online). Neither ages
by itself, so a gateway that fell silent kept reading "online" for weeks. The reads derive the
status from the word, who gave it and the age of the newest evidence:

- the platform's word stands while it is fresh (within `platform_hours`, longer than the daily
  gateway sync), since the platform hears the gateway's own status reports whether or not a
  device spoke;
- otherwise the gateway is online while it was seen (a reception, a status report, the
  platform's list) within `silent_hours`, and `silent` after that;
- a gateway the platform called offline stays offline until something is heard from it again (a
  reception sets it online), and a gateway nothing was ever heard from is `unknown`.
"""

from datetime import datetime, timedelta

from shared.enums import ConnectivityStatus

SILENT = "silent"
PLATFORM = "platform"
RECEPTION = "reception"


def effective_status(
    status: str,
    status_source: str | None,
    status_at: datetime | None,
    last_seen_at: datetime | None,
    now: datetime,
    *,
    silent_hours: float,
    platform_hours: float,
) -> str:
    """The status to show for a gateway row's stored word and evidence."""
    if status == ConnectivityStatus.OFFLINE:
        return ConnectivityStatus.OFFLINE
    if (
        status_source == PLATFORM
        and status_at is not None
        and now - status_at <= timedelta(hours=platform_hours)
        and status in (ConnectivityStatus.ONLINE, ConnectivityStatus.UNKNOWN)
    ):
        return status
    if last_seen_at is None:
        return ConnectivityStatus.UNKNOWN
    if now - last_seen_at <= timedelta(hours=silent_hours):
        return ConnectivityStatus.ONLINE
    return SILENT
