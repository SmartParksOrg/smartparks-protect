# WildlifeNL

[WildlifeNL](https://wildlifenl.nl) is the Dutch research programme on human-wildlife
coexistence; Smart Parks is a consortium member. The connector sends positions and temperatures
of the entities you choose as borne sensor readings, registers those entities as animals with
their sensor on the platform, and sends camera trap detections as species detections
(decisions D88 and D407 to D411).

Built from the platform's [open source API](https://github.com/UtrechtUniversity/wildlifenl)
(MPL-2.0), read at its push of 2026-11-16, and from the API documents the two servers serve
themselves:

| Server | Address | API version read on 2026-11-21 |
| --- | --- | --- |
| TEST | `https://test-api-wildlifenl.uu.nl` | 20261116 |
| LIVE | `https://live-api-wildlifenl.uu.nl` | 20260826 |

Start on TEST. The connector has been run end to end against a stand-in server built from
these documents; a run against the real TEST server is recorded here when it is done.

## What you need

An account on the server with two roles:

- `data-system`, to send readings and detections;
- `herd-manager`, so Protect can register the animals and their sensors. Without it the
  readings arrive but belong to no animal, until a herd manager registers each sensor by hand.

Get the token once: on the server's own API page, `POST /auth/` with your email address and a
`displayNameApp` (any name, it is shown in the email), then `PUT /auth/` with the code from the
email. The answer carries `token`. It stays valid.

## Setting it up in a project

1. **Integrate, Integrations, New integration**, connector WildlifeNL.
   - Config: `base_url`, the server's address from the table above.
   - Credentials: `token`.
   - Forwards: positions, and measurements when the temperature should go along.
   - **Entities**: tick the entities to integrate. Only their data is forwarded.
2. **Test the connection** (the paper plane on the row). The answer names the account, its
   roles, whether it may register animals, the server's API version and which species field a
   detection takes there.
3. Open the integration (click its row). **Entities on WildlifeNL** lists each ticked entity
   with what the platform has for it:
   - *Registered*: a deployment of its sensor exists, since the date shown.
   - *Not registered*: it can be registered; the line shows the sensor id and the species.
   - *Cannot be registered*, with the reason: no device on the entity, or no species the
     platform knows.
4. Choose **Send history, then register**, pick the period, and queue it. Protect sends the old
   readings oldest first. When every one of them is delivered, it registers the animals and
   their sensors. From then on the readings on the platform belong to those animals, the old
   ones as well, and new readings follow as they arrive.

**Register now** registers at once, without sending history. Use it when no old data should go.

A run covers at most 400 days. For more, run it again for the earlier period before you
register: choose the plain backfill (the clock icon on the row) without the tick for the earlier
runs, and "Send history, then register" for the last one.

## The species of an entity

The platform takes an animal only with a species from its own list. Protect looks for it in
this order and matches against the platform's Latin and common names:

1. the entity's own `taxon`, `species` or `scientific_name` value;
2. the integration's `species` setting, by the key of the entity's type;
3. the label of the entity's type.

When none is found the entity shows "Cannot be registered". Add the mapping to the config, for
example for PWN's cattle and horses:

```json
{
  "base_url": "https://test-api-wildlifenl.uu.nl",
  "species": {"cow": "Bos taurus", "horse": "Equus ferus caballus"}
}
```

The names must be the platform's own; `GET /species/` on the API page lists them.

## Why history goes first

As the platform's code read on 2026-11-21, a reading with a location for an animal that has a
deployment does two things, whatever the reading's age: it becomes the animal's current
location, and, when it is older than an hour, it raises zone alarms for the platform's users.
A reading for a sensor without a deployment is stored and does neither. So Protect sends the
history before the deployment exists.

What remains after the registration: a reading that reaches Protect late (a flash log read out
days afterwards, an offload station's card) is forwarded when it is younger than the
integration's "max age" and then moves the animal back and may raise alarms. On TEST that harms
nobody. Before a project goes to LIVE, read the note under "Known limits".

## Mapping

| Smart Parks Protect | WildlifeNL |
| --- | --- |
| position | `POST /borne-sensor-reading/` with `sensorID`, `timestamp`, `location` and `altitude` |
| temperature measurement | `POST /borne-sensor-reading/` with `sensorID`, `timestamp` and `temperature`; the platform keeps one reading per sensor and timestamp, so it joins the position of the same moment |
| ticked entity | `POST /animal/` (`name`, `speciesID`), then `POST /borne-sensor-deployment/` (`animalID`, `sensorID`, `start` at the start of the device's time on the entity) |
| `SPECIES_DETECTION` event (AddaxAI Connect) | `POST /detection/` per species: `speciesName` or `speciesID` as the server's own API document asks, `deploymentID`, `sensorType`, `location`, `start`, `end`, `uri`, `animals` with the confidence as a percentage |
| other events | skipped: WildlifeNL has no free-form events |
| corrected position | a new reading; a reading at the same timestamp replaces the earlier one |

`sensorID` is the device's identity (the DevEUI, IMEI or serial on the hardware) by default;
`sensor_id_source` in the config changes it to `device_name` or `entity_id`. The same value is
used for the readings and for the deployment.

## Known limits

- **A device replaced on an entity** is not followed by itself. Open the integration: the
  entity shows "Not registered" for its new sensor; register it. The platform ends the earlier
  deployment of a sensor when a new one is made for that sensor, not when the animal gets
  another sensor.
- **Late old readings after the registration** move the animal's location back and may raise
  alarms on the platform (see above). This is the platform's behaviour as its code reads; it is
  reported to its developers.
- **The rate limit.** The platform limits requests per account and answers 429 with the time to
  wait. Protect waits that long and goes on; a long history takes the time the platform allows.
- **Accelerometer values** are not sent.
- Protect never ends or deletes an animal or a deployment on the platform.

## Troubleshooting

- `lacks the data-system role`: the account can log in but may not send readings.
- `does not show its deployments to this account; it needs the herd-manager role`: the account
  may send readings but not register animals.
- `knows no species for this entity`: see "The species of an entity".
- "Not registered: N objects of the backfill failed": the history has holes, so Protect did not
  register. Open Deliveries, filter on failed, read the platform's answer, retry them, then
  choose Register now.
- Readings arrive but the animal does not move on the platform: the sensor id of the readings
  and of the deployment differ; both follow `sensor_id_source`, so check that it was not changed
  between the two.
