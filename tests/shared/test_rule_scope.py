"""A rule's scope by entity type takes the type's sub-types (phase 37): `in_scope` reads the
entity's lineage, its type and the type's parent, so a rule for Vehicles judges a car."""

import uuid

from shared.rules.replay import in_scope
from shared.rules.schema import Scope

VEHICLE, CAR, WILDLIFE, RHINO = (uuid.uuid4() for _ in range(4))
ENTITY, DEVICE = uuid.uuid4(), uuid.uuid4()


def test_a_parent_type_in_the_scope_takes_its_sub_types():
    scope = Scope(entity_type_ids=[VEHICLE])
    assert in_scope(scope, ENTITY, frozenset({CAR, VEHICLE}), DEVICE)
    assert in_scope(scope, ENTITY, VEHICLE, DEVICE)
    assert not in_scope(scope, ENTITY, frozenset({RHINO, WILDLIFE}), DEVICE)
    assert not in_scope(scope, ENTITY, None, DEVICE)


def test_a_sub_type_in_the_scope_takes_that_sub_type_alone():
    scope = Scope(entity_type_ids=[CAR])
    assert in_scope(scope, ENTITY, frozenset({CAR, VEHICLE}), DEVICE)
    assert not in_scope(scope, ENTITY, frozenset({VEHICLE}), DEVICE)


def test_an_empty_scope_takes_everything_and_the_other_lists_still_count():
    assert in_scope(Scope(), None, None, None)
    assert in_scope(Scope(entity_ids=[ENTITY]), ENTITY, None, None)
    assert in_scope(Scope(device_ids=[DEVICE]), None, None, DEVICE)
    assert not in_scope(Scope(device_ids=[DEVICE]), ENTITY, frozenset({CAR}), uuid.uuid4())
