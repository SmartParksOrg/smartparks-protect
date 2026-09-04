"""The stateful evaluator with an in-memory data access: edge triggering, cooldown, FOR,
enter and exit, no-data, window aggregates and boolean composition."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from shapely.geometry import Polygon

from shared.rules.evaluator import (
    FeatureGeometry,
    Sample,
    Subject,
    SubjectState,
    evaluate,
    format_title,
)
from shared.rules.schema import RuleDocument, TriggerKind

pytestmark = pytest.mark.asyncio

T0 = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)
PROJECT = uuid.uuid4()
ENTITY = uuid.uuid4()
FENCE = uuid.uuid4()
SUBJECT = Subject(PROJECT, ENTITY, uuid.uuid4())


class Memory:
    def __init__(self) -> None:
        self.values: dict[str, float] = {}
        self.point: tuple[float, float] | None = None
        self.windows: dict[str, float | None] = {}
        self.seen: datetime | None = None
        self.fences = [
            FeatureGeometry(
                FENCE, "Core area", "geofence", Polygon([(0, 0), (1, 0), (1, 1), (0, 1)])
            )
        ]

    async def latest_value(self, subject, metric, before):
        return self.values.get(metric)

    async def latest_point(self, subject, before):
        return (self.point, before) if self.point else None

    async def window(self, subject, metric, aggregate, seconds, at):
        return self.windows.get(f"{aggregate}_{metric}")

    async def features(self, project_id, feature_ids, feature_type):
        return self.fences

    async def last_seen(self, subject, at):
        return self.seen


def doc(**overrides):
    base = {
        "trigger": {"kind": "measurement", "metric_key": "battery_voltage"},
        "conditions": {"type": "threshold", "metric": "battery_voltage", "op": "<", "value": 3.2},
        "event": {"event_type": "BATTERY_LOW", "title": "{entity} at {value} V"},
    }
    base.update(overrides)
    return RuleDocument.model_validate(base)


def measurement(value: float, minutes: int = 0) -> Sample:
    return Sample(
        time=T0 + timedelta(minutes=minutes),
        kind=TriggerKind.MEASUREMENT,
        values={"battery_voltage": value},
        metric_key="battery_voltage",
    )


async def test_threshold_fires_on_the_edge_only():
    d, state, data = doc(), SubjectState(), Memory()
    assert (await evaluate(d, SUBJECT, measurement(3.5, 0), state, data)).fire is False
    first = await evaluate(d, SUBJECT, measurement(3.1, 1), state, data)
    assert first.fire is True and first.reason == "condition became true"
    assert first.context["value"] == 3.1 and first.context["metric"] == "battery_voltage"
    again = await evaluate(d, SUBJECT, measurement(3.0, 2), state, data)
    assert again.fire is False and again.reason == "still active"
    assert (await evaluate(d, SUBJECT, measurement(3.6, 3), state, data)).fire is False
    assert (await evaluate(d, SUBJECT, measurement(3.0, 4), state, data)).fire is True


async def test_cooldown_reminds_while_active():
    d, state, data = doc(cooldown_seconds=600), SubjectState(), Memory()
    assert (await evaluate(d, SUBJECT, measurement(3.0, 0), state, data)).fire is True
    assert (await evaluate(d, SUBJECT, measurement(3.0, 5), state, data)).fire is False
    reminder = await evaluate(d, SUBJECT, measurement(3.0, 11), state, data)
    assert reminder.fire is True and reminder.reason == "reminder after cooldown"


async def test_for_duration_needs_the_condition_to_hold():
    d, state, data = doc(for_seconds=120), SubjectState(), Memory()
    assert (await evaluate(d, SUBJECT, measurement(3.0, 0), state, data)).fire is False
    assert (await evaluate(d, SUBJECT, measurement(3.0, 1), state, data)).fire is False
    assert (await evaluate(d, SUBJECT, measurement(3.0, 2), state, data)).fire is True
    # a break resets the hold
    assert (await evaluate(d, SUBJECT, measurement(3.5, 3), state, data)).fire is False
    assert (await evaluate(d, SUBJECT, measurement(3.0, 4), state, data)).fire is False
    assert state.holding_since == T0 + timedelta(minutes=4)


async def test_state_round_trips_through_json():
    d, state, data = doc(), SubjectState(), Memory()
    await evaluate(d, SUBJECT, measurement(3.0, 0), state, data)
    restored = SubjectState.from_dict(state.to_dict())
    assert restored.active is True and restored.last_fired_at == T0


def position(x: float, y: float, minutes: int, speed_mps: float | None = None) -> Sample:
    values = {"latitude": y, "longitude": x}
    if speed_mps is not None:
        values["speed_kmh"] = speed_mps * 3.6
    return Sample(
        time=T0 + timedelta(minutes=minutes), kind=TriggerKind.POSITION, values=values, point=(x, y)
    )


async def test_enter_and_exit_fire_on_the_crossing():
    exit_rule = doc(
        trigger={"kind": "position"},
        conditions={"type": "spatial", "relation": "exit", "feature_type": "geofence"},
        event={"event_type": "GEOFENCE_EXIT", "title": "{entity} left {feature}"},
    )
    state, data = SubjectState(), Memory()
    # first sample inside: no history, so no transition
    assert (await evaluate(exit_rule, SUBJECT, position(0.5, 0.5, 0), state, data)).fire is False
    assert state.inside == {str(FENCE): True}
    still = await evaluate(exit_rule, SUBJECT, position(0.6, 0.5, 1), state, data)
    assert still.fire is False
    left = await evaluate(exit_rule, SUBJECT, position(2, 2, 2), state, data)
    assert left.fire is True and left.context["feature"] == "Core area"
    assert (await evaluate(exit_rule, SUBJECT, position(3, 3, 3), state, data)).fire is False
    # back in, then out again fires again
    await evaluate(exit_rule, SUBJECT, position(0.5, 0.5, 4), state, data)
    assert (await evaluate(exit_rule, SUBJECT, position(2, 2, 5), state, data)).fire is True


async def test_inside_and_speed_with_for():
    rule = doc(
        trigger={"kind": "position"},
        conditions={
            "all": [
                {"type": "threshold", "metric": "speed_kmh", "op": ">", "value": 40},
                {"type": "spatial", "relation": "inside", "feature_type": "geofence"},
            ]
        },
        for_seconds=30,
        event={"event_type": "SPEED", "title": "{entity} at {value} km/h in {feature}"},
    )
    state, data = SubjectState(), Memory()
    fast = 15.0  # 54 km/h
    assert (await evaluate(rule, SUBJECT, position(0.5, 0.5, 0, fast), state, data)).fire is False
    verdict = await evaluate(rule, SUBJECT, position(0.5, 0.6, 1, fast), state, data)
    assert verdict.fire is True and verdict.context["feature"] == "Core area"
    assert round(verdict.context["value"], 1) == 54.0
    # fast but outside: false
    assert (await evaluate(rule, SUBJECT, position(5, 5, 2, fast), state, data)).fire is False


async def test_no_data_on_a_schedule():
    rule = doc(
        trigger={"kind": "schedule", "every_seconds": 300},
        conditions={"type": "no_data", "for_seconds": 3600},
        event={"event_type": "NO_DATA", "title": "{entity} silent"},
    )
    state, data = SubjectState(), Memory()
    tick = Sample(time=T0, kind=TriggerKind.SCHEDULE)
    assert (await evaluate(rule, SUBJECT, tick, state, data)).fire is False  # never seen
    data.seen = T0 - timedelta(minutes=30)
    assert (await evaluate(rule, SUBJECT, tick, state, data)).fire is False
    data.seen = T0 - timedelta(hours=2)
    silent = await evaluate(rule, SUBJECT, tick, state, data)
    assert silent.fire is True and silent.context["values"]["silence_hours"] == 2.0
    later = Sample(time=T0 + timedelta(minutes=5), kind=TriggerKind.SCHEDULE)
    assert (await evaluate(rule, SUBJECT, later, state, data)).fire is False
    data.seen = T0 + timedelta(minutes=4)  # data resumed: the condition clears
    assert (await evaluate(rule, SUBJECT, later, state, data)).condition is False


async def test_window_and_not():
    rule = doc(
        trigger={"kind": "schedule", "every_seconds": 3600},
        conditions={
            "all": [
                {
                    "type": "window",
                    "metric": "activity",
                    "aggregate": "avg",
                    "seconds": 21600,
                    "op": "<",
                    "value": 10,
                },
                {
                    "not": {
                        "type": "threshold",
                        "metric": "battery_voltage",
                        "op": "<",
                        "value": 3.2,
                    }
                },
            ]
        },
        event={"event_type": "IMMOBILE", "title": "{entity} activity {value}"},
    )
    state, data = SubjectState(), Memory()
    tick = Sample(time=T0, kind=TriggerKind.SCHEDULE)
    data.windows["avg_activity"] = 4.0
    data.values["battery_voltage"] = 3.0
    assert (await evaluate(rule, SUBJECT, tick, state, data)).fire is False
    data.values["battery_voltage"] = 3.8
    verdict = await evaluate(rule, SUBJECT, tick, state, data)
    assert verdict.fire is True and verdict.context["values"]["avg_activity"] == 4.0


async def test_missing_data_is_false_and_reported():
    d, state, data = doc(), SubjectState(), Memory()
    sample = Sample(time=T0, kind=TriggerKind.MEASUREMENT, values={}, metric_key="temperature")
    verdict = await evaluate(d, SUBJECT, sample, state, data)
    assert verdict.fire is False and verdict.context["missing"] == ["battery_voltage"]


async def test_format_title_is_forgiving():
    assert (
        format_title("{entity} at {value} V", entity="Rhino 14", value=3.1) == "Rhino 14 at 3.1 V"
    )
    assert format_title("{entity} {unknown}", entity="x") == "x ?"
    assert format_title("{broken", entity="x") == "{broken"
