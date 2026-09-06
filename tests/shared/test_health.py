"""Device health (decision D104): what the driver declares, read from the current state."""

from datetime import UTC, datetime

from shared.device_drivers.base import HealthField
from shared.device_drivers.registry import DRIVERS
from shared.domain.health import device_health

NOW = datetime(2026, 9, 6, 8, 0, tzinfo=UTC)


def _measurements(**values):
    return {k: {"value": v, "time": NOW.isoformat()} for k, v in values.items()}


def test_opencollar_declares_its_health_from_the_status_message():
    fields = DRIVERS["opencollar"].health
    keys = [f.key for f in fields]
    assert keys[:4] == ["battery_voltage", "charging_voltage", "device_temperature", "uptime"]
    assert {"errors", "firmware_version", "gnss_accuracy"} <= set(keys)
    assert all(isinstance(f, HealthField) for f in fields)


def test_levels_and_texts():
    fields = DRIVERS["opencollar"].health
    health = device_health(
        fields,
        latest_measurements=_measurements(
            battery_voltage=3.5, device_temperature=21.4, uptime=30 * 86400 + 7200, gnss_accuracy=8
        ),
        latest_state={
            "firmware_version": "7.2",
            "errors": {"lr_module": False, "ble": False},
            "reset_reason": {"pin": False, "watchdog": True},
        },
        latest_state_time=NOW,
        last_seen_at=NOW,
    )
    by_key = {f.key: f for f in health.fields}
    assert health.level == "warn" and health.last_status_at == NOW
    assert by_key["battery_voltage"].level == "warn" and by_key["battery_voltage"].unit == "V"
    assert by_key["device_temperature"].level == "ok"
    assert by_key["uptime"].text == "30 d 2 h" and by_key["uptime"].level is None
    assert by_key["errors"].text == "none" and by_key["errors"].level == "ok"
    assert by_key["reset_reason"].text == "watchdog" and by_key["reset_reason"].level is None
    assert by_key["firmware_version"].text == "7.2" and by_key["firmware_version"].at == NOW
    assert by_key["gnss_accuracy"].level == "ok" and by_key["gnss_accuracy"].at == NOW
    assert "charging_voltage" not in by_key  # never reported: not shown

    critical = device_health(
        fields,
        latest_measurements=_measurements(battery_voltage=3.3),
        latest_state={"errors": {"flash": True, "ble": False}},
        latest_state_time=NOW,
        last_seen_at=NOW,
    )
    assert critical.level == "critical"
    assert {f.key: f.text for f in critical.fields}["errors"] == "flash"


def test_a_driver_without_health_gives_last_seen_only():
    health = device_health(
        getattr(DRIVERS["generic_json"], "health", None),
        latest_measurements=_measurements(battery_voltage=3.0),
        latest_state={},
        latest_state_time=None,
        last_seen_at=NOW,
    )
    assert health.fields == [] and health.level is None and health.last_seen_at == NOW
