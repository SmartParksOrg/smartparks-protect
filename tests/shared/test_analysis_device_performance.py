"""The device performance primitives on synthetic series (docs/ANALYTICS_DEVICE_PERFORMANCE_PLAN.md,
section 11): a falling battery and the days it leaves, error flags per status, a frame counter
with gaps, silences between reports, and the levels from the driver's thresholds."""

from datetime import UTC, datetime

import numpy as np
import pytest

from shared.analysis.primitives.health import (
    DAY_S,
    bucketed,
    days_to,
    flag_shares,
    is_status,
    reboots_from,
    slope_per_day,
)
from shared.analysis.primitives.intervals import (
    decode_tlv_settings,
    expected_intervals,
    interval_report,
    merged_settings,
)
from shared.analysis.primitives.levels import (
    DEFAULTS,
    Threshold,
    ranks,
    thresholds_for,
    worst,
)
from shared.analysis.primitives.network import counter_gaps, fold_receptions, lost_share
from shared.device_drivers.base import HealthField

T0 = datetime(2026, 8, 1, tzinfo=UTC).timestamp()


def test_a_falling_battery_gives_its_slope_and_the_days_to_critical():
    # 4.0 V falling 10 mV a day for 20 days, one reading every six hours
    times = np.asarray([T0 + i * 6 * 3600 for i in range(80)])
    values = 4.0 - 0.010 * (times - T0) / DAY_S
    slope = slope_per_day(times, values)
    assert slope == pytest.approx(-0.010, rel=0.02)
    assert days_to(float(values[-1]), slope, 3.45) == pytest.approx(
        (values[-1] - 3.45) / 0.010, rel=0.02
    )
    assert days_to(3.9, 0.001, 3.45) is None  # not falling
    assert days_to(3.4, -0.01, 3.45) == 0
    assert slope_per_day(times[:4], values[:4]) is None  # one day of values says nothing
    daily = bucketed(times, values, DAY_S)
    assert len(daily) == 20 and daily[0][1] > daily[-1][1]


def test_error_flags_count_per_status_and_a_settings_frame_is_not_a_status():
    states = [
        {"errors": {"ublox_fix": i % 5 == 0, "flash": False}, "reset_reason": {"pin": False}}
        for i in range(20)
    ]
    settings = {"port_3_tlv": {"0x01": "100e0000"}}
    assert not is_status(settings) and is_status(states[0])
    shares = flag_shares(states)
    assert shares.statuses == 20
    assert shares.share_of("ublox_fix") == pytest.approx(0.2)
    assert shares.share_of("flash") == 0
    assert shares.any_share == pytest.approx(0.2)
    reboots = reboots_from(
        [
            (datetime(2026, 8, 3, tzinfo=UTC), {"reset_reason": "watchdog"}),
            (datetime(2026, 8, 2, tzinfo=UTC), None),
        ]
    )
    assert reboots.count == 2 and reboots.reasons == {"watchdog": 1, "unknown": 1}
    assert reboots.entries[0][1] == "unknown"  # sorted by time
    assert reboots.per_week(28 * DAY_S) == pytest.approx(0.5)


def test_frame_counters_with_gaps_give_the_lost_share_and_a_reset_is_no_gap():
    assert counter_gaps([1, 2, 3, 4]) == (0, 3)
    assert counter_gaps([1, 2, 5, 6]) == (2, 5)
    assert lost_share([1, 2, 5, 6]) == pytest.approx(0.4)
    # a counter going back to zero (a rejoin) starts a new run
    assert counter_gaps([10, 11, 0, 1, 2]) == (0, 3)
    assert lost_share([7]) is None


