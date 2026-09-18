"""The contact tracing module's shaping of what the primitives find (phase 31, task C7).

The primitives are tested on their own in `test_analysis_contacts.py`. What is tested here is
the layer above: which pairs reach the tables, what the network says, which warnings fire, and
above all what the module refuses to claim.
"""

import uuid
from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from shared.analysis.base import Period, Subject
from shared.analysis.modules.contact_tracing import (
    ContactParameters,
    Pair,
    build_document,
    contact_geometries,
    daily_series,
    hour_series,
    median_accuracy_m,
    median_interval_s,
    network_series,
    pair_rows,
    sampling_warnings,
    subject_rows,
)
from shared.analysis.primitives.contacts import Sighting, by_pair, pair_key
from shared.analysis.primitives.proximity import pair_proximity
from shared.analysis.primitives.trajectory import Trajectory, trajectory_from

LAT, LON = 52.53, 4.61
M_PER_DEG_LAT = 111_320.0
START = datetime(2026, 9, 10, 6, 0, tzinfo=UTC)


def _subject(name: str) -> Subject:
    return Subject(id=uuid.uuid4(), name=name, type="Rabbit")


def _track(subject: Subject, metres_north: float, *, n: int = 8, step_s: float = 300.0):
    return trajectory_from(
        subject.id,
        [START.timestamp() + i * step_s for i in range(n)],
        [LAT + metres_north / M_PER_DEG_LAT] * n,
        [LON] * n,
    )


def _params(**over) -> ContactParameters:
    base = {
        "entity_ids": [],
        "time_from": START,
        "time_to": START + timedelta(days=1),
    }
    return ContactParameters(**{**base, **over})


def _pair_from_tracks(a: Subject, b: Subject, metres: float, params: ContactParameters) -> Pair:
    found = pair_proximity(
        _track(a, 0.0),
        _track(b, metres),
        max_distance_m=params.max_distance_m,
        max_time_s=params.max_time_s,
    )
    key = pair_key(a.id, b.id)
    return Pair(a=key[0], b=key[1], period="main", fixes=found)


class TestEvidence:
    def test_a_pair_says_which_kinds_of_evidence_saw_it(self):
        """The most useful column in the table: both kinds is solid, proximity alone rests on
        how often the animals report."""
        a, b = _subject("Anna"), _subject("Bram")
        params = _params()
        pair = _pair_from_tracks(a, b, 20, params)
        assert pair.evidence == "proximity"

        key = pair_key(a.id, b.id)
        heard = by_pair([Sighting(time=START, observer=a.id, seen=b.id, rssi_dbm=-65)])[key]
        pair.sightings = heard
        assert pair.evidence == "bluetooth + proximity"

        alone = Pair(a=key[0], b=key[1], period="main", sightings=heard)
        assert alone.evidence == "bluetooth"

    def test_a_pair_that_met_neither_way_says_none(self):
        a, b = _subject("Anna"), _subject("Bram")
        key = pair_key(a.id, b.id)
        assert Pair(a=key[0], b=key[1], period="main").evidence == "none"

    def test_the_two_kinds_add_up_rather_than_one_hiding_the_other(self):
        a, b = _subject("Anna"), _subject("Bram")
        params = _params()
        pair = _pair_from_tracks(a, b, 20, params)
        by_fixes = pair.contacts
        pair.sightings = by_pair(
            [
                Sighting(time=START + timedelta(days=3), observer=a.id, seen=b.id, rssi_dbm=-70),
            ]
        )[pair_key(a.id, b.id)]
        assert pair.contacts == by_fixes + 1
        assert pair.first_at == START, "the earliest of either kind"
        assert pair.last_at == START + timedelta(days=3), "the latest of either kind"


