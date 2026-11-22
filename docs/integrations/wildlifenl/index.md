# WildlifeNL

[WildlifeNL](https://wildlifenl.nl) is the Dutch research programme on human-wildlife
coexistence; Smart Parks is a consortium member. The connector sends positions and temperatures
of the entities you integrate as borne sensor readings, registers those entities as animals with
their sensor on the platform, follows a device that moves to another entity after a person
confirmed it, and sends camera trap detections as species detections (decisions D88, D407
to D420).

Built from the platform's [open source API](https://github.com/UtrechtUniversity/wildlifenl)
(MPL-2.0), read at its push of 2026-11-16 and again at cc71256 of 2026-11-22, and from the API documents the two servers serve
themselves:

| Server (as the form names it) | Address | API version read on 2026-11-21 |
| --- | --- | --- |
| Test | `https://test-api-wildlifenl.uu.nl` | 20261116 |
| Live | `https://live-api-wildlifenl.uu.nl` | 20260826 |

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

1. **Integrate, Integrations, New integration**, target WildlifeNL. The form asks for two
   things and nothing is typed in as text or JSON:
   - **Name**: "WildlifeNL" is filled in; change it when a project has both servers.
   - **Server**: Test or Live. Start on Test.
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
   - **Ear tag number**: required. The platform takes it as the animal's identifier (decision
     D422). Filled in when the entity has one; typed here when it has none, and then saved on
     the entity as its Ear tag number. Once the animal is made, a change here stays in Protect:
     the platform cannot change an animal.
   - **Device** and **Sensor id**: how the platform will know this entity's readings.
   - What the platform has for that sensor: on this entity's animal already, or on another
     animal. In the second case integrating moves the sensor here, and the history is sent
     after the deployment, so it does not land on the other animal.
   - An entity without a device can be integrated too: its animal is made, and the first
     device assigned to it waits for a confirmation (below).
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
entity with what the platform has for it, and the devices that wait for a confirmation.

The device's own page has the same **Integrations** card. It shows the entity the device is on
now with Integrate, Change and Stop for that entity, and every deployment of the device: on
which entity, from when to when, and whether it waits.

### 3. A device that moves to another entity

In Protect the device is the sensor and the entity is the animal. WildlifeNL links a reading
to an animal through a deployment of the sensor, and a new deployment of a sensor ends the
one before it at the new start. It has no call to end or remove a deployment.

Every half minute Protect compares the devices on integrated entities with what it sent:

| What happened in Protect | What Protect does |
| --- | --- |
| A device moved from one integrated entity to another | A deployment on the new entity's animal **waits for you**. The device's readings for the new entity are held: sent now they would land on the old animal. |
| A second device on an integrated entity, or the first on one integrated without a device | The same: a deployment that waits, the readings held. |
| A device back on an animal that still has it (its move was declined, or an assignment cut in two) | Nothing. The platform has the sensor there already. |
| A device moved to an entity that is not integrated, or to none | Its readings stop. The card says the platform keeps the sensor on the old animal, since it cannot end a deployment; that ends when the sensor is deployed again. |
| An assignment's start changed after the deployment was sent | The sent one is marked as changed, and a deployment from the new start waits. |

On the entity's card, the device's card or the integration's overview:

- **Confirm** makes the deployment from the start of the device's assignment. The held
  readings go after it, oldest first. When the platform refuses, the row says what it
  answered and **Try again** stays.
- **Decline** sends nothing, and the device's readings for that entity in that period are not
  sent either.

