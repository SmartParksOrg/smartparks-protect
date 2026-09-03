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