class TestTables:
    def test_the_pair_table_puts_the_pairs_that_met_most_first(self):
        a, b, c = _subject("Anna"), _subject("Bram"), _subject("Cees")
        params = _params()
        close = _pair_from_tracks(a, b, 10, params)
        brief = Pair(
            a=a.id,
            b=c.id,
            period="main",
            sightings=by_pair([Sighting(time=START, observer=a.id, seen=c.id)])[
                pair_key(a.id, c.id)
            ],
        )
        rows = pair_rows([brief, close], [a, b, c])
        assert rows[0][0] == "Anna · Bram", "the longer meeting leads"
        assert rows[0][4] == "proximity"
        assert rows[1][4] == "bluetooth"

    def test_a_subject_row_counts_the_others_it_met_not_the_meetings(self):
        """Meeting one animal ten times is not the same as meeting ten animals."""
        a, b, c = _subject("Anna"), _subject("Bram"), _subject("Cees")
        params = _params()
        rows = subject_rows(
            [_pair_from_tracks(a, b, 10, params), _pair_from_tracks(a, c, 10, params)],
            [a, b, c],
        )
        anna = next(r for r in rows if r[0] == "Anna")
        assert anna[2] == 2, "Anna met two others"
        assert next(r for r in rows if r[0] == "Bram")[2] == 1

    def test_a_pair_with_no_contacts_is_in_no_subject_row(self):
        a, b = _subject("Anna"), _subject("Bram")
        empty = Pair(a=a.id, b=b.id, period="main")
        assert subject_rows([empty], [a, b]) == []


class TestWarnings:
    def test_a_subject_that_reports_too_seldom_is_named(self):
        """Two animals an hour apart in the record may have been a kilometre apart in between."""
        slow = _subject("Slow")
        tracks = {slow.id: _track(slow, 0.0, n=10, step_s=3600)}
        found = sampling_warnings([slow], tracks, _params(max_time_s=600))
        codes = [w.code for w in found]
        assert "sampling_coarser_than_window" in codes
        named = next(w for w in found if w.code == "sampling_coarser_than_window")
        assert named.subject_id == slow.id
        assert "Slow" in named.text and "60 min" in named.text

    def test_a_subject_that_reports_often_enough_is_not_warned_about(self):
        quick = _subject("Quick")
        tracks = {quick.id: _track(quick, 0.0, n=10, step_s=60)}
        found = sampling_warnings([quick], tracks, _params(max_time_s=600))
        assert "sampling_coarser_than_window" not in [w.code for w in found]

    def test_asking_for_a_distance_inside_the_fixes_own_error_is_a_warning(self):
        vague = _subject("Vague")
        track = _track(vague, 0.0, n=10)
        track.accuracy_m = np.full(10, 150.0)
        found = sampling_warnings([vague], {vague.id: track}, _params(max_distance_m=100))
        assert "distance_within_accuracy" in [w.code for w in found]

    def test_a_network_estimate_is_not_a_fix_and_the_run_says_so(self):
        a = _subject("Anna")
        found = sampling_warnings([a], {a.id: _track(a, 0.0)}, _params())
        notice = next(w for w in found if w.code == "proximity_uses_device_fixes")
        assert notice.level == "notice"
        assert "network estimated" in notice.text

    def test_no_proximity_no_notice_about_fixes(self):
        a = _subject("Anna")
        found = sampling_warnings([a], {a.id: _track(a, 0.0)}, _params(proximity=False))
        assert "proximity_uses_device_fixes" not in [w.code for w in found]

    def test_an_empty_track_warns_about_nothing(self):
        a = _subject("Anna")
        empty = trajectory_from(a.id, [], [], [])
        found = sampling_warnings([a], {a.id: empty}, _params(proximity=False))
        assert found == []


class TestCharts:
    def test_the_network_carries_nodes_and_edges_not_points(self):
        a, b, c = _subject("Anna"), _subject("Bram"), _subject("Cees")
        params = _params()
        pairs = [_pair_from_tracks(a, b, 10, params)]
        series = network_series(pairs, [a, b, c])[0]
        assert {n["name"] for n in series["nodes"]} == {"Anna", "Bram", "Cees"}
        assert len(series["edges"]) == 1
        lonely = next(n for n in series["nodes"] if n["name"] == "Cees")
        assert lonely["contacts"] == 0, "a subject that met nobody is still on the network"

    def test_the_hour_rose_has_a_slot_for_every_hour(self):
        a, b = _subject("Anna"), _subject("Bram")
        pairs = [_pair_from_tracks(a, b, 10, _params())]
        points = hour_series(pairs)[0]["points"]
        assert len(points) == 24
        assert sum(n for _, n in points) == 1
        assert points[START.hour][1] == 1

    def test_contacts_per_day_is_dated_and_ordered(self):
        a, b = _subject("Anna"), _subject("Bram")
        key = pair_key(a.id, b.id)
        sightings = by_pair(
            [
                Sighting(time=START, observer=a.id, seen=b.id),
                Sighting(time=START + timedelta(days=2), observer=a.id, seen=b.id),
            ]
        )[key]
        points = daily_series([Pair(a=key[0], b=key[1], period="main", sightings=sightings)])[0][
            "points"
        ]
        assert [d for d, _ in points] == ["2026-09-10", "2026-09-12"]


