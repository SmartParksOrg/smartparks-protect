"""The cache of environmental layer samples (decision D245), reviewed on 2026-09-18: which
weeks it keeps, which it asks the provider for again, and what it refuses to guess."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from shared.analysis.environment import LayerSample, sample_weekly

pytestmark = pytest.mark.asyncio

AREA_A = {
    "type": "Polygon",
    "coordinates": [
        [[16.70, -20.85], [16.72, -20.85], [16.72, -20.83], [16.70, -20.83], [16.70, -20.85]]
    ],
}
AREA_B = {
    "type": "Polygon",
    "coordinates": [
        [[16.74, -20.86], [16.76, -20.86], [16.76, -20.84], [16.74, -20.84], [16.74, -20.86]]
    ],
}


class FakeProvider:
    """Answers every week it is asked for with one value per geometry, and remembers the asks."""

    key = "fake"
    layers = ("ndvi",)

    def __init__(self, value: float = 0.5, series_count: int | None = None) -> None:
        self.value = value
        self.series_count = series_count
        self.asks: list[tuple[datetime, datetime]] = []

    async def sample(self, layer, geometries, time_from, time_to, project_id):
        self.asks.append((time_from, time_to))
        count = self.series_count if self.series_count is not None else len(geometries)
        week = time_from
        weeks = []
        while week < time_to:
            weeks.append(week)
            week += timedelta(days=7)
        return LayerSample(
            layer=layer,
            source="fake",
            sampled_at=datetime.now(UTC),
            series=[[(w, self.value) for w in weeks] for _ in range(count)],
        )


async def test_only_the_missing_weeks_are_asked_for_again(db):
    """Tim, 2026-09-18: the vegetation layer is the slow part of a run. A second run over a
    period that overlaps the first asks only for the weeks the cache does not hold."""
    project = uuid.uuid4()
    provider = FakeProvider()
    first_from = datetime(2026, 6, 1, tzinfo=UTC)
    first_to = datetime(2026, 6, 29, tzinfo=UTC)
    first = await sample_weekly(
        db, provider, "ndvi", [AREA_A, AREA_B], first_from, first_to, project
    )
    await db.commit()
    assert len(provider.asks) == 1
    assert len(first) == 2 and all(len(series) == 4 for series in first.values())

    # the same period again touches the provider not at all
    await sample_weekly(db, provider, "ndvi", [AREA_A, AREA_B], first_from, first_to, project)
    assert len(provider.asks) == 1

    # a period that reaches two weeks further asks for those two weeks only
    later = await sample_weekly(
        db,
        provider,
        "ndvi",
        [AREA_A, AREA_B],
        first_from,
        datetime(2026, 7, 13, tzinfo=UTC),
        project,
    )
    await db.commit()
    assert len(provider.asks) == 2
    asked_from, asked_to = provider.asks[1]
    assert asked_from == datetime(2026, 6, 29, tzinfo=UTC)
    assert asked_to == datetime(2026, 7, 13, tzinfo=UTC)
    # the weeks from the cache are still there beside the new ones
    assert len(later[next(iter(later))]) == 6


async def test_a_week_that_has_not_ended_is_not_cached(db):
    """A week still running may still gain a cloud-free pass, so nothing is kept for it and the
    next run asks again; the weeks before it are kept."""
    project = uuid.uuid4()
    provider = FakeProvider()
    now = datetime.now(UTC)
    time_from = now - timedelta(days=21)
    await sample_weekly(db, provider, "ndvi", [AREA_A], time_from, now, project)
    await db.commit()
    assert len(provider.asks) == 1

    await sample_weekly(db, provider, "ndvi", [AREA_A], time_from, now, project)
    assert len(provider.asks) == 2, "the running week is asked for again"
    # and only that week, not the whole span
    asked_from, _ = provider.asks[1]
    assert asked_from >= now - timedelta(days=7)


async def test_a_provider_that_answers_the_wrong_number_of_series_is_refused(db):
    """The series come back in the order the geometries were asked for; a different count means
    the module cannot tell which area a value belongs to, so it fails rather than guess."""
    project = uuid.uuid4()
    provider = FakeProvider(series_count=1)
    with pytest.raises(ValueError, match="cannot tell which"):
        await sample_weekly(
            db,
            provider,
            "ndvi",
            [AREA_A, AREA_B],
            datetime(2026, 5, 4, tzinfo=UTC),
            datetime(2026, 5, 18, tzinfo=UTC),
            project,
        )


async def test_an_empty_period_asks_nothing(db):
    provider = FakeProvider()
    moment = datetime(2026, 5, 4, tzinfo=UTC)
    out = await sample_weekly(db, provider, "ndvi", [AREA_A], moment, moment, uuid.uuid4())
    assert out and all(series == {} for series in out.values())
    assert provider.asks == []
