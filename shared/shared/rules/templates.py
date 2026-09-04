"""Rule templates shipped with the platform (architecture 30.1: geofence, speed, no-data,
battery). A template is a complete rule document plus a name; the UI offers them as starting
points and the API validates the result like any other document."""

from typing import Any

from shared.rules.schema import RuleDocument

TEMPLATES: dict[str, dict[str, Any]] = {
    "geofence_exit": {
        "name": "Geofence exit",
        "description": "An entity leaves any geofence of the project.",
        "document": {
            "trigger": {"kind": "position"},
            "conditions": {"type": "spatial", "relation": "exit", "feature_type": "geofence"},
            "event": {
                "event_type": "GEOFENCE_EXIT",
                "severity": "warning",
                "title": "{entity} left {feature}",
                "create_alert": True,
            },
        },
    },
    "geofence_enter": {
        "name": "Geofence enter",
        "description": "An entity enters any geofence of the project.",
        "document": {
            "trigger": {"kind": "position"},
            "conditions": {"type": "spatial", "relation": "enter", "feature_type": "geofence"},
            "event": {
                "event_type": "GEOFENCE_ENTER",
                "severity": "info",
                "title": "{entity} entered {feature}",
                "create_alert": False,
            },
        },
    },
    "speed_limit": {
        "name": "Speed limit inside an area",
        "description": "Faster than 40 km/h inside a zone for 30 seconds (architecture 15.3).",
        "document": {
            "trigger": {"kind": "position"},
            "conditions": {
                "all": [
                    {"type": "threshold", "metric": "speed_kmh", "op": ">", "value": 40},
                    {"type": "spatial", "relation": "inside", "feature_type": "zone"},
                ]
            },
            "for_seconds": 30,
            "cooldown_seconds": 600,
            "event": {
                "event_type": "SPEED_LIMIT_VIOLATION",
                "severity": "warning",
                "title": "{entity} at {value} km/h inside {feature}",
                "create_alert": True,
            },
        },
    },
    "no_data": {
        "name": "No data for 12 hours",
        "description": "An entity has not reported for twelve hours. Checked every five minutes.",
        "document": {
            "trigger": {"kind": "schedule", "every_seconds": 300},
            "conditions": {"type": "no_data", "for_seconds": 43_200},
            "cooldown_seconds": 86_400,
            "event": {
                "event_type": "NO_DATA",
                "severity": "warning",
                "title": "{entity} has not reported for 12 hours",
                "create_alert": True,
            },
        },
    },
    "battery_low": {
        "name": "Battery low",
        "description": "Battery voltage below 3.2 V. Reminds once a day while it stays low.",
        "document": {
            "trigger": {"kind": "measurement", "metric_key": "battery_voltage"},
            "conditions": {
                "type": "threshold",
                "metric": "battery_voltage",
                "op": "<",
                "value": 3.2,
            },
            "cooldown_seconds": 86_400,
            "event": {
                "event_type": "BATTERY_LOW",
                "severity": "warning",
                "title": "{entity} battery at {value} V",
                "create_alert": True,
            },
        },
    },
    "possible_immobility": {
        "name": "Possible immobility",
        "description": (
            "Average activity over six hours below 10 while the battery is fine "
            "(architecture 15.4, without the baseline term until phase 13)."
        ),
        "document": {
            "trigger": {"kind": "schedule", "every_seconds": 3600},
            "conditions": {
                "all": [
                    {
                        "type": "window",
                        "metric": "activity",
                        "aggregate": "avg",
                        "seconds": 21_600,
                        "op": "<",
                        "value": 10,
                    },
                    {"type": "threshold", "metric": "battery_voltage", "op": ">", "value": 3.2},
                ]
            },
            "cooldown_seconds": 43_200,
            "event": {
                "event_type": "POSSIBLE_IMMOBILITY",
                "severity": "critical",
                "title": "{entity} may be immobile: activity {value} over 6 hours",
                "create_alert": True,
            },
        },
    },
}


def template_documents() -> dict[str, RuleDocument]:
    """Every template parsed, so a broken template fails at import time in tests."""
    return {key: RuleDocument.model_validate(t["document"]) for key, t in TEMPLATES.items()}