class TestGeometry:
    def test_a_contact_is_placed_between_the_two_animals_not_on_one(self):
        """Neither of them is the place; the meeting is, and it was somewhere between them."""
        a, b = _subject("Anna"), _subject("Bram")
        params = _params()
        pair = _pair_from_tracks(a, b, 40, params)
        pair.places = [(LAT, LON), (LAT + 40 / M_PER_DEG_LAT, LON)]
        found = contact_geometries([pair], [a, b])
        assert len(found) == 1
        assert found[0].kind == "contact"
        lon, lat = found[0].geojson["coordinates"]
        assert lat == pytest.approx(LAT + 20 / M_PER_DEG_LAT, abs=1e-6)
        assert lon == pytest.approx(LON, abs=1e-6)
        assert found[0].properties["evidence"] == "proximity"

    def test_a_pair_with_nowhere_to_put_it_yields_no_point(self):
        a, b = _subject("Anna"), _subject("Bram")
        key = pair_key(a.id, b.id)
        heard = by_pair([Sighting(time=START, observer=a.id, seen=b.id)])[key]
        pair = Pair(a=key[0], b=key[1], period="main", sightings=heard)
        assert contact_geometries([pair], [a, b]) == []


class TestDocument:
    def _document(self, **over):
        a, b, c = _subject("Anna"), _subject("Bram"), _subject("Cees")
        params = _params()
        pairs = [_pair_from_tracks(a, b, 10, params)]
        return (
            build_document(
                [a, b, c],
                [Period(key="main", time_from=START, time_to=START + timedelta(days=1))],
                pairs,
                params,
                warnings=[],
                input_count=over.get("input_count", 100),
                excluded_count=over.get("excluded_count", 0),
                unknown=over.get("unknown", 0),
                ambiguous=over.get("ambiguous", 0),
            ),
            [a, b, c],
        )

    def test_the_summary_counts_the_pairs_that_met_against_the_pairs_that_could_have(self):
        document, _ = self._document()
        assert document.summary["pairs_met"] == 1
        assert document.summary["pairs_possible"] == 3, "three subjects make three pairs"

    def test_what_was_set_aside_is_reported_and_not_quietly_dropped(self):
        """An unknown neighbour is a finding (D253) and an ambiguous one is in no pair figure
        (D254). Either way the reader is told how many."""
        document, _ = self._document(unknown=17, ambiguous=4)
        assert document.summary["unknown_sightings"] == 17
        assert document.summary["ambiguous_sightings"] == 4

    def test_the_limitations_say_it_infers_no_transmission(self):
        document, _ = self._document()
        text = " ".join(document.summary["limitations"])
        assert "infers no transmission" in text
        assert "never converted to metres" in text

    def test_the_provenance_names_both_sources(self):
        document, _ = self._document()
        assert set(document.provenance.sources) == {"device_contacts", "positions"}
        assert document.provenance.method_version == "contact_tracing/1"
        assert document.provenance.parameters["max_distance_m"] == 100

    def test_the_document_carries_the_three_charts(self):
        document, _ = self._document()
        assert [c.key for c in document.charts] == [
            "contacts_per_day",
            "contacts_by_hour",
            "network",
        ]
        assert next(c for c in document.charts if c.key == "network").kind == "network"


def test_the_observed_interval_is_what_the_subject_actually_did():
    a = _subject("Anna")
    assert median_interval_s(_track(a, 0.0, n=10, step_s=300)) == pytest.approx(300)
    assert median_interval_s(trajectory_from(a.id, [0.0, 1.0], [LAT, LAT], [LON, LON])) is None


def test_accuracy_ignores_the_fixes_that_claim_none():
    a = _subject("Anna")
    track: Trajectory = _track(a, 0.0, n=4)
    track.accuracy_m = np.array([10.0, np.nan, 30.0, np.nan])
    assert median_accuracy_m(track) == pytest.approx(20)
    blank: Trajectory = _track(a, 0.0, n=3)
    assert median_accuracy_m(blank) is None
