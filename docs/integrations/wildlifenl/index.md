# WildlifeNL

[WildlifeNL](https://wildlifenl.nl) is the Dutch research programme on human-wildlife
coexistence; Smart Parks is a consortium member. The connector sends positions and temperatures
of the entities you integrate as borne sensor readings, registers those entities as animals with
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

You never handle a token. Protect signs the integration in for you: you give the account's
email address, WildlifeNL mails a code to it, you type the code into Protect, and Protect stores
the sign-in (decision D414).

## Setting it up in a project

The connection is set once on the integration. Each entity is then integrated from its own
page, where its species and its history are chosen (decision D412).

### 1. The connection (a project admin, once)

1. **Integrate, Integrations, New integration**, connector WildlifeNL.
   - Config: the TEST server's address is filled in already,
     `{"base_url": "https://test-api-wildlifenl.uu.nl"}`. Change it for another server.
   - Forwards: positions, and measurements when the temperature should go along.
   - There is no credentials field: the sign-in fills them.
2. **Save.** The sign-in opens by itself:
   - type the account's email address (your own is filled in) and choose **Send me a code**;
   - WildlifeNL mails a code to that address; type it and choose **Sign in**.
   The dialog ends on who is signed in, the account's roles on WildlifeNL, and a warning when
   the account may send data but not register entities.

The integration's row has a key to sign in again, with the same or another account, and its
detail says who is signed in. **Test the connection** (the paper plane) repeats the check at any
time and also names the server's API version.

Nothing is sent yet. A WildlifeNL integration forwards the entities somebody integrated and no
others.

### 2. An entity (whoever may change integrations)

1. Open the entity. Its Overview has an **Integrations** card with the project's WildlifeNL
   integration and "Not integrated".
2. Choose **Integrate**. Protect asks the platform and shows:
   - **Species on WildlifeNL**: the platform's own list. When the entity's type matches one of
     its names, that one is chosen already; otherwise pick it.
   - **Device** and **Sensor id**: how the platform will know this entity's readings.
   - **Send its history first**, with the date to start from. It starts at the day the device
     came onto the entity, at most 400 days back.
3. Choose **Integrate**. The card follows what happens:
   - *Preparing history*, then *Sending history, N to go*: the old readings go oldest first.
   - *Integrated*: every reading was delivered and the animal and its sensor are registered.
     New readings follow as they arrive.
   - *On hold*: part of the history failed, so Protect did not register. Look at Deliveries,
     retry the failed ones, then choose Change and integrate without history.
   - *Not registered*: the platform refused the registration; the card says what it answered.

With the history switched off the entity is registered at once and only new data is sent.

**Change** opens the same dialog again, for another species or a history after all. **Stop**
ends the forwarding; what the platform has stays there.

The integration itself (click its row under Integrate, Integrations) lists every integrated
entity with what the platform has for it. Nothing is changed there.

## The species of an entity

The platform takes an animal only with a species from its own list, so the dialog offers that
list and nothing else. Protect proposes one when it finds a match, in this order, against the
platform's Latin and common names:

1. the entity's own `taxon`, `species` or `scientific_name` value;
2. the integration's optional `species` setting, by the key of the entity's type, for example
   `{"species": {"cow": "Bos taurus"}}`, which saves the picking in a project of one kind;
3. the label of the entity's type.

No match means no proposal: the user picks. Protect never registers an animal under a guess.

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
| integrated entity | `POST /animal/` (`name`, the species chosen), then `POST /borne-sensor-deployment/` (`animalID`, `sensorID`, `start` at the start of the device's time on the entity) |
| `SPECIES_DETECTION` event (AddaxAI Connect) | `POST /detection/` per species: `speciesName` or `speciesID` as the server's own API document asks, `deploymentID`, `sensorType`, `location`, `start`, `end`, `uri`, `animals` with the confidence as a percentage |
| other events | skipped: WildlifeNL has no free-form events |
| corrected position | a new reading; a reading at the same timestamp replaces the earlier one |

`sensorID` is the device's identity (the DevEUI, IMEI or serial on the hardware) by default;
`sensor_id_source` in the config changes it to `device_name` or `entity_id`. The same value is
used for the readings and for the deployment.

## Known limits

- **A device replaced on an entity** is not followed by itself. Open the entity, choose Change
  on its Integrations card and integrate it again: its new sensor is registered on the animal
  Protect made before. The platform ends the earlier deployment of a sensor when a new one is
  made for that sensor, not when the animal gets another sensor.
- **Late old readings after the registration** move the animal's location back and may raise
  alarms on the platform (see above). This is the platform's behaviour as its code reads; it is
  reported to its developers.
- **The rate limit.** The platform limits requests per account and answers 429 with the time to
  wait. Protect waits that long and goes on; a long history takes the time the platform allows.
- **Accelerometer values** are not sent.
- Protect never ends or deletes an animal or a deployment on the platform.

## Troubleshooting

- `did not accept the code`: the code was mistyped or has expired; choose Send a new code.
- `is not signed in`: the integration has no sign-in yet; use the key on its row.
- `lacks the data-system role`: the account can sign in but may not send readings.
- `does not show its deployments to this account; it needs the herd-manager role`: the account
  may send readings but not register animals.
- "On hold: N objects of its history failed": the history has holes, so Protect did not
  register. Open Deliveries, filter on failed, read the platform's answer, retry them, then
  choose Change on the entity's card and integrate without history.
- Readings arrive but the animal does not move on the platform: the sensor id of the readings
  and of the deployment differ; both follow `sensor_id_source`, so check that it was not changed
  between the two.
