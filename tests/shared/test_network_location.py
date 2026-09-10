"""Locations a network provides (decision D162): one shape from an Iridium session the network
stands by, from ThingPark's location report and from The Things Stack's solved location."""

from datetime import UTC, datetime

from shared.connectivity.adapters.kpn_thingpark import parse_event
from shared.connectivity.adapters.tts import parse_message
from shared.connectivity.network_location import NETWORK_RECORD_TYPE, NetworkLocation
from shared.connectivity.satellite import SatelliteSession
from tests.shared.test_adapters_and_drivers import context as base_context


def test_from_a_satellite_session_only_when_the_network_stands_by_it():
    at = datetime(2026, 9, 10, 14, 44, 3, tzinfo=UTC)
    good = SatelliteSession(
        status="ok", sequence=4757, latitude=46.5829, longitude=15.594, cep_km=5.0, session_at=at
    )
    location = NetworkLocation.from_satellite(good)
    assert location is not None
    assert location.method == "iridium_estimate" and location.accuracy_m == 5000.0
    assert location.time == at and location.attributes == {"cep_km": 5.0, "sequence": 4757}
    poor = SatelliteSession(
        status="location_unacceptable",
        latitude=46.5,
        longitude=15.1,
        cep_km=64.0,
        session_at=at,
    )
    assert NetworkLocation.from_satellite(poor) is None
    assert NetworkLocation.from_dict(location.to_dict()) == location
    assert NetworkLocation.from_dict({"latitude": "x"}) is None
    assert NETWORK_RECORD_TYPE == "network"


def test_thingpark_location_report_becomes_a_network_location():
    """The documented fields of `DevEUI_location` (the LRC-AS tunnel changelog): a report built
    from them until a live one is recorded."""
    report = {
        "DevEUI_location": {
            "Time": "2026-09-10T12:00:05.000+02:00",
            "DevEUI": "0016C001F016D281",
            "DevLocTime": "2026-09-10T12:00:00.000+02:00",
            "DevLAT": "52.0988",
            "DevLON": "5.1254",
            "DevAlt": "12.5",
            "DevLocRadius": "350",
            "DevAltRadius": "20",
            "DevLocDilution": "1.4",
            "DevUlFCntUpUsed": "812",
            "NwGeolocAlgo": "3",
            "NwGeolocAlgoUsed": "3",
            "CustomerID": "100001234",
        }
    }
    message = parse_event(base_context("kpn_thingpark"), report)
    assert message.event_type == "location"
    location = message.network_location
    assert location is not None
    assert (location.latitude, location.longitude) == (52.0988, 5.1254)
    assert location.accuracy_m == 350.0 and location.altitude_m == 12.5
    assert location.time == datetime(2026, 9, 10, 10, 0, tzinfo=UTC)
    assert location.method == "thingpark_geoloc"
    assert location.attributes == {
        "algorithm": "3",
        "altitude_radius_m": 20.0,
        "dilution": 1.4,
        "f_cnt_used": "812",
    }
    # an uplink carries no network location
    uplink = parse_event(
        base_context("kpn_thingpark"),
        {
            "DevEUI_uplink": {
                "Time": "2026-09-10T12:00:05.000+02:00",
                "DevEUI": "0016C001F016D281",
                "FPort": "13",
                "FCntUp": "812",
                "payload_hex": "00",
            }
        },
    )
    assert uplink.network_location is None


def test_tts_solved_location_becomes_a_network_location():
    document = {
        "end_device_ids": {
            "device_id": "sp05-1",
            "application_ids": {"application_id": "app"},
            "dev_eui": "0016C001F016D281",
        },
        "received_at": "2026-09-10T10:00:00.000Z",
        "location_solved": {
            "service": "packet-broker",
            "location": {
                "latitude": 52.09,
                "longitude": 5.12,
                "altitude": 3,
                "accuracy": 1200,
                "source": "SOURCE_LORA_RSSI_GEOLOCATION",
            },
        },
    }
    message = parse_message(base_context("tts"), document)
    assert message.event_type == "location"
    location = message.network_location
    assert location is not None
    assert location.method == "tts_lora_rssi_geolocation" and location.accuracy_m == 1200.0
    assert location.time == datetime(2026, 9, 10, 10, 0, tzinfo=UTC)
    assert location.attributes == {"source": "SOURCE_LORA_RSSI_GEOLOCATION"}
