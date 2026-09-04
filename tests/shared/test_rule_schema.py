"""The rule document: templates parse, invalid combinations are rejected, reserved types are
detected, the JSON schema builds."""

import pytest
from pydantic import ValidationError

from shared.rules.schema import RuleDocument, json_schema, parse_document
from shared.rules.templates import TEMPLATES, template_documents


def test_every_template_is_a_valid_document():
    docs = template_documents()
    assert set(docs) == set(TEMPLATES)
    assert docs["battery_low"].reserved_types() == []
    assert docs["speed_limit"].for_seconds == 30
    assert docs["speed_limit"].metrics() == {"speed_kmh"}


def test_no_data_needs_a_schedule_trigger():
    with pytest.raises(ValidationError, match="schedule"):
        parse_document(
            {
                "trigger": {"kind": "position"},
                "conditions": {"type": "no_data", "for_seconds": 3600},
                "event": {"event_type": "NO_DATA", "title": "x"},
            }
        )


def test_enter_needs_a_position_trigger():
    with pytest.raises(ValidationError, match="position trigger"):
        parse_document(
            {
                "trigger": {"kind": "measurement"},
                "conditions": {"type": "spatial", "relation": "enter", "feature_type": "geofence"},
                "event": {"event_type": "TEST", "title": "x"},
            }
        )


def test_spatial_needs_features():
    with pytest.raises(ValidationError, match="feature_ids or feature_type"):
        parse_document(
            {
                "trigger": {"kind": "position"},
                "conditions": {"type": "spatial", "relation": "inside"},
                "event": {"event_type": "TEST", "title": "x"},
            }
        )


def test_reserved_types_are_accepted_but_reported():
    doc = parse_document(
        {
            "trigger": {"kind": "position"},
            "conditions": {
                "all": [
                    {"type": "threshold", "metric": "speed_kmh", "op": ">", "value": 1},
                    {"type": "near", "feature_id": "abc", "meters": 50},
                ]
            },
            "event": {"event_type": "TEST", "title": "x"},
        }
    )
    assert doc.reserved_types() == ["near"]


def test_event_type_is_upper_snake():
    with pytest.raises(ValidationError):
        parse_document(
            {
                "trigger": {"kind": "position"},
                "conditions": {"type": "threshold", "metric": "speed_kmh", "op": ">", "value": 1},
                "event": {"event_type": "speed", "title": "x"},
            }
        )


def test_unknown_fields_are_rejected():
    with pytest.raises(ValidationError):
        RuleDocument.model_validate(
            {
                "trigger": {"kind": "position"},
                "conditions": {"type": "threshold", "metric": "x", "op": ">", "value": 1},
                "event": {"event_type": "TEST", "title": "x"},
                "bogus": 1,
            }
        )


def test_json_schema_builds():
    schema = json_schema()
    assert "trigger" in schema["properties"]
    assert "$defs" in schema and "ThresholdCondition" in schema["$defs"]
