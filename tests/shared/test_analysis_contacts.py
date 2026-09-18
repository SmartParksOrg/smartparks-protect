"""The contact tracing primitives on synthetic tracks and sightings (phase 31, task C6).

Two kinds of evidence, tested apart because they fail in different ways. Proximity is an
inference from two sets of fixes that do not line up, so its tests are about what it refuses to
claim. Sightings are observations, so their tests are about not losing what was observed.
"""

import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from shared.analysis.primitives.contacts import (
    BANDS,
    Sighting,
    band_of,
    by_pair,
    meetings_of,
    pair_key,
)
from shared.analysis.primitives.proximity import (
    distance_is_within_accuracy,
    pair_proximity,
    sampling_is_coarser_than,
)
from shared.analysis.primitives.trajectory import trajectory_from

LAT, LON = 52.53, 4.61
M_PER_DEG_LAT = 111_320.0
START = datetime(2026, 9, 10, 6, 0, tzinfo=UTC)


def _north(metres: float) -> float:
    return LAT + metres / M_PER_DEG_LAT


def _track(offsets_m, *, step_s: float = 300.0, start_s: float = 0.0, n: int | None = None):
    """A track standing still at `offsets_m` metres north of the origin, one fix per step."""
    offsets = list(offsets_m) if n is None else [offsets_m] * n
    return trajectory_from(
        uuid.uuid4(),
        [START.timestamp() + start_s + i * step_s for i in range(len(offsets))],
        [_north(m) for m in offsets],
        [LON] * len(offsets),
    )


