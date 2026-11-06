from shared.enums import ValueType
from shared.metrics.seeds import METRIC_SEEDS, seed_sql


def test_seed_keys_are_unique_snake_case():
    keys = [m.key for m in METRIC_SEEDS]
    assert len(keys) == len(set(keys))
    assert all(k == k.lower() and " " not in k for k in keys)


def test_seed_sql_is_idempotent_insert():
    sql = seed_sql()
    assert sql.startswith("INSERT INTO metrics") and sql.endswith("ON CONFLICT (key) DO NOTHING")
    assert "'battery_voltage'" in sql and "'°C'" in sql


def test_the_opencollar_driver_metrics_are_seeded():
    # F10: the keys the OpenCollar driver writes that the decoder used to register as uncategorized
    by_key = {m.key: m for m in METRIC_SEEDS}
    expected = {
        "switch_active": ("infrastructure", None, ValueType.BOOLEAN),
        "switch_count": ("infrastructure", None, ValueType.NUMERIC),
        "lr_satellites": ("positioning", None, ValueType.NUMERIC),
        "gnss_pdop": ("positioning", None, ValueType.NUMERIC),
        "flash_used_percent": ("device_health", "%", ValueType.NUMERIC),
        "flash_messages": ("device_health", None, ValueType.NUMERIC),
        "charging_voltage": ("device_health", "V", ValueType.NUMERIC),
        "clock_offset": ("device_health", "s", ValueType.NUMERIC),
    }
    for key, (category, unit, value_type) in expected.items():
        seed = by_key[key]
        assert (seed.category, seed.unit, seed.value_type) == (category, unit, value_type), key
