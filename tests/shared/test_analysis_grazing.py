"""The grazing figures on synthetic herds (docs/ANALYTICS_PHASE1_PLAN.md, section 17)."""

import math
import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest
from shapely.geometry import Polygon, mapping

from shared.analysis.base import Subject
from shared.analysis.modules.grazing import (
    Animal,
    Area,
    _visits,
    area_use,
    containment,
    weights_of,
)
from shared.analysis.primitives.timeagg import local_days
from shared.analysis.primitives.trajectory import time_weights, trajectory_from

LAT, LON = -19.0, 23.5
M_PER_DEG_LAT = 111_320.0
M_PER_DEG_LON = M_PER_DEG_LAT * math.cos(math.radians(LAT))
START = datetime(2026, 5, 1, tzinfo=UTC)
GAP_S = 4 * 3600


def _square(name: str, lat: float, lon: float, hectares: float) -> Area:
    side = math.sqrt(hectares * 10_000)
    dlat, dlon = side / M_PER_DEG_LAT, side / M_PER_DEG_LON
    ring = [(lon, lat), (lon + dlon, lat), (lon + dlon, lat + dlat), (lon, lat + dlat), (lon, lat)]
    polygon = Polygon(ring)
    return Area(uuid.uuid4(), name, "zone", polygon, dict(mapping(polygon)), hectares)


def _animal(
    name: str,
    lat: float,
    lon: float,
    areas: list[Area],
    *,
    hours: float = 24,
    step_min: float = 10,
    start: datetime = START,
) -> Animal:
    n = int(hours * 60 / step_min)
    times = [start.timestamp() + i * step_min * 60 for i in range(n)]
    track = trajectory_from(uuid.uuid4(), times, [lat] * n, [lon] * n)
    animal = Animal(
        Subject(id=track.entity_id, name=name),
        track,
        time_weights(track, GAP_S),
        local_days(track.times, "UTC"),
    )
    animal.inside = containment(track, areas)
    return animal


def _centre(area: Area) -> tuple[float, float]:
    c = area.geometry.centroid
    return float(c.y), float(c.x)


def test_two_animals_a_day_in_ten_hectares():
    area = _square("Camp 1", LAT, LON, 10)
    a = _animal("Aldo", *_centre(area), [area])
    b = _animal("Bibi", *_centre(area), [area])
    use = area_use(
        [a, b],
        [area],
        START,
        START + timedelta(days=1),
        "UTC",
        min_absence_s=6 * 3600,
        rest_threshold_h=0,
    )
    f = use.areas[area.id]
    # 144 fixes at ten minutes: the first and last carry half an interval, 23.83 hours each
    assert f["animal_hours"] == pytest.approx(48, rel=0.01)
    assert f["animal_days"] == pytest.approx(2, rel=0.01)
    assert f["animal_days_per_ha"] == pytest.approx(0.2, rel=0.01)
    assert f["animals_used"] == 2 and f["visits"] == 2 and f["use_days"] == 1
    assert f["rest_days"] == 0 and f["relative_pressure"] == 1 and f["pressure_rank"] == 1
    assert f["share_of_herd_time"] == 1
    assert use.herd["tracked_animal_hours"] == pytest.approx(48, rel=0.01)
    assert use.herd["share_inside"] == 1 and use.herd["share_outside"] == 0
    assert len(use.days) == 1 and use.timeline[area.id][0] == pytest.approx(48, rel=0.01)
    assert len(use.animals) == 2 and use.animals[0][0] == "Aldo"


def test_a_silent_day_puts_no_time_anywhere():
    area = _square("Camp 1", LAT, LON, 10)
    a = _animal("Aldo", *_centre(area), [area])  # one day of fixes in a two-day window
    use = area_use(
        [a],
        [area],
        START,
        START + timedelta(days=2),
        "UTC",
        min_absence_s=6 * 3600,
        rest_threshold_h=0,
    )
    f = use.areas[area.id]
    assert f["animal_hours"] < 25
    assert f["use_days"] == 1 and f["rest_days"] == 1 and f["longest_rest_days"] == 1
    assert f["hours_since_last_use"] == pytest.approx(24 + 10 / 60, abs=0.1)


def test_weighting_by_an_attribute_and_by_mass():
    area = _square("Camp 1", LAT, LON, 10)
    a = _animal("Aldo", *_centre(area), [area])
    b = _animal("Bibi", *_centre(area), [area])
    c = _animal("Cato", *_centre(area), [area])
    warnings = weights_of(
        [a, b, c], "attribute", "livestock_unit", {a.subject.id: 2, b.subject.id: 1}
    )
    assert (a.weight, b.weight, c.weight) == (2.0, 1.0, 1.0)
    assert [w.code for w in warnings] == ["weight_missing"] and "Cato" in warnings[0].text
    use = area_use(
        [a, b, c],
        [area],
        START,
        START + timedelta(days=1),
        "UTC",
        min_absence_s=6 * 3600,
        rest_threshold_h=0,
    )
    f = use.areas[area.id]
    assert f["weighted_animal_days_per_ha"] == pytest.approx(
        f["animal_days_per_ha"] * 4 / 3, rel=0.01
    )
    weights_of([a, b], "metabolic", "body_mass_kg", {a.subject.id: 400, b.subject.id: 100})
    assert a.weight == pytest.approx(400**0.75 / ((400**0.75 + 100**0.75) / 2))
    assert a.weight + b.weight == pytest.approx(2)
    assert weights_of([a, b], "equal", None, {}) == []


def test_relative_pressure_averages_to_one_and_rest_days_count():
    camp1 = _square("Camp 1", LAT, LON, 10)
    camp2 = _square("Camp 2", LAT + 0.1, LON, 40)
    a = _animal("Aldo", *_centre(camp1), [camp1, camp2])
    b = _animal("Bibi", *_centre(camp2), [camp1, camp2], hours=12)
    use = area_use(
        [a, b],
        [camp1, camp2],
        START,
        START + timedelta(days=3),
        "UTC",
        min_absence_s=6 * 3600,
        rest_threshold_h=0,
    )
    f1, f2 = use.areas[camp1.id], use.areas[camp2.id]
    assert f1["relative_pressure"] + f2["relative_pressure"] == pytest.approx(2, rel=0.001)
    assert f1["pressure_rank"] == 1 and f2["pressure_rank"] == 2
    assert f1["rest_days"] == 2 and f2["rest_days"] == 2 and f2["longest_rest_days"] == 2
    assert use.herd["share_inside"] == 1
    # a fix inside no area counts outside
    outside = _animal("Dido", LAT + 1, LON, [camp1, camp2], hours=6)
    use2 = area_use(
        [a, outside],
        [camp1, camp2],
        START,
        START + timedelta(days=1),
        "UTC",
        min_absence_s=6 * 3600,
        rest_threshold_h=0,
    )
    assert 0 < use2.herd["share_outside"] < 0.25


def test_visits_split_on_a_long_absence():
    times = np.array([0.0, 600.0, 8 * 3600.0, 8 * 3600.0 + 600.0])
    weights = np.array([300.0, 600.0, 600.0, 300.0])
    visits = _visits(times, weights, 6 * 3600)
    assert len(visits) == 2 and visits[0] == (0.0, 600.0, 900.0)
    assert _visits(np.zeros(0), np.zeros(0), 1) == []


def test_the_module_is_in_the_catalogue():
    import shared.analysis.modules  # noqa: F401
    from shared.analysis import MODULES

    assert MODULES["grazing"].version == "grazing/1"
