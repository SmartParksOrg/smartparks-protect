"""Turning a sighting into a contact (decisions D253, D254): three octets are a fragment, not an
identity, and what is made of them is decided once."""

import uuid

from shared.domain.contacts import Resolver, normalise, suffix_of
from shared.enums import ContactResolution

A, B, OBSERVER = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


def test_an_address_is_compared_in_one_spelling():
    """The reference decoder drops leading zeros; a device might send any case. One spelling of
    an address must never become two neighbours."""
    assert normalise("a:41:c") == "0a:41:0c"
    assert normalise("0A:41:0C") == "0a:41:0c"
    # a full address reduces to what a scan of it would report
    assert normalise("d4:22:11:0a:41:0c") == "0a:41:0c"


def test_the_suffix_is_what_a_neighbour_would_report():
    assert suffix_of("d4:22:11:0a:41:0c") == "0a:41:0c"
    assert suffix_of(None) is None
    assert suffix_of("0a:41") is None, "too short to be an address"


def test_one_device_ending_with_those_octets_resolves():
    resolver = Resolver(by_suffix={"0a:41:0c": [A]})
    found = resolver.resolve("0a:41:0c", OBSERVER)
    assert found.resolution == ContactResolution.RESOLVED and found.device_id == A


def test_no_device_leaves_an_unknown_neighbour():
    """Decision D253: kept, not discarded. The same unknown address every night is a finding."""
    found = Resolver(by_suffix={}).resolve("0a:41:0c", OBSERVER)
    assert found.resolution == ContactResolution.UNKNOWN
    assert found.device_id is None and found.candidates == []


def test_two_devices_are_ambiguous_and_belong_to_neither():
    """Decision D254: a wrong contact between two named animals is worse than a missing one."""
    found = Resolver(by_suffix={"0a:41:0c": [A, B]}).resolve("0a:41:0c", OBSERVER)
    assert found.resolution == ContactResolution.AMBIGUOUS
    assert found.device_id is None
    assert set(found.candidates) == {A, B}, "both named, so a person can judge"


def test_a_device_never_meets_itself():
    """A stale address on another row could collide with the observer's own."""
    resolver = Resolver(by_suffix={"0a:41:0c": [OBSERVER]})
    assert resolver.resolve("0a:41:0c", OBSERVER).resolution == ContactResolution.UNKNOWN
    # and with one real neighbour beside it, that neighbour resolves rather than reading ambiguous
    resolver = Resolver(by_suffix={"0a:41:0c": [OBSERVER, A]})
    found = resolver.resolve("0a:41:0c", OBSERVER)
    assert found.resolution == ContactResolution.RESOLVED and found.device_id == A


def test_the_spelling_of_the_sighting_does_not_decide_the_match():
    resolver = Resolver(by_suffix={"0a:41:0c": [A]})
    for spelling in ("0a:41:0c", "0A:41:0C", "a:41:c"):
        assert resolver.resolve(spelling, OBSERVER).device_id == A, spelling
