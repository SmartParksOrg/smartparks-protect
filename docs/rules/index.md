# Rules

A rule turns observations into events (architecture 15). Rules are versioned documents: every event references the exact version that created it, and a version can be tested against history before it is enabled. Rules live per project under Rules in the sidebar.

## What a rule is

| Part | Meaning |
| --- | --- |
| Trigger | What starts an evaluation: a new position, a new measurement (optionally one metric), a device state change, or a schedule (every N seconds) |
| Scope | Which entities the rule applies to; empty means every entity of the project |
| Conditions | One condition, or several that must all hold |
| For | How long the condition must hold before the rule fires (0 fires at once) |
| Cooldown | While the condition stays true, fire again as a reminder after this long; 0 never |
| Event | The event type, severity, title template and whether an alert is created |

The subject of a rule is the entity the data belongs to, or the device when no entity is assigned. State is kept per rule and subject: whether the condition is active, since when it holds, when it last fired and which geofences the subject was inside of.

## Conditions

| Type | Fields | Meaning |
| --- | --- | --- |
| Threshold | metric, operator, value | The triggering measurement, a derived position metric (`speed_kmh`, `speed_mps`, `altitude_m`) or the latest value of another metric of the subject (within seven days) compared with the value |
| Geofence or area | relation (enter, exit, inside, outside), features by type or by selection | Enter and exit fire on the crossing and need a position trigger; inside and outside are checked on every sample |
| No data | duration | The subject has not been seen for this long; needs a schedule trigger. A subject that never reported does not count |
| Window aggregate | metric, aggregate (avg, min, max, sum, count), window, operator, value | The aggregate over the last window of the metric compared with the value |

Reserved for a later release, accepted by the schema but not by the evaluator: `near`, `dwell`, `crossed`, `baseline`, `correlation`, `event_chain`. A rule that uses one can be saved but not enabled.

## Firing

Firing is edge-triggered. The rule fires when the condition becomes true, and while it stays true it fires again only after the cooldown. A battery rule with `battery_voltage < 3.2` and a cooldown of one day therefore sends one event when the battery drops and one reminder per day, not one per measurement. A rule with a `for` of 30 seconds fires when the samples show the condition holding for at least 30 seconds without a break.

The title is a template: `{entity}`, `{device}`, `{feature}`, `{metric}`, `{value}` and `{rule}` are filled in; an unknown placeholder renders as `?`.

## Templates

| Template | Trigger | Conditions | Event |
| --- | --- | --- | --- |
| Geofence exit | position | exit any geofence | `GEOFENCE_EXIT`, warning, alert |
| Geofence enter | position | enter any geofence | `GEOFENCE_ENTER`, info |
| Speed limit inside an area | position | `speed_kmh > 40` and inside any zone, for 30 s, cooldown 10 min | `SPEED_LIMIT_VIOLATION`, warning, alert |
| No data for 12 hours | schedule, every 5 min | no data for 12 h, cooldown 24 h | `NO_DATA`, warning, alert |
| Battery low | measurement `battery_voltage` | `battery_voltage < 3.2`, cooldown 24 h | `BATTERY_LOW`, warning, alert |
| Possible immobility | schedule, hourly | `avg(activity, 6 h) < 10` and `battery_voltage > 3.2`, cooldown 12 h | `POSSIBLE_IMMOBILITY`, critical, alert |

## Testing on history

The editor's Test tab replays the definition over the project's positions and measurements in a time range, with in-memory state, and lists the events it would have produced. Nothing is created. A replay reads at most 50,000 rows and returns at most 500 events; a schedule rule steps through the range at its interval, at most 5,000 steps. The API: `POST /projects/{id}/rules/{rule_id}/test` for a saved version, `POST /projects/{id}/rules/test-document` for a draft.

## The document

Rules are JSON documents validated by `shared/rules/schema.py`; the JSON schema is served at `GET /projects/{id}/rules/schema`. The example from architecture 15.3:

```json
{
  "trigger": {"kind": "position"},
  "scope": {"entity_type_ids": ["<vehicle type>"]},
  "conditions": {
    "all": [
      {"type": "threshold", "metric": "speed_kmh", "op": ">", "value": 40},
      {"type": "spatial", "relation": "inside", "feature_type": "zone"}
    ]
  },
  "for_seconds": 30,
  "event": {
    "event_type": "SPEED_LIMIT_VIOLATION",
    "severity": "warning",
    "title": "{entity} at {value} km/h inside {feature}",
    "create_alert": true
  }
}
```

`all`, `any` and `not` nest. The form in the editor shows one condition or an `all` of conditions; anything else is edited as JSON.

## Events and alerts

An event is a fact: a geofence exit, a low battery, a species detection from a device or an integration. An alert is an event that needs a person; it is open, acknowledged or resolved, with the actor, time and a note recorded. Alerts live in the Alerts inbox; every event has a detail page with its context, alert and the deliveries of the automations that acted on it. Events with a location show on the live map for the last 24 hours with the event marker family, so an event never looks like an entity.

Late data: every event carries the age of the sample that produced it. Rules evaluate offloaded history for completeness; [automations](automations.md) skip events older than their freshness bound so a log upload never pages anyone about last month.

## Failures

A rule that fails to evaluate (a reserved condition, a bug) does not stop the other rules. The failure is recorded on the rule (`last_error`, shown in the Rules list) and as a failed processing trace; the rule fires again normally once the cause is fixed. A rule that fires writes a compact trace with the matched subject, the evaluated values and the created event and alert; silent evaluations write nothing.