class TestProximity:
    def test_two_tracks_side_by_side_are_one_encounter_not_many(self):
        """Two animals standing together for an hour report a dozen fixes each. That is one
        meeting; counting the fixes would say the herd is a dozen times as sociable."""
        a = _track(0.0, n=12)
        b = _track(20.0, n=12)
        found = pair_proximity(a, b, max_distance_m=100, max_time_s=600)
        assert found.contacts == 1
        assert found.encounters[0].samples == 12
        assert found.seconds == pytest.approx(11 * 300)
        assert found.closest_m == pytest.approx(20, abs=2)

    def test_a_silence_ends_an_encounter(self):
        """Nothing was observed across a gap in reporting, so nothing is claimed across it: two
        runs of fixes with a hole between them are two meetings, not one long one."""
        a = trajectory_from(
            uuid.uuid4(),
            [START.timestamp() + t for t in (0, 300, 600, 900, 20_000, 20_300)],
            [_north(0)] * 6,
            [LON] * 6,
        )
        b = trajectory_from(
            uuid.uuid4(),
            [START.timestamp() + t for t in (0, 300, 600, 900, 20_000, 20_300)],
            [_north(10)] * 6,
            [LON] * 6,
        )
        found = pair_proximity(a, b, max_distance_m=100, max_time_s=600)
        assert found.contacts == 2, "the hole in the middle is not a meeting"
        assert [e.samples for e in found.encounters] == [4, 2]

    def test_far_apart_is_no_contact_however_long_they_report(self):
        a = _track(0.0, n=20)
        b = _track(5000.0, n=20)
        found = pair_proximity(a, b, max_distance_m=100, max_time_s=600)
        assert found.contacts == 0
        assert found.compared == 20, "they were compared and found apart, which is not nothing"

    def test_fixes_too_far_apart_in_time_are_not_compared_at_all(self):
        """The pair was not observed together; that is different from being observed apart."""
        a = _track(0.0, n=5, step_s=300)
        b = _track(0.0, n=5, step_s=300, start_s=10_000)
        found = pair_proximity(a, b, max_distance_m=100, max_time_s=600)
        assert found.contacts == 0
        assert found.compared == 0
        assert found.unpaired == 5

    def test_the_nearest_fix_in_time_is_the_one_judged(self):
        """Of two candidates the closer in time is the better evidence, and which came first
        must not decide the answer."""
        a = trajectory_from(uuid.uuid4(), [START.timestamp() + 500], [_north(0)], [LON])
        # 100 s earlier and far; 400 s later and near. The earlier one is nearer in time.
        b = trajectory_from(
            uuid.uuid4(),
            [START.timestamp() + 400, START.timestamp() + 900],
            [_north(5000), _north(5)],
            [LON, LON],
        )
        found = pair_proximity(a, b, max_distance_m=100, max_time_s=600)
        assert found.contacts == 0, "the nearest fix in time was the far one"

    def test_an_empty_track_yields_nothing_rather_than_failing(self):
        a = _track(0.0, n=5)
        b = trajectory_from(uuid.uuid4(), [], [], [])
        assert pair_proximity(a, b, max_distance_m=100, max_time_s=600).contacts == 0

    def test_a_single_passing_sample_can_be_dropped_by_the_minimum(self):
        """One sample is a moment, not a duration, so it counts as zero seconds and a run that
        asks for a minimum duration leaves it out."""
        a = trajectory_from(
            uuid.uuid4(),
            [START.timestamp() + t for t in (0, 300, 600)],
            [_north(5000), _north(0), _north(5000)],
            [LON] * 3,
        )
        b = _track(0.0, n=3)
        loose = pair_proximity(a, b, max_distance_m=100, max_time_s=600)
        assert loose.contacts == 1 and loose.seconds == 0
        strict = pair_proximity(a, b, max_distance_m=100, max_time_s=600, min_contact_s=60)
        assert strict.contacts == 0

    def test_the_widest_pairing_gap_is_reported(self):
        """How far apart in time the two fixes of a proximity were is the reader's measure of
        how much the finding rests on sampling."""
        a = _track(0.0, n=3, step_s=300)
        b = _track(10.0, n=3, step_s=300, start_s=120)
        found = pair_proximity(a, b, max_distance_m=100, max_time_s=600)
        assert found.contacts == 1
        assert found.worst_pairing_s == pytest.approx(120)

    def test_the_sweep_does_not_cost_the_product_of_the_tracks(self):
        """A week of five-minute fixes each is two thousand against two thousand. The sweep
        walks them; a cross product would be four million distances."""
        long_a = _track(0.0, n=2000, step_s=300)
        long_b = _track(30.0, n=2000, step_s=300)
        found = pair_proximity(long_a, long_b, max_distance_m=100, max_time_s=600)
        assert found.compared == 2000
        assert found.contacts == 1

    def test_the_warnings_say_when_the_figures_would_mislead(self):
        assert sampling_is_coarser_than(3600, 600) is True, "an hour apart, judged in ten minutes"
        assert sampling_is_coarser_than(300, 600) is False
        assert sampling_is_coarser_than(None, 600) is False, "unknown is not a warning"
        assert distance_is_within_accuracy(100, 120) is True, "the receiver alone could do it"
        assert distance_is_within_accuracy(100, 10) is False
        assert distance_is_within_accuracy(100, None) is False


