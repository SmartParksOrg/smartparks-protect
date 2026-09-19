"""The server's texts in the reader's language (decision D240)."""

from shared.analysis.modules.device_performance import FOLDED_TEXTS
from shared.domain.contacts import HUMAN_PRESENCE_MANY, HUMAN_PRESENCE_ONE, HUMAN_PRESENCE_TITLE
from shared.domain.explanations import ERROR_FLAGS, EVENTS, RESET_REASONS, explain_event
from shared.domain.trap import trap_titles
from shared.i18n import resolve_language, translate
from shared.i18n.nl import NL
from shared.rules.templates import TEMPLATES


def test_the_language_comes_from_the_header():
    assert resolve_language(None) == "en"
    assert resolve_language("nl-NL,nl;q=0.9,en;q=0.8") == "nl"
    assert resolve_language("de-DE,de;q=0.9") == "en"
    assert resolve_language("fr, nl;q=0.5") == "nl"
    # the quality values decide, not the order the parts stand in (reviewed 2026-09-18)
    assert resolve_language("en;q=0.5,nl") == "nl"
    assert resolve_language("nl;q=0.2,en;q=0.9") == "en"
    assert resolve_language("nl;q=0,en") == "en", "q=0 refuses that language"
    assert resolve_language("nl;q=zero,en;q=0.4") == "en", "an unreadable q is no preference"


def test_exact_texts_and_templates_translate_and_unknown_text_stays():
    assert translate("Device rebooted", "nl") == "Apparaat herstart"
    assert translate("Device rebooted (watchdog)", "nl") == "Apparaat herstart (watchdog)"
    assert translate("Rhino 14 left North fence", "nl") == "Rhino 14 heeft North fence verlaten"
    assert (
        translate("Fix 3271 km from the last one in 1.0 h: flagged as an outlier", "nl")
        == "Fix 3271 km van de vorige in 1.0 h: gemarkeerd als uitschieter"
    )
    assert translate(
        "SP050969's fix interval is not known and too few fixes to learn it; missed fixes cannot be counted.",
        "nl",
    ).startswith("Het fixinterval van SP050969")
    # a person's own words and English stay as they are
    assert translate("Poacher seen near the river", "nl") == "Poacher seen near the river"
    assert translate("Device rebooted", "en") == "Device rebooted"
    assert translate(None, "nl") is None


def test_explanations_come_in_dutch_with_flags_and_reasons():
    text = explain_event("device_reset", {"reset_reason": "watchdog"}, "nl")
    assert text is not None and text.startswith("Het apparaat is opnieuw gestart")
    assert "De reden die het apparaat geeft: de firmware reageerde niet meer" in text
    errors = explain_event("device_error", {"errors": ["ublox", "mystery"]}, "nl")
    assert errors is not None and "ublox: De GPS-ontvanger" in errors
    assert "mystery: nog geen uitleg." in errors
    assert explain_event("device_reset", {"reset_reason": "watchdog"}) == explain_event(
        "device_reset", {"reset_reason": "watchdog"}, "en"
    )


def test_every_fixed_server_text_has_its_dutch():
    fixed = [
        *EVENTS.values(),
        *ERROR_FLAGS.values(),
        *RESET_REASONS.values(),
        *FOLDED_TEXTS.values(),
        HUMAN_PRESENCE_TITLE,
        HUMAN_PRESENCE_ONE,
        HUMAN_PRESENCE_MANY,
        *trap_titles(),
    ]
    for template in TEMPLATES.values():
        fixed.append(template["description"])
        for rule_event in _event_titles(template):
            fixed.append(rule_event)
    missing = [text for text in fixed if text not in NL]
    assert missing == [], missing


def _event_titles(template: dict) -> list[str]:
    out = []
    stack = [template]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            if "title" in node and isinstance(node["title"], str):
                out.append(node["title"])
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return out