**When a sensor had a deployment before.** The platform's code (cc71256) sets the end of
*every* deployment of a sensor to the new start, not only of the open one. A device's first move
is right. From its second move on, the finished deployments get a wrong end and overlap, and
the animals' tracks over that time are wrong. The confirm dialog warns when this would happen,
with how many deployments it touches. A report for the platform's developers was written on
2026-11-22.

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
| status message (device temperature and accelerometer) | `POST /borne-sensor-reading/` without a location: `sensorID`, `timestamp`, `temperature` (the temperature inside the device, °C) and `accelero` (x, y, z in m/s², as Protect stores them) when the device measured all three axes. One request per status message. It moves no animal and raises no alarm. The platform keeps one reading per sensor and timestamp, so a position of the same moment joins it |
| integrated entity | `POST /animal/` (`identifier`: the entity's ear tag number, since the platform's API of 2026-11-22; `speciesID`: the species chosen), then `POST /borne-sensor-deployment/` (`animalID`, `sensorID`, `start` at the start of the device's time on the entity) |
| `SPECIES_DETECTION` event (AddaxAI Connect) | `POST /detection/` per species: `speciesName` or `speciesID` as the server's own API document asks, `deploymentID`, `sensorType`, `location`, `start`, `end`, `uri`, `animals` with the confidence as a percentage |
| other events | skipped: WildlifeNL has no free-form events |
| corrected position | a new reading; a reading at the same timestamp replaces the earlier one |

`sensorID` is the device's identity by default: its DevEUI when it has one, else the identity it
was heard under first, so a device heard over LoRaWAN and Iridium keeps one name there
(decision D417). Protect keeps the sensor id with each deployment it makes;
`sensor_id_source` in the config changes it to `device_name` or `entity_id`. The same value is
used for the readings and for the deployment.

## Known limits

- **A device that leaves its animal** stays deployed there on the platform until the sensor is
  deployed again: the platform has no call to end a deployment.
- **A sensor's third deployment** gives the earlier ones a wrong end on the platform (see
  "A device that moves to another entity").
- **An animal's track on the platform** holds every reading of its sensor in the period asked,
  also those from after the sensor moved on: the platform reads the sensor's readings over the
  asked period, not over the deployment's own. In the same report.
- **Late readings after a confirmation.** The readings held while a deployment waited go after
  it, oldest first. Each moves the animal's location, and the old ones may raise alarms on the
  platform (see "Why history goes first").
- **Late old readings after the registration** move the animal's location back and may raise
  alarms on the platform (see above). This is the platform's behaviour as its code reads; it is
  reported to its developers.
- **The rate limit.** The platform limits requests per account and answers 429 with the time to
  wait. Protect waits that long and goes on; a long history takes the time the platform allows.
- **What is sent.** Positions, and per status message the device temperature with the
  accelerometer (decision D421). The platform's reading has no field for the battery, the
  activity index, the uptime or the satellites, and refuses fields it does not know, so those
  stay in Protect. A status message without a temperature is not sent. Camera trap detections
  are built in the connector and not set by the form; say so when a project needs them.
- **The accelerometer's unit.** The platform's document gives none; Protect sends m/s². Asked
  of the platform's administrator on 2026-11-22.
- **The device temperature** is measured inside the device. On an animal it lies between the
  body and the air temperature; read it as such.
- **Another server is another integration.** The server of an integration cannot change while
  entities are integrated with it, and changing it signs the integration out.
- **An animal cannot be changed.** The platform has no call for it, so an animal keeps the
  identifier it was made with. A corrected ear tag number reaches the platform only with a new
  animal.
- Protect never ends or deletes an animal or a deployment on the platform.

## Troubleshooting

- `did not accept the code`: the code was mistyped or has expired; choose Send a new code.
- `is not signed in`: the integration has no sign-in yet; use the key on its row.
- After the sign-in, "may not send data" or "may not register entities": the platform's own API
  document says the account's roles do not reach the calls Protect needs. Protect reads which
  roles each call takes from that document, so a role given more rights by the platform's
  administrator works without a change in Protect (decision D420). Ask the administrator.
- `does not show its deployments to this account`: the account may not read the platform's
  deployments, which registration needs.
- Readings stay queued with "Waits until a person confirms the deployment of this device": the
  device came onto the entity. Confirm or decline it on the entity's card.
- "On hold: N objects of its history failed": the history has holes, so Protect did not
  register. Open Deliveries, filter on failed, read the platform's answer, retry them, then
  choose Change on the entity's card and integrate without history.
- Readings arrive but the animal does not move on the platform: the sensor id of the readings
  and of the deployment differ; both follow `sensor_id_source`, so check that it was not changed
  between the two.
