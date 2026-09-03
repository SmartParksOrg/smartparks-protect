from shared.metrics.seeds import METRIC_SEEDS, seed_sql


def test_seed_keys_are_unique_snake_case():
    keys = [m.key for m in METRIC_SEEDS]
    assert len(keys) == len(set(keys))
    assert all(k == k.lower() and " " not in k for k in keys)


def test_seed_sql_is_idempotent_insert():
    sql = seed_sql()
    assert sql.startswith("INSERT INTO metrics") and sql.endswith("ON CONFLICT (key) DO NOTHING")
    assert "'battery_voltage'" in sql and "'°C'" in sql
