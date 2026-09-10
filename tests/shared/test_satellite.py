"""The satellite session behind an Iridium delivery (decision D158): one shape for Cloudloop's
named statuses and Rock7's numeric codes, the estimate's worth, and the fix-versus-estimate
check."""

import json
from datetime import UTC, datetime
from pathlib import Path

from shared.connectivity.adapters.cloudloop import parse_lingo
from shared.connectivity.adapters.rock7 import parse_message
from shared.connectivity.satellite import (
    SatelliteSession,
    estimate_disagreement,
    status_from_code,
    status_from_name,
    status_level,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "payloads"


def test_statuses_map_from_codes_and_names_to_one_vocabulary():
    assert status_from_code(0) == "ok" and status_from_code("2") == "location_unacceptable"
    assert status_from_code(13) == "rf_link_loss" and status_from_code(15) == "prohibited"
    assert status_from_code(None) == "unknown" and status_from_code("x") == "unknown"
    assert status_from_name("SESSION_STATUS_OK") == "ok"
    assert status_from_name("SESSION_STATUS_ERROR_RF_LINK_LOSS") == "rf_link_loss"
    assert status_from_name("SESSION_STATUS_ERROR_UNACCEPTABLE_QUALITY") == "location_unacceptable"
    assert status_from_name("") == "unknown"
    assert status_level("ok") == "ok" and status_level("location_unacceptable") == "ok"
    assert status_level("timeout") == "warn" and status_level("prohibited") == "critical"


def test_estimate_is_only_worth_showing_when_the_network_stands_by_it():
    good = SatelliteSession(status="ok", latitude=46.5, longitude=15.1, cep_km=4.0)
    poor = SatelliteSession(
        status="location_unacceptable", latitude=46.5, longitude=15.1, cep_km=64.0
    )
    assert good.has_estimate and not poor.has_estimate
    assert not SatelliteSession(status="ok").has_estimate
    # a fix within three CEP radii is no news; one far outside is
    assert estimate_disagreement(good, 46.52, 15.12) is None
    far = estimate_disagreement(good, 47.5, 15.1)
    assert far is not None and 110_000 < far < 112_000
    assert estimate_disagreement(poor, 47.5, 15.1) is None


def test_dict_round_trip_keeps_the_session():
    session = SatelliteSession(
        status="ok",
        status_code=0,
        sequence=4753,
        mt_sequence=0,
        latitude=46.5448,
        longitude=15.0995,
        cep_km=64.0,
        bytes=168,
        session_at=datetime(2026, 9, 10, 10, 43, 56, tzinfo=UTC),
    )
    data = session.to_dict()
    assert data["status_text"] == "session completed"
    assert SatelliteSession.from_dict(data) == session
    assert SatelliteSession.from_dict(None) is None and SatelliteSession.from_dict("x") is None


def test_the_adapters_fill_the_session():
    lingo = parse_lingo(
        json.loads((FIXTURES / "cloudloop" / "lingo_220757_replayed.json").read_text())
    )
    assert lingo.satellite_session is not None
    assert lingo.satellite_session.status == "ok"
    assert lingo.satellite_session.mt_sequence == 0 and lingo.satellite_session.bytes == 42
    assert lingo.satellite_session.session_at == lingo.satellite_delivered_at
    rock7 = parse_message(
        json.loads((FIXTURES / "rock7" / "delivery_live_sp051890.json").read_text())
    )
    assert rock7.satellite_session is not None
    assert rock7.satellite_session.status == "location_unacceptable"
    assert rock7.satellite_session.status_code == 2 and rock7.satellite_session.sequence == 4753
    assert rock7.satellite_session.cep_km == 64.0 and not rock7.satellite_session.has_estimate
    assert rock7.satellite_session.latitude == 46.5448
    # a documented delivery without the status field is a completed session
    plain = parse_message(
        {
            "imei": "300234010753370",
            "momsn": "12",
            "transmit_time": "21-10-31 10:41:50",
            "data": "48",
        }
    )
    assert plain.satellite_session is not None and plain.satellite_session.status == "ok"
