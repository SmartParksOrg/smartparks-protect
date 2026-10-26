"""Assignment boundaries moved after the fact (decisions D355 to D358): the pure rules of
`shared/domain/boundaries.py`, on the timeline of SP051307 as it stood on dev on
2026-10-26: one project and one entity row ending at the transfer's instant, the next ones
starting there, and the intended boundary a day earlier."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from shared.domain.boundaries import (
    CROSSES,
    EMPTY,
    FUTURE,
    NEXT_EMPTY,
    OUTSIDE_PROJECT,
    PREVIOUS_EMPTY,
    REFUSALS,
    Bounds,
    EdgeChange,
    apply_changes,
    entity_rows_covered,
    merge,
    move_edge,
    nearest_edge,
    plan_row,
)
from shared.i18n.nl import NL

JOINED = datetime(2026, 7, 16, 12, 53, 20, tzinfo=UTC)
TRANSFER = datetime(2026, 10, 26, 15, 21, 13, 517796, tzinfo=UTC)
BOUNDARY = datetime(2026, 10, 25, 14, 13, 52, tzinfo=UTC)
NOW = datetime(2026, 10, 30, 17, 0, tzinfo=UTC)

SMART_PARKS, LP0 = uuid.uuid4(), uuid.uuid4()
OLD_ROW, NEW_ROW = uuid.uuid4(), uuid.uuid4()


def timeline() -> list[Bounds]:
    return [
        Bounds(OLD_ROW, SMART_PARKS, JOINED, TRANSFER),
        Bounds(NEW_ROW, LP0, TRANSFER, None),
    ]


def test_moving_a_start_earlier_takes_the_neighbours_end_along():
    plan = move_edge("project", timeline(), NEW_ROW, "start", BOUNDARY, NOW)
    assert plan.ok and plan.gap is None
    assert plan.changes == [
        EdgeChange(NEW_ROW, LP0, "start", TRANSFER, BOUNDARY),
        EdgeChange(OLD_ROW, SMART_PARKS, "end", TRANSFER, BOUNDARY),
    ]
    assert plan.window == (BOUNDARY, TRANSFER)
    after = apply_changes(timeline(), plan.changes)
    assert after[0].end == BOUNDARY and after[1].start == BOUNDARY


def test_moving_the_end_of_the_previous_row_is_the_same_move():
    plan = move_edge("project", timeline(), OLD_ROW, "end", BOUNDARY, NOW)
    assert plan.ok
    assert {(c.assignment_id, c.edge) for c in plan.changes} == {
        (OLD_ROW, "end"),
        (NEW_ROW, "start"),
    }
    assert plan.window == (BOUNDARY, TRANSFER)


def test_a_boundary_moved_later_has_the_window_the_other_way_round():
    later = TRANSFER + timedelta(hours=1)
    plan = move_edge("project", timeline(), NEW_ROW, "start", later, NOW)
    assert plan.ok and plan.window == (TRANSFER, later)


def test_the_future_an_empty_row_and_an_emptied_neighbour_are_refused():
    assert (
        move_edge("project", timeline(), NEW_ROW, "start", NOW + timedelta(seconds=1), NOW).refused
        == FUTURE
    )
    # the new row's start moved before the old row's start would leave the old row empty
    assert move_edge("project", timeline(), NEW_ROW, "start", JOINED, NOW).refused == PREVIOUS_EMPTY
    # the old row's end moved to its own start leaves it empty
    assert move_edge("project", timeline(), OLD_ROW, "end", JOINED, NOW).refused == EMPTY
    # the old row's end moved past the next row's end would empty the next row
    rows = [
        Bounds(OLD_ROW, SMART_PARKS, JOINED, TRANSFER),
        Bounds(NEW_ROW, LP0, TRANSFER, NOW - timedelta(hours=1)),
    ]
    assert move_edge("project", rows, OLD_ROW, "end", NOW, NOW).refused == NEXT_EMPTY


def test_a_boundary_nothing_touches_moves_alone_and_names_the_gap():
    gap_start = TRANSFER + timedelta(days=1)
    rows = [Bounds(OLD_ROW, SMART_PARKS, JOINED, TRANSFER), Bounds(NEW_ROW, LP0, gap_start, None)]
    # the new row's start moved earlier into the gap closes part of it, alone
    plan = move_edge("project", rows, NEW_ROW, "start", TRANSFER + timedelta(hours=12), NOW)
    assert plan.ok and plan.gap == "closes" and len(plan.changes) == 1
    # moved earlier than the gap it would cross the old row
    assert move_edge("project", rows, NEW_ROW, "start", BOUNDARY, NOW).refused == CROSSES
    # the old row's end moved earlier opens more unassigned time
    plan = move_edge("project", rows, OLD_ROW, "end", BOUNDARY, NOW)
    assert (
        plan.ok
        and plan.gap == "opens"
        and plan.changes == [EdgeChange(OLD_ROW, SMART_PARKS, "end", TRANSFER, BOUNDARY)]
    )


def test_ending_an_open_row_counts_from_now():
    rows = [Bounds(NEW_ROW, LP0, JOINED, None)]
    plan = move_edge("project", rows, NEW_ROW, "end", BOUNDARY, NOW)
    assert plan.ok and plan.gap == "opens"
    assert plan.changes == [EdgeChange(NEW_ROW, LP0, "end", None, BOUNDARY)]
    assert plan.window == (BOUNDARY, NOW)
    assert plan.changes[0].shrinks


def test_the_same_instant_changes_nothing():
    plan = move_edge("project", timeline(), NEW_ROW, "start", TRANSFER, NOW)
    assert plan.ok and plan.changes == [] and plan.window is None


def test_plan_row_moves_both_edges_with_their_neighbours():
    third = uuid.uuid4()
    middle_end = TRANSFER + timedelta(days=1)
    rows = [
        Bounds(OLD_ROW, SMART_PARKS, JOINED, TRANSFER),
        Bounds(NEW_ROW, LP0, TRANSFER, middle_end),
        Bounds(third, SMART_PARKS, middle_end, None),
    ]
    new_end = middle_end - timedelta(hours=2)
    plan = plan_row("project", rows, NEW_ROW, new_from=BOUNDARY, new_to=new_end, now=NOW)
    assert plan.ok
    assert len(plan.changes) == 4
    assert plan.window == (BOUNDARY, middle_end)
    after = apply_changes(rows, plan.changes)
    assert [(r.start, r.end) for r in after] == [
        (JOINED, BOUNDARY),
        (BOUNDARY, new_end),
        (new_end, None),
    ]
    refused = plan_row("project", rows, NEW_ROW, new_from=BOUNDARY, new_to=JOINED, now=NOW)
    assert refused.refused == EMPTY


def test_merge_keeps_the_first_refusal_and_widens_the_window():
    first = move_edge("project", timeline(), NEW_ROW, "start", BOUNDARY, NOW)
    second = move_edge("project", timeline(), NEW_ROW, "start", TRANSFER + timedelta(hours=1), NOW)
    merged = merge(first, second)
    assert merged.ok and merged.window == (BOUNDARY, TRANSFER + timedelta(hours=1))
    refused = move_edge("project", timeline(), NEW_ROW, "start", NOW + timedelta(days=1), NOW)
    assert merge(first, refused).refused == FUTURE
    assert merge(refused, first).refused == FUTURE


def test_the_nearest_edge_is_the_boundary_a_person_means():
    old, new = timeline()
    assert nearest_edge(new, BOUNDARY, NOW) == "start"
    assert nearest_edge(old, BOUNDARY, NOW) == "end"
    assert nearest_edge(old, JOINED + timedelta(minutes=5), NOW) == "start"


def test_an_entity_row_must_lie_inside_a_project_row_of_its_project():
    tim, sp051307 = uuid.uuid4(), uuid.uuid4()
    projects = apply_changes(
        timeline(), move_edge("project", timeline(), NEW_ROW, "start", BOUNDARY, NOW).changes
    )
    entity_rows = [
        Bounds(uuid.uuid4(), tim, JOINED, BOUNDARY),
        Bounds(uuid.uuid4(), sp051307, BOUNDARY, None),
    ]
    owners = {tim: SMART_PARKS, sp051307: LP0}
    assert entity_rows_covered(projects, entity_rows, owners)
    # the entity rows at the old instant no longer fit the moved project rows
    stale = [
        Bounds(uuid.uuid4(), tim, JOINED, TRANSFER),
        Bounds(uuid.uuid4(), sp051307, TRANSFER, None),
    ]
    assert not entity_rows_covered(projects, stale, owners)
    # an entity of another project never fits
    assert not entity_rows_covered(projects, entity_rows, {tim: LP0, sp051307: SMART_PARKS})
    assert not entity_rows_covered(projects, entity_rows, {})
    assert OUTSIDE_PROJECT in REFUSALS


def test_every_refusal_has_its_dutch():
    assert [text for text in REFUSALS if text not in NL] == []


@pytest.mark.parametrize("edge", ["start", "end"])
def test_a_naive_instant_is_refused_loudly(edge):
    from shared.timeutil import NaiveDatetimeError

    with pytest.raises(NaiveDatetimeError):
        move_edge("project", timeline(), NEW_ROW, edge, datetime(2026, 10, 25), NOW)
