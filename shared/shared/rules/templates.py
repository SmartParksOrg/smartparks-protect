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
    "near_site": {
        "name": "Near a site",
        "description": (
            "An entity comes within 200 metres of any site of the project "
            "(a proximity rule, decision D140). Reminds once an hour while it stays."
        ),
        "document": {
            "trigger": {"kind": "position"},
            "conditions": {"type": "near", "meters": 200, "feature_type": "site"},
            "cooldown_seconds": 3600,
            "event": {
                "event_type": "PROXIMITY",
                "severity": "warning",
                "title": "{entity} within {value} m of {feature}",
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
    "fence_down": {
        "name": "Fence down",
        "description": (
            "A fence monitor reads under 2 kV (phase 32). Reminds once a day while it stays down; "
            "the fence line's own status on the map follows the thresholds set on the line."
        ),
        "document": {
            "trigger": {"kind": "measurement", "metric_key": "fence_voltage"},
            "conditions": {
                "type": "threshold",
                "metric": "fence_voltage",
                "op": "<",
                "value": 2000,
            },
            "cooldown_seconds": 86_400,
            "event": {
                "event_type": "FENCE_DOWN",
                "severity": "critical",
                "title": "{entity} reads {value} V on the fence",
                "create_alert": True,
            },
        },
    },
    "fence_monitor_silent": {
        "name": "Fence monitor silent",
        "description": (
            "A fence monitor has not reported for six hours (phase 32). Checked every five "
            "minutes; scope it to the Fence monitor type."
        ),
        "document": {
            "trigger": {"kind": "schedule", "every_seconds": 300},
            "conditions": {"type": "no_data", "for_seconds": 21_600},
            "cooldown_seconds": 86_400,
            "event": {
                "event_type": "FENCE_MONITOR_SILENT",
                "severity": "warning",
                "title": "{entity} has not reported for 6 hours",
                "create_alert": True,
            },
        },
    },
    "trap_closed": {
        "name": "Trap closed",
        "description": (
            "A trap's door shut (phase 32, decision D266): somebody has to go and look. "
            "Reminds once a day while it stays shut."
        ),
        "document": {
            "trigger": {"kind": "measurement", "metric_key": "trap_triggered"},
            "conditions": {
                "type": "threshold",
                "metric": "trap_triggered",
                "op": ">=",
                "value": 1,
            },
            "cooldown_seconds": 86_400,
            "event": {
                "event_type": "TRAP_SHUT",
                "severity": "critical",
                "title": "{entity} is shut",
                "create_alert": True,
            },
        },
    },
    "possible_immobility": {
        "name": "Device not moving",
        "description": (
            "The accelerometer of the device has not changed between status messages for "
            "twelve hours (at least three messages), while the battery is fine. Checked hourly."
        ),
        "document": {
            "trigger": {"kind": "schedule", "every_seconds": 3600},
            "conditions": {
                "all": [
                    {
                        "type": "window",
                        "metric": "activity",
                        "aggregate": "max",
                        "seconds": 43_200,
                        "op": "<",
                        "value": 1.0,
                    },
                    {
                        "type": "window",
                        "metric": "activity",
                        "aggregate": "count",
                        "seconds": 43_200,
                        "op": ">=",
                        "value": 3,
                    },
                    {"type": "threshold", "metric": "battery_voltage", "op": ">", "value": 3.2},
                ]
            },
            "cooldown_seconds": 43_200,
            "event": {
                "event_type": "POSSIBLE_IMMOBILITY",
                "severity": "critical",
                "title": "{entity} has not moved for 12 hours",
                "create_alert": True,
            },
        },
    },
}


def template_documents() -> dict[str, RuleDocument]:
    """Every template parsed, so a broken template fails at import time in tests."""
    return {key: RuleDocument.model_validate(t["document"]) for key, t in TEMPLATES.items()}
