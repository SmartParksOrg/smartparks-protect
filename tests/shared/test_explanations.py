"""Every event the system raises has an explanation, and the flags it carries are spelled out."""

from shared.domain.explanations import ERROR_FLAGS, EVENTS, explain_event
from shared.rules.templates import TEMPLATES


def test_every_template_event_type_is_explained():
    for template in TEMPLATES.values():
        assert template["document"]["event"]["event_type"] in EVENTS


def test_the_flags_of_a_device_error_are_spelled_out():
    text = explain_event("device_error", {"errors": ["ublox_fix", "lr_join"], "dedup": "x"})
    assert text is not None
    assert "did not get a fix" in text and "join the LoRaWAN network" in text
    assert text.startswith(EVENTS["device_error"])
    assert set(ERROR_FLAGS) >= {
        "lr_module",
        "ble",
        "ublox",
        "accelerometer",
        "battery",
        "ublox_fix",
        "flash",
        "ublox_busy",
        "lr_join",
    }


def test_a_reboot_names_its_reason_and_unknown_types_have_none():
    text = explain_event("device_reset", {"reset_reason": "watchdog"})
    assert text is not None and "watchdog restarted it" in text
    assert explain_event("device_reset", {}) == EVENTS["device_reset"]
    assert explain_event("MY_OWN_RULE", {"metric": "x"}) is None
