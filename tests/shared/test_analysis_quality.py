"""The quality warnings say what the fixes allow."""

import uuid

from shared.analysis.primitives.trajectory import steps, trajectory_from
from shared.analysis.quality import quality_report

LAT, LON = 52.09, 5.36


def _regular(n: int, step_s: float):
    return trajectory_from(
        uuid.uuid4(),
        [i * step_s for i in range(n)],
        [LAT] * n,
        [LON + i * 0.0001 for i in range(n)],
    )


def test_few_fixes_is_the_only_word_when_there_are_few():
    track = _regular(5, 600)
    warnings, figures = quality_report(
        track, steps(track, 3600), subject_id=track.entity_id, window_seconds=86_400, excluded=0
    )
    assert [w.code for w in warnings] == ["few_fixes"] and figures["fixes"] == 5


def test_missing_and_gaps_are_measured_against_the_window():
    # a fix every 10 minutes for 12 hours, in a 24 hour window: half the expected fixes
    track = _regular(73, 600)
    warnings, figures = quality_report(
        track, steps(track, 3600), subject_id=track.entity_id, window_seconds=86_400, excluded=2
    )
    codes = {w.code for w in warnings}
    assert "missing_fixes" in codes and figures["missing_share"] > 0.4
    assert "impossible_speed" in codes
    assert "gaps" not in codes


def test_a_long_gap_warns():
    times = [i * 600 for i in range(40)] + [3 * 86_400 + i * 600 for i in range(40)]
    track = trajectory_from(uuid.uuid4(), times, [LAT] * 80, [LON] * 80)
    warnings, figures = quality_report(
        track, steps(track, 3600), subject_id=track.entity_id, window_seconds=4 * 86_400, excluded=0
    )
    assert any(w.code == "gaps" for w in warnings) and figures["gap_share"] > 0.5