class TestSightings:
    def _sighting(self, observer, seen, minutes, rssi=-70):
        return Sighting(
            time=START + timedelta(minutes=minutes), observer=observer, seen=seen, rssi_dbm=rssi
        )

    def test_a_pair_is_named_the_same_way_whichever_heard_the_other(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        assert pair_key(a, b) == pair_key(b, a)

    def test_sightings_close_in_time_are_one_meeting(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        rows = [self._sighting(a, b, m) for m in (0, 5, 10, 15)]
        meetings = meetings_of(rows)
        assert len(meetings) == 1
        assert meetings[0].sightings == 4
        assert meetings[0].seconds == pytest.approx(15 * 60)

    def test_a_long_silence_makes_two_meetings(self):
        """A tag heard every five minutes for a week is not one contact lasting seven days."""
        a, b = uuid.uuid4(), uuid.uuid4()
        rows = [self._sighting(a, b, m) for m in (0, 5, 10, 600, 605)]
        assert len(meetings_of(rows, gap_s=900)) == 2

    def test_the_strongest_signal_of_a_meeting_is_kept_and_banded(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        rows = [
            self._sighting(a, b, 0, rssi=-95),
            self._sighting(a, b, 5, rssi=-62),
            self._sighting(a, b, 10, rssi=-88),
        ]
        meeting = meetings_of(rows)[0]
        assert meeting.strongest_dbm == -62
        assert meeting.band == "near"

    def test_a_band_is_all_a_signal_can_honestly_say(self):
        assert band_of(-55) == "near"
        assert band_of(-80) == "middling"
        assert band_of(-100) == "far"
        assert band_of(None) is None
        assert [name for name, _ in BANDS] == ["near", "middling", "far"]

    def test_heard_both_ways_is_stronger_evidence_and_is_recorded(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        one_way = by_pair([self._sighting(a, b, 0), self._sighting(a, b, 5)])
        assert one_way[pair_key(a, b)].mutual is False
        both = by_pair([self._sighting(a, b, 0), self._sighting(b, a, 5)])
        assert both[pair_key(a, b)].mutual is True, "each heard the other"
        assert both[pair_key(a, b)].contacts == 1, "still one meeting between the same two"

    def test_a_signal_floor_drops_sightings_and_says_how_many(self):
        """Dropping them silently would read as "they never met" (decision D253's spirit)."""
        a, b = uuid.uuid4(), uuid.uuid4()
        rows = [self._sighting(a, b, 0, rssi=-95), self._sighting(a, b, 5, rssi=-60)]
        pair = by_pair(rows, min_rssi_dbm=-80)[pair_key(a, b)]
        assert pair.sightings == 1
        assert pair.below_floor == 1

    def test_a_pair_whose_every_sighting_was_dropped_is_still_named(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        pair = by_pair([self._sighting(a, b, 0, rssi=-95)], min_rssi_dbm=-80)[pair_key(a, b)]
        assert pair.contacts == 0 and pair.below_floor == 1

    def test_a_sighting_without_a_signal_is_kept(self):
        """Not every driver reports RSSI, and a sighting is a sighting."""
        a, b = uuid.uuid4(), uuid.uuid4()
        rows = [Sighting(time=START, observer=a, seen=b)]
        pair = by_pair(rows, min_rssi_dbm=-80)[pair_key(a, b)]
        assert pair.contacts == 1 and pair.strongest_dbm is None

    def test_an_aggregated_sighting_carries_its_own_count(self):
        """A port 7 message says how often it saw a neighbour in the window; that count is the
        evidence, not the one row that carried it."""
        a, b = uuid.uuid4(), uuid.uuid4()
        rows = [Sighting(time=START, observer=a, seen=b, rssi_dbm=-70, sightings=9)]
        assert by_pair(rows)[pair_key(a, b)].sightings == 9

    def test_first_and_last_span_every_meeting(self):
        a, b = uuid.uuid4(), uuid.uuid4()
        rows = [self._sighting(a, b, m) for m in (0, 5, 600, 605)]
        pair = by_pair(rows)[pair_key(a, b)]
        assert pair.first_at == START
        assert pair.last_at == START + timedelta(minutes=605)
        assert pair.contacts == 2


def test_the_two_kinds_of_evidence_agree_on_a_pair_that_was_really_together():
    """The point of carrying both (decision D255): a pair seen by fixes and by sightings should
    come out of each with the same story, and a reader can hold them against each other."""
    a_id, b_id = uuid.uuid4(), uuid.uuid4()
    a = _track(0.0, n=8, step_s=300)
    b = _track(15.0, n=8, step_s=300)
    by_fixes = pair_proximity(a, b, max_distance_m=100, max_time_s=600)

    sightings = [
        Sighting(time=START + timedelta(seconds=i * 300), observer=a_id, seen=b_id, rssi_dbm=-65)
        for i in range(8)
    ]
    by_sighting = by_pair(sightings)[pair_key(a_id, b_id)]

    assert by_fixes.contacts == by_sighting.contacts == 1
    assert by_fixes.seconds == pytest.approx(by_sighting.seconds)
    assert np.isclose(by_fixes.closest_m, 15, atol=2)
    assert by_sighting.band == "near"
