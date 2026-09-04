# WildlifeNL

[WildlifeNL](https://wildlifenl.nl) is the Dutch research programme on human-wildlife
coexistence; Smart Parks is a consortium member and its collar data is one of the platform's
planned sources. The connector sends collar positions and temperatures as borne sensor
readings and camera trap detections as species detections (decision D88).

Built from the platform's [open source API](https://github.com/UtrechtUniversity/wildlifenl)
(MPL-2.0) and its functional and technical design documents. The OpenAPI document is
generated from that code and served at the API's root. Live verification waits for the
platform's URL and an account with the `data-system` role.

## Setup

1. Ask the WildlifeNL administrator for an account with the `data-system` role. Log in once
   through the API's own page (`POST /auth/` with the email address, then `PUT /auth/` with
   the code from the email); the answer carries the bearer `token`, which stays valid.
2. Under Integrate, Integrations: New integration, connector WildlifeNL. Config: `base_url`
   (the API root), `sensor_id_source` (`device_identity` by default: the DevEUI, IMEI or
   serial printed on the collar; or `device_name`, or `entity_id`), `temperature_metrics`
   (metric keys sent as the reading's temperature, default `temperature`), `sensor_type` for
   detections (`visual` by default) and `species` (Smart Parks species name to a WildlifeNL
   species name or id, for names the platform spells differently). Credentials: `token`.
3. Test the connection: the connector reads the account's profile, checks the `data-system`
   role and counts the platform's species.
4. Let a herd manager on the platform register each collar as a borne sensor deployment on its
   animal, with the same sensor id the integration sends. WildlifeNL accepts readings before
   that registration exists and links them once it does.

## Mapping

| Smart Parks Protect | WildlifeNL |
| --- | --- |
| position | `POST /borne-sensor-reading/` with `sensorID`, `timestamp`, `location` (`latitude`, `longitude`) and `altitude` |
| temperature measurement | `POST /borne-sensor-reading/` with `sensorID`, `timestamp` and `temperature` |
| `SPECIES_DETECTION` event (AddaxAI Connect) | `POST /detection/` per species named in the event: `speciesID` (resolved by Latin or common name against `GET /species/`, cached ten minutes), `deploymentID` (the camera's sensor id), `sensorType`, `location`, `start` and `end` (the capture time), `uri` (the image link), `animals` with the best `confidence` as a percentage |
| other events | skipped: WildlifeNL has no free-form events, its interactions are people's reports |
| corrected position | a new reading; WildlifeNL keeps both |

The platform updates the animal's location and raises its zone alarms from the readings and
detections it receives. Requests carry `Authorization: Bearer <token>`; 5xx and 429 answers
are retried on the delivery schedule, 401 and 403 mean the token or the role, other 4xx
answers are permanent failures with the platform's message.

## Troubleshooting

- `lacks the data-system role`: the account can log in but may not post readings; ask the
  administrator to add the role.
- `has no species named`: the platform does not know the species under that name; add it on
  the platform or map the name in the integration's `species` setting.
- Readings arrive but the animal does not move on the platform: no borne sensor deployment
  matches the sensor id; check `sensor_id_source` against what the herd manager registered.
