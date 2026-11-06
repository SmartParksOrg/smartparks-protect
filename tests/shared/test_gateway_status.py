"""The status a gateway is shown with (decision D370): the platform's word while fresh, else
the age of the evidence."""

from datetime import UTC, datetime, timedelta

from shared.domain.gateways import PLATFORM, RECEPTION, SILENT, effective_status

NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
BOUNDS = {"silent_hours": 24, "platform_hours": 36}


def hours_ago(hours: float) -> datetime:
    return NOW - timedelta(hours=hours)


def test_a_reception_keeps_a_gateway_online_for_a_day_then_silent() -> None:
    assert (
        effective_status("online", RECEPTION, hours_ago(2), hours_ago(2), NOW, **BOUNDS) == "online"
    )
    assert (
        effective_status("online", RECEPTION, hours_ago(23), hours_ago(23), NOW, **BOUNDS)
        == "online"
    )
    # ac1f09fffe1e9c83 on dev: last uplink relayed eight days before, still "online" stored
    assert (
        effective_status("online", RECEPTION, hours_ago(190), hours_ago(190), NOW, **BOUNDS)
        == SILENT
    )


def test_the_platforms_word_stands_while_fresh_then_the_evidence_decides() -> None:
    # the daily sync said online this morning; the gateway relays nothing, its own status
    # reports reach the platform and the platform's word is what we have
    assert (
        effective_status("online", PLATFORM, hours_ago(10), hours_ago(100), NOW, **BOUNDS)
        == "online"
    )
    assert effective_status("unknown", PLATFORM, hours_ago(10), None, NOW, **BOUNDS) == "unknown"
    # the sync has not run for two days: the word is stale, nothing was heard for four days
    assert (
        effective_status("online", PLATFORM, hours_ago(50), hours_ago(100), NOW, **BOUNDS) == SILENT
    )
    # stale word, but a reception came yesterday
    assert (
        effective_status("online", PLATFORM, hours_ago(50), hours_ago(5), NOW, **BOUNDS) == "online"
    )


def test_offline_stands_and_nothing_heard_is_unknown() -> None:
    assert (
        effective_status("offline", PLATFORM, hours_ago(1), hours_ago(1), NOW, **BOUNDS)
        == "offline"
    )
    assert (
        effective_status("offline", PLATFORM, hours_ago(500), hours_ago(500), NOW, **BOUNDS)
        == "offline"
    )
    assert effective_status("unknown", None, None, None, NOW, **BOUNDS) == "unknown"
    # a row from before migration 0059: no source, judged by the age of its evidence
    assert effective_status("online", None, None, hours_ago(3), NOW, **BOUNDS) == "online"
    assert effective_status("online", None, None, hours_ago(30), NOW, **BOUNDS) == SILENT
