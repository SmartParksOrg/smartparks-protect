# AddaxAI Connect

Camera trap detections from [AddaxAI Connect](https://github.com/PetervanLunteren/AddaxAI-Connect)
enter Smart Parks Protect as events (architecture 18.3): a wolf detection becomes a
`SPECIES_DETECTION` event with the species, confidence, camera, site, the camera's location and
a link back, and rules and integrations treat it like any other event.

Built from the AddaxAI Connect API code (decisions D16, D63 and D64). Live verification waits
for an AddaxAI Connect server with a viewer account for this server.

## Setup

1. In AddaxAI Connect, create a user for this server with viewer access to the projects to
   follow (AddaxAI Connect has only user login today; an API key mode is added when it grows
   one).
2. Under Server admin, Data sources: New data source, adapter AddaxAI Connect. Config: `url`,
   optionally `web_url`, `project_ids` (AddaxAI Connect project ids; empty for every project the
   account sees), `poll_interval_seconds` (300), `min_confidence` (0.5), `species`,
   `categories` (animal, person, vehicle), `verified_only`. Credentials: `email`, `password`.
3. Every camera becomes an identity of type `addaxai_camera_id` with the camera name, its
   AddaxAI device id and the site as attributes. Create a device per camera with the Generic
   JSON driver and link it, or accept it from Needs attention. A camera entity of an
   infrastructure type makes the camera visible on the map.

## What arrives

The connector logs in (`POST /api/auth/login`), lists cameras (`GET /api/cameras`, for the
location and site) and pages through `GET /api/images?sort=newest` from the cursor. Every
classified image with a detection that passes the filters becomes one source event on the
camera's identity with the image item under `raw`, and one `SPECIES_DETECTION` event:

| Field | Value |
| --- | --- |
| time | the image's capture time |
| title | `Wolf at Waterhole north` (species from the classifications or, for a verified image, the human observations) |
| location | the camera's location from its latest report, also stored as a position of the camera |
| context | `species`, `top_species`, `max_confidence`, `classifications`, `categories`, `detection_count`, `verified`, `camera_id`, `camera_name`, `site_name`, `image_uuid`, `link` |

Filters: a detection counts when its category is in `categories` (empty for all) and a
classification reaches `min_confidence`; a species suggested below the threshold is dropped, a
person or vehicle detection uses the detection's own confidence. With `species` set, only those
species pass. `verified_only` keeps images a person verified.

## Cursor and rescans

The cursor is the newest capture time seen plus the images at that instant; each poll asks
for newer images only. Because bulk SD-card imports arrive with old capture times, a rescan over
`overlap_days` (7) runs every `rescan_interval_hours` (24). For older imports use Rescan on the
data source with the instant to start from. Duplicate images are recognised by the pipeline's
canonical keys, so a rescan never doubles an event.

## Links

`OPEN_DEVICE` opens the project's camera list in AddaxAI Connect, `OPEN_APPLICATION` its image
list; the event context carries a link to the camera's images. The paths follow the AddaxAI
Connect web app's routes and are confirmed at the live run.

## Troubleshooting

- The connector logs `refused the credentials`: the account's password changed or it is not
  verified in AddaxAI Connect.
- No events although images exist: check `min_confidence`, `categories` and `species`; a
  camera without a location still produces events, only without a point.
- Events of an old import are missing: Rescan from before the import's capture times.