def test_receptions_fold_to_the_best_gateway_per_uplink_and_the_shares():
    rows = []
    for event in range(10):
        rows.append(("gw-a", event, -100.0 + event, 5.0, T0 + event * 60))
        if event < 3:
            rows.append(("gw-b", event, -80.0, 9.0, T0 + event * 60))
    folded = fold_receptions(rows)
    assert folded.uplinks == 10
    assert [g.gateway_id for g in folded.gateways] == ["gw-a", "gw-b"]
    assert folded.best is not None and folded.best.share == 1.0
    assert folded.gateways[1].share == pytest.approx(0.3)
    # the first three uplinks were heard best by gw-b
    assert folded.best_rssi[:3].tolist() == [-80.0, -80.0, -80.0]
    assert folded.best_rssi[3] == -97.0


def test_intervals_find_missed_reports_and_the_longest_silence():
    hour = 3600.0
    window_from, window_to = T0, T0 + 10 * DAY_S
    # hourly reports for three days, a week of silence, then hourly again for the last day
    times = np.asarray(
        [T0 + i * hour for i in range(72)] + [T0 + 9 * DAY_S + i * hour for i in range(24)]
    )
    report = interval_report(times, window_from, window_to, expected_s=hour)
    assert report.messages == 96 and report.expected_count == 240
    assert report.missed_share == pytest.approx(0.6)
    assert report.observed_median_s == hour
    assert report.silences == 1
    assert report.longest_silence_s == pytest.approx(6 * DAY_S + hour)
    assert report.longest_silence_end == pytest.approx(T0 + 9 * DAY_S)
    # a silence running to the end of the window has no end
    tail = interval_report(times[:72], window_from, window_to, expected_s=hour)
    assert tail.silences == 1 and tail.longest_silence_end is None
    # no expected interval: no missed share, silences against the median seen
    unknown = interval_report(times, window_from, window_to, expected_s=None)
    assert unknown.missed_share is None and unknown.silences == 1


def test_settings_frames_decode_by_the_catalogue_and_the_layers_merge():
    catalog = [
        {"id": 1, "name": "lr_gps_interval", "type": "uint32"},
        {"id": 3, "name": "status_send_interval", "type": "uint32"},
        {"id": 9, "name": "flag", "type": "uint8"},
    ]
    decoded = decode_tlv_settings(
        {"0x01": "100e0000", "0x03": "10", "0x09": "01", "0x7f": "aa"}, catalog
    )
    assert decoded == {"lr_gps_interval": 3600, "flag": 1}  # a short value is left out
    settings = merged_settings({"lr_gps_interval": 0, "status_send_interval": 3600}, decoded)
    assert expected_intervals(settings) == {"fix": 3600.0, "status": 3600.0, "satellite": None}
    assert expected_intervals({"ublox_send_interval": 600})["fix"] == 600.0


def test_levels_come_from_the_driver_first_and_the_defaults_second():
    fields = (
        HealthField("battery_voltage", "Battery", unit="V", warn_below=3.7, critical_below=3.5),
    )
    thresholds = thresholds_for(fields)
    assert thresholds["battery_v"].level(3.65) == "warn"
    assert thresholds["battery_v"].level(3.45) == "critical"
    assert DEFAULTS["battery_v"].level(3.65) == "ok"
    assert thresholds["fix_success"] is DEFAULTS["fix_success"]
    assert (
        DEFAULTS["fix_success"].level(0.79) == "warn"
        and DEFAULTS["fix_success"].level(0.4) == "critical"
    )
    assert DEFAULTS["reboots_per_week"].level(1.0) == "warn"
    assert (
        DEFAULTS["invalid_share"].level(0.0) == "ok"
        and DEFAULTS["invalid_share"].level(0.001) == "warn"
    )
    assert Threshold(warn_at=1).level(None) is None
    assert "warn below 3.6 V" in DEFAULTS["battery_v"].describe()
    assert worst(["ok", None, "warn"]) == "warn" and worst([None]) is None
    # ranks: 1 is the worst; a low battery ranks first, a high loss share ranks first
    assert ranks({"a": 3.9, "b": 3.5, "c": None}, "battery_v") == {"b": 1, "a": 2}
    assert ranks({"a": 0.1, "b": 0.3, "c": 0.3}, "lost_uplinks_share") == {"b": 1, "c": 1, "a": 3}
