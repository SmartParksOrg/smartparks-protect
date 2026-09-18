"""The battery type per device (decision D248): the thresholds and the share of charge follow
the chemistry, and the type is resolved device, device type, driver."""

import pytest

from shared.device_drivers.base import HealthField
from shared.domain.battery import PROFILES, BatteryChoice, resolve
from shared.domain.health import device_health


def test_the_same_voltage_means_different_things_per_chemistry():
    """Tim, 2026-09-18: 3.60 V is a healthy primary cell and a half-empty lithium-ion one."""
    primary = PROFILES["primary_lithium"]
    ion = PROFILES["lithium_ion"]
    assert primary.level(3.60) == "ok"
    assert ion.level(3.60) == "warn"
    assert primary.percent(3.60) > 60
    assert 20 < ion.percent(3.60) < 40


@pytest.mark.parametrize("key", list(PROFILES))
def test_every_curve_runs_from_empty_to_full(key):
    profile = PROFILES[key]
    volts = [v for v, _ in profile.curve]
    shares = [p for _, p in profile.curve]
    assert volts == sorted(volts), "the curve runs from the lowest voltage up"
    assert shares == sorted(shares), "the share of charge never falls as the voltage rises"
    assert profile.percent(profile.curve[0][0] - 1) == 0
    assert profile.percent(profile.curve[-1][0] + 1) == 100
    assert profile.critical_v <= profile.warn_v <= profile.full_v
    # a voltage between two points lands between their shares
    low_v, low_p = profile.curve[0]
    high_v, high_p = profile.curve[1]
    middle = profile.percent((low_v + high_v) / 2)
    assert low_p <= middle <= high_p


def test_the_narrowest_type_wins():
    class Driver:
        default_battery_type = "primary_lithium"

    assert resolve(None, None, None) == BatteryChoice(None, "none")
    assert resolve(None, None, Driver()).source == "driver"
    assert resolve(None, {"battery_type": "lifepo4"}, Driver()) == BatteryChoice(
        PROFILES["lifepo4"], "device_type"
    )
    chosen = resolve(
        {"battery_type": {"key": "lithium_ion"}}, {"battery_type": "lifepo4"}, Driver()
    )
    assert chosen == BatteryChoice(PROFILES["lithium_ion"], "device")
    # a type nobody knows is not a type
    assert resolve({"battery_type": {"key": "nuclear"}}, None, None).profile is None


def test_the_health_line_takes_the_chemistry_and_carries_the_share():
    fields = (
        HealthField("battery_voltage", "Battery", unit="V", warn_below=3.6, critical_below=3.45),
    )
    measurements = {"battery_voltage": {"value": 3.58, "time": "2026-09-18T10:00:00+00:00"}}
    common = {
        "latest_measurements": measurements,
        "latest_state": {},
        "latest_state_time": None,
        "last_seen_at": None,
    }
    # without a type the driver's thresholds stand, as before
    plain = device_health(fields, **common)
    assert plain.fields[0].level == "warn" and plain.fields[0].percent is None
    # with a primary lithium cell 3.58 V is a normal reading
    typed = device_health(fields, **common, battery=PROFILES["primary_lithium"])
    assert typed.level == "ok" and typed.fields[0].level == "ok"
    assert typed.fields[0].percent == PROFILES["primary_lithium"].percent(3.58)
    assert "%" in (typed.fields[0].text or "")
    # with a lithium-ion cell the same voltage is low
    ion = device_health(fields, **common, battery=PROFILES["lithium_ion"])
    assert ion.level == "warn" and ion.fields[0].level == "warn"
