"""Time helpers. Every datetime in this codebase is timezone-aware and stored in UTC."""

from datetime import UTC, datetime


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
