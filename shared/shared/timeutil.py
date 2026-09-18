"""Time helpers. Every datetime in this codebase is timezone-aware and stored in UTC."""

from datetime import UTC, datetime

from shared.enums import AcquisitionChannel


class NaiveDatetimeError(ValueError):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC)


def require_aware(value: datetime) -> datetime:
    """Raise on a naive datetime. Called at every boundary where a time enters the system."""
    if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
        raise NaiveDatetimeError(f"naive datetime not allowed: {value!r}")
    return value


def to_utc(value: datetime) -> datetime:
    return require_aware(value).astimezone(UTC)


def clock_ahead(record_time: datetime, received_at: datetime, tolerance_seconds: int) -> float:
    """Seconds a record's device time runs ahead of the moment it was delivered, when that is
    more than the tolerance; 0.0 otherwise (decision D119). Late records are never a problem:
    flash logs and satellite deliveries arrive after the fact by design, a clock cannot know
    the future."""
    ahead = (record_time - received_at).total_seconds()
    return ahead if ahead > tolerance_seconds else 0.0


def clock_behind(record_time: datetime, received_at: datetime, tolerance_seconds: int) -> float:
    """Seconds a record's device time runs behind its delivery, beyond the tolerance (decision
    D259); 0.0 otherwise.

    This is only a fault on a path that delivers as it happens. A flash log or a Bluetooth sync
    carries the past on purpose and a satellite message waits for a pass, so the caller asks
    this only for a live channel (`delivers_live`). Some OpenCollar firmware sets the clock
    wrongly, and a PWN reader is timing its scans 45 hours before they arrive."""
    behind = (received_at - record_time).total_seconds()
    return behind if behind > tolerance_seconds else 0.0


def delivers_live(channel: str | None) -> bool:
    """Whether a delivery path is expected to arrive about when the record was made, so that a
    device time far from it is the clock's fault rather than the path's."""
    return channel == AcquisitionChannel.LORAWAN
