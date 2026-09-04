"""OpenCollar control actions: encoding golden values from the protocol research (section 4),
parameter validation, response interpretation."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from shared.control.actions import ConfirmationPolicy, ResponseContext, actions_of
from shared.device_drivers.base import (
    DecodedMeasurement,
    DecodedPosition,
    DecodedRecords,
    DecodedState,
)
from shared.device_drivers.opencollar import OpenCollarDriver
from shared.device_drivers.opencollar.control import CONTROL_ACTIONS, GnssIntervalParameters
from shared.permissions import Permission

T = datetime(2026, 9, 4, tzinfo=UTC)


def test_driver_declares_actions():
    actions = actions_of(OpenCollarDriver())
    assert set(actions) == {"REQUEST_STATUS", "REQUEST_POSITION", "SET_GNSS_INTERVAL", "RESET"}
    assert actions_of(object()) == {}


@pytest.mark.parametrize(
    ("key", "params", "f_port", "payload"),
    [
        ("RESET", {}, 32, "a100"),
        ("REQUEST_STATUS", {}, 32, "a400"),
        ("REQUEST_POSITION", {}, 32, "b800"),
        ("SET_GNSS_INTERVAL", {"interval_seconds": 600}, 3, "020458020000"),
        ("SET_GNSS_INTERVAL", {"interval_seconds": 0}, 3, "020400000000"),
    ],
)
def test_encoding_golden(key, params, f_port, payload):
    action = CONTROL_ACTIONS[key]
    encoded = action.encode(action.parameters.model_validate(params))
    assert (encoded.f_port, encoded.payload.hex()) == (f_port, payload)
    assert encoded.confirmed is False


def test_parameters_are_validated():
    with pytest.raises(ValidationError):
        GnssIntervalParameters(interval_seconds=200_000)
    with pytest.raises(ValidationError):
        CONTROL_ACTIONS["RESET"].parameters.model_validate({"bogus": 1})


def test_policies_and_schema():
    assert CONTROL_ACTIONS["RESET"].permission == Permission.DEVICES_CONTROL_HIGH_IMPACT
    assert CONTROL_ACTIONS["RESET"].confirmation == ConfirmationPolicy.PRIVILEGED
    assert CONTROL_ACTIONS["REQUEST_STATUS"].confirmation == ConfirmationPolicy.NONE
    described = CONTROL_ACTIONS["SET_GNSS_INTERVAL"].describe()
    assert described["parameters_schema"]["properties"]["interval_seconds"]["maximum"] == 172_800
    assert described["confirms"] is False and described["schema_version"] == 1


def _context(event_type="uplink", **records) -> ResponseContext:
    return ResponseContext(event_type=event_type, records=DecodedRecords(**records), parameters={})


def test_status_request_confirmed_by_status_uplink():
    interpret = CONTROL_ACTIONS["REQUEST_STATUS"].interpret
    assert interpret is not None
    assert interpret(
        _context(
            measurements=[
                DecodedMeasurement(
                    time=T, metric_key="battery_voltage", value=3.9, record_type="status"
                )
            ]
        )
    ).confirmed
    assert (
        interpret(
            _context(
                measurements=[DecodedMeasurement(time=T, metric_key="battery_voltage", value=3.9)]
            )
        )
        is None
    )


def test_reset_confirmed_by_join_or_software_reset():
    interpret = CONTROL_ACTIONS["RESET"].interpret
    assert interpret is not None
    assert interpret(_context(event_type="join")).confirmed
    assert interpret(
        _context(states=[DecodedState(time=T, state={"reset_reason": {"software": True}})])
    ).confirmed
    assert (
        interpret(_context(states=[DecodedState(time=T, state={"reset_reason": {"pin": True}})]))
        is None
    )


def test_position_request_confirmed_by_port_2_fix():
    interpret = CONTROL_ACTIONS["REQUEST_POSITION"].interpret
    assert interpret is not None
    fix = DecodedPosition(time=T, latitude=-24.9, longitude=31.5, attributes={"port": 2})
    assert interpret(_context(positions=[fix])).confirmed
    assert (
        interpret(
            _context(
                positions=[
                    DecodedPosition(time=T, latitude=1, longitude=1, attributes={"port": 13})
                ]
            )
        )
        is None
    )
