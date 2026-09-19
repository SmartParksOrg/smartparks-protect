"""A fence line's status from its monitors (phase 32, decisions D263 to D265), on known
shapes: the levels a reading gives, the place of a monitor along the line, the sections a set
of monitors cuts the line into, and what changed."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from shared.domain.fence import (
    MonitorReading,
    Section,
    Thresholds,
    along_line,
    changed_sections,
    line_length_m,
    line_level,
    monitor_level,
    sections_of,
    status_title,
)

NOW = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)
T = Thresholds()
#: A fence running east for about a kilometre at 52.5 north, then north for half of one.
LINE = [[4.6000, 52.5000], [4.6147, 52.5000], [4.6147, 52.5045]]


def _reading(name: str, position_m: float | None, level: str = "ok") -> MonitorReading:
    return MonitorReading(uuid.uuid4(), name, position_m, level=level)


class TestMonitorLevel:
    def test_a_good_reading_is_ok(self):
        assert monitor_level(6500, 5, False, NOW - timedelta(seconds=30), NOW, T) == "ok"

    def test_under_the_ok_threshold_is_low(self):
        assert monitor_level(3200, 5, False, NOW, NOW, T) == "low"

    def test_under_the_down_threshold_is_down(self):
        assert monitor_level(900, 5, False, NOW, NOW, T) == "down"

    def test_no_pulses_is_down_whatever_the_voltage_reads(self):
        assert monitor_level(6500, 0, False, NOW, NOW, T) == "down"

    def test_a_failed_measurement_is_unknown(self):
        assert monitor_level(6500, 5, True, NOW, NOW, T) == "unknown"

    def test_a_stale_reading_is_unknown(self):
        old = NOW - timedelta(seconds=3 * T.interval_s)
        assert monitor_level(6500, 5, False, old, NOW, T) == "unknown"

    def test_nothing_measured_is_unknown(self):
        assert monitor_level(None, None, False, None, NOW, T) == "unknown"

    def test_the_thresholds_come_from_the_line_with_defaults(self):
        assert Thresholds.of({"fence": {"ok_v": 5000, "down_v": 1500}}) == Thresholds(
            5000, 1500, 60
        )
        assert Thresholds.of({}) == Thresholds()
        assert Thresholds.of({"fence": {"ok_v": "nonsense", "interval_s": -1}}) == Thresholds()


class TestAlongTheLine:
    def test_the_line_has_its_length(self):
        assert line_length_m(LINE) == pytest.approx(1500, rel=0.02)

    def test_a_monitor_beside_the_first_stretch_projects_onto_it(self):
        # a little south of the line, a third of the way east
        metres = along_line(LINE, 4.6049, 52.4998)
        assert metres == pytest.approx(333, rel=0.05)

    def test_a_monitor_past_the_corner_lands_on_the_second_stretch(self):
        metres = along_line(LINE, 4.6150, 52.5030)
        assert metres == pytest.approx(1000 + 333, rel=0.05)

    def test_a_monitor_before_the_start_sits_at_the_start(self):
        assert along_line(LINE, 4.5900, 52.5000) == 0.0


class TestSections:
    def test_no_monitor_is_one_unknown_section(self):
        assert sections_of(1500, []) == [Section(0.0, 1500, "unknown")]

    def test_one_monitor_colours_the_whole_line(self):
        only = _reading("A", 700, "low")
        assert sections_of(1500, [only]) == [Section(0.0, 1500, "low", [only.entity_id])]

    def test_two_monitors_cut_the_line_in_three_and_the_middle_reads_the_worse(self):
        a, b = _reading("A", 400, "ok"), _reading("B", 1100, "down")
        found = sections_of(1500, [b, a])  # any order in
        assert [(s.from_m, s.to_m, s.level) for s in found] == [
            (0.0, 400, "ok"),
            (400, 1100, "down"),
            (1100, 1500, "down"),
        ]
        assert found[1].monitor_ids == [a.entity_id, b.entity_id]

    def test_a_monitor_without_a_place_takes_no_part(self):
        a, lost = _reading("A", 400, "ok"), _reading("Lost", None, "down")
        assert [s.level for s in sections_of(1500, [a, lost])] == ["ok"]

    def test_the_line_reads_its_worst_section(self):
        assert line_level([Section(0, 1, "ok"), Section(1, 2, "low")]) == "low"
        assert line_level([Section(0, 1, "ok"), Section(1, 2, "unknown")]) == "unknown"
        assert line_level([Section(0, 1, "low"), Section(1, 2, "down")]) == "down"
        assert line_level([]) == "unknown"

    def test_only_the_sections_whose_level_moved_count_as_changed(self):
        before = [
            {"from_m": 0.0, "to_m": 400.0, "level": "ok"},
            {"from_m": 400.0, "to_m": 1100.0, "level": "ok"},
        ]
        after = [Section(0.0, 400.0, "ok"), Section(400.0, 1100.0, "low")]
        assert changed_sections(before, after) == [after[1]]
        assert changed_sections([], after) == after


def test_the_title_names_the_stretch_when_one_section_changed():
    a, b = _reading("North gate", 400), _reading("Corner", 1100)
    changed = [Section(400, 1100, "down", [a.entity_id, b.entity_id])]
    assert status_title("East fence", changed, [a, b]) == (
        "Fence East fence reads down near North gate to Corner"
    )
    assert status_title("East fence", [Section(0, 1, "ok"), Section(1, 2, "ok")], [a]) == (
        "Fence East fence reads live"
    )
    # the stretch that reported is live even while the line as a whole is not known yet
    assert status_title("East fence", [Section(0, 400, "ok", [a.entity_id])], [a, b]) == (
        "Fence East fence reads live near North gate"
    )


def test_a_point_along_the_line_walks_its_vertices():
    from shared.domain.fence import point_along

    lon, lat = point_along(LINE, 500)
    assert lat == pytest.approx(52.5, abs=1e-6) and 4.6 < lon < 4.6147
    lon, lat = point_along(LINE, 1250)
    assert lon == pytest.approx(4.6147, abs=1e-6) and 52.5 < lat < 52.5045
    assert point_along(LINE, 99_999) == (4.6147, 52.5045)
