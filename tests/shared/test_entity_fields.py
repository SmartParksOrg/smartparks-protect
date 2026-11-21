"""The fields of an entity by its type (decisions D399 to D404): the definitions, the order a
sub-type has them in, and the values as they are stored."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from shared.catalog.entity_fields import (
    MAX_OWN_FIELDS,
    STANDARD_FIELDS,
    FieldDefinition,
    FieldError,
    check_own,
    fields_of,
    own_fields,
    validate_attributes,
)
from shared.catalog.entity_types import ENTITY_TYPE_SEEDS

COLOUR = {"key": "collar_colour", "label": "Collar colour", "kind": "text"}
HERD = {"key": "herd", "label": "Herd", "kind": "text"}


def test_standard_fields_belong_to_seeded_types_under_unique_keys():
    seeded = {s.key: s for s in ENTITY_TYPE_SEEDS}
    for key, fields in STANDARD_FIELDS.items():
        assert seeded[key].parent_key is None, key
        keys = [f.key for f in fields]
        assert len(keys) == len(set(keys)), key


def test_a_subtype_has_its_types_fields_then_its_own():
    fields = fields_of("cow", {"fields": [HERD]}, ("wildlife", {"fields": [COLOUR]}))
    keys = [f.key for f in fields]
    standard = [f.key for f in STANDARD_FIELDS["wildlife"]]
    assert keys == [*standard, "collar_colour", "herd"]
    by_key = {f.key: f for f in fields}
    assert by_key["ear_tag"].origin == "standard" and by_key["ear_tag"].inherited
    assert by_key["collar_colour"].origin == "own" and by_key["collar_colour"].inherited
    assert by_key["herd"].origin == "own" and not by_key["herd"].inherited
    assert [f.key for f in fields_of("vehicle", {})] == [
        "licence_plate",
        "make",
        "model",
        "fleet_number",
    ]
    assert fields_of("made_by_hand", None) == []


@pytest.mark.parametrize(
    "definition",
    [
        {"key": "Colour", "label": "Colour", "kind": "text"},
        {"key": "colour", "label": "Colour", "kind": "colour"},
        {"key": "colour", "label": "Colour", "kind": "choice"},
        {
            "key": "colour",
            "label": "Colour",
            "kind": "text",
            "choices": [{"value": "a", "label": "A"}],
        },
        {"key": "colour", "label": "Colour", "kind": "text", "unit": "kg"},
        {"key": "length", "label": "Length", "kind": "number", "min": 5, "max": 1},
        {"key": "length", "label": "Length", "kind": "number", "search": True},
        {"key": "colour", "label": "Colour", "kind": "text", "required": True},
        {
            "key": "colour",
            "label": "Colour",
            "kind": "choice",
            "choices": [{"value": "red", "label": "Red"}, {"value": "red", "label": "Rood"}],
        },
    ],
)
def test_a_definition_that_cannot_stand_is_refused(definition):
    with pytest.raises(ValidationError):
        FieldDefinition.model_validate(definition)


def test_own_fields_are_a_bounded_list_of_unique_keys():
    assert own_fields({}) == () and own_fields(None) == ()
    assert [f.key for f in own_fields({"fields": [COLOUR, HERD]})] == ["collar_colour", "herd"]
    with pytest.raises(ValidationError):
        own_fields({"fields": [COLOUR, COLOUR]})
    with pytest.raises(ValidationError):
        own_fields({"type": "object", "properties": {}})
    many = [
        {"key": f"field_{i}", "label": "Field", "kind": "text"} for i in range(MAX_OWN_FIELDS + 1)
    ]
    with pytest.raises(ValidationError):
        own_fields({"fields": many})
    with pytest.raises(FieldError, match="collar_colour"):
        check_own(own_fields({"fields": [COLOUR]}), {"collar_colour", "sex"})


def test_values_are_stored_by_their_kind():
    fields = fields_of(
        "wildlife",
        {
            "fields": [
                {"key": "tagged_on", "label": "Tagged", "kind": "date"},
                {"key": "habituated", "label": "Habituated", "kind": "boolean"},
            ]
        },
    )
    stored = validate_attributes(
        fields,
        {
            "individual_id": "  R-14 ",
            "sex": "female",
            "birth_year": 2015.0,
            "vhf_frequency_mhz": 148.32,
            "ear_tag": "nl 1234 5678 9012",
            "weight_kg": 0,
            "tagged_on": "2026-03-01",
            "habituated": False,
            "breed": "   ",
            "age_class": None,
            "species": "Diceros bicornis",
        },
    )
    assert stored == {
        "individual_id": "R-14",
        "sex": "female",
        "birth_year": 2015,
        "vhf_frequency_mhz": 148.32,
        "ear_tag": "NL123456789012",
        "weight_kg": 0,
        "tagged_on": "2026-03-01",
        "habituated": False,
        # a key no field defines is kept as it came (decision D401)
        "species": "Diceros bicornis",
    }
    assert isinstance(stored["birth_year"], int)


@pytest.mark.parametrize(
    ("values", "names"),
    [
        ({"vhf_frequency_mhz": 5}, "\\(vhf_frequency_mhz\\): at least 30"),
        ({"vhf_frequency_mhz": "148.32"}, "\\(vhf_frequency_mhz\\): a number"),
        ({"vhf_frequency_mhz": True}, "\\(vhf_frequency_mhz\\): a number"),
        ({"weight_kg": float("nan")}, "\\(weight_kg\\): a number"),
        ({"birth_year": 2015.5}, "\\(birth_year\\): a whole number"),
        ({"birth_year": 2200}, "\\(birth_year\\): at most 2100"),
        ({"sex": "bull"}, "\\(sex\\): one of female, male, unknown"),
        ({"ear_tag": "12"}, "\\(ear_tag\\): 4 to 20"),
        ({"ear_tag": "NL-1234"}, "\\(ear_tag\\): 4 to 20"),
        ({"breed": 7}, "\\(breed\\): text"),
        ({"breed": "x" * 501}, "\\(breed\\): at most 500"),
        ({"notes_of_ours": "x" * 9000}, "at most 8192 bytes"),
    ],
)
def test_a_wrong_value_names_its_field(values, names):
    with pytest.raises(FieldError, match=names):
        validate_attributes(fields_of("wildlife", {}), values)


def test_a_date_and_a_yes_or_no_are_checked():
    fields = [
        FieldDefinition(key="tagged_on", label="Tagged", kind="date"),
        FieldDefinition(key="habituated", label="Habituated", kind="boolean"),
    ]
    with pytest.raises(FieldError, match="\\(tagged_on\\): a date"):
        validate_attributes(fields, {"tagged_on": "1 March"})
    with pytest.raises(FieldError, match="\\(habituated\\): yes or no"):
        validate_attributes(fields, {"habituated": "yes"})


def test_every_standard_text_is_in_the_interface_catalogues():
    """The API sends the standard labels in English and the interface translates them, so
    each one is a key of both catalogues (phase 48, F12)."""
    texts: set[str] = set()
    for fields in STANDARD_FIELDS.values():
        for field in fields:
            texts.add(field.label)
            texts.update(choice.label for choice in field.choices)
            if field.help:
                texts.add(field.help)
    locales = Path(__file__).parents[2] / "services" / "frontend" / "src" / "locales"
    for language in ("en", "nl"):
        catalogue = json.loads((locales / language / "translation.json").read_text())
        assert texts <= set(catalogue), (language, sorted(texts - set(catalogue)))
