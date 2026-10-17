# Field, the companion for the place without a connection

Smart Parks Protect Field is a separate program ([`SmartParksOrg/smartparks-protect-field`](https://github.com/SmartParksOrg/smartparks-protect-field), [its documentation](https://smartparksorg.github.io/smartparks-protect-field/)) that a person runs on a laptop they take to the [offload stations](offload-stations.md). It reads a station's SD card where there is no connection, decodes the trackers' frames with Protect's own code, shows the positions and measurements, and hands the untouched card files to Protect when there is a connection again. Protect decodes them itself; nothing decoded in the field comes back. Decision D331 (2026-10-17); Field's own design is its ADR 0001.

## Installing Field from the Offload page

The Offload page's "Field for the laptop" button opens a card that gets a person from Protect to a running Field in three steps, without leaving the page (decision D332): the installer for the computer they are on (Windows `ProtectField-Setup.exe`, macOS `ProtectField-arm64.dmg` for Apple Silicon, Debian and Ubuntu `ProtectField-amd64.deb`; the other two a link away), always the newest release since the links point at `releases/latest/download`; this server's address with a copy button, which Field asks for at its first start; and "Open Field", a `protect-field://connect?server=…` link that an installed Field answers to by opening with this server filled in, after which the person signs in with their Protect email and password. The card links Field's own step-by-step page, which also says what to do about the warnings an unsigned installer draws on Windows and macOS until Smart Parks holds code-signing certificates. Field is installed and updated the way the desktop AddaxAI is (Field's decision D6): a release on GitHub carries the three installers, and Field tells its user at start when a newer one exists.

## What Protect gives Field

**The field bundle**, `GET /projects/{id}/field-bundle`, for a member of the project. One document with:

- the project (id, name, slug, time zone) and the versions that made the bundle (Protect's version and commit, the server's address for the upload);
- the project's devices the caller may see, each with its type and driver, its serial and DevEUI, its status and firmware, the entity it tracks now, and whether it is an offload station;
- each tracker's LP0 address, and its two session keys when the caller may set keys in this project (device control in the project, or a server admin, the rule of the device page's credentials card); a viewer gets the address and `keys_set` and no key;
- the entities those devices track, with type and icon and a place set by hand;
- the offload stations with their EUI and where they stand;
- the project's area: the bounding box of its features, its entities' places and its devices' places, which Field cuts its offline map for.

Every download is an audit log entry (`project.field_bundle_downloaded`) with how many devices, stations and keys it carried. The caller's visibility applies as everywhere: a member limited to some groups gets those groups' devices.

**The parser**, `shared/station_files.py`: the module that reads a station's files and unpacks a card's zip, with no database, broker or settings import, so Field reads a card on a laptop with the same code the file worker runs on the server. Field installs Protect's `shared` package pinned to a commit and imports this module, the LP0 codec and the OpenCollar driver.

## The offline map

Field draws positions on a map where there is no connection, so the map must travel with the bundle (Field's decision D4; phase 43 P3). Protect cuts it: `POST /projects/{id}/field-bundle/map`, for a member who may create exports (an analyst or an admin; a map is a file made for members as an export is), asks the export worker to run `pmtiles extract` on the newest Protomaps planet build, a single file of some 140 GB at `build.protomaps.com` that answers range requests, for the project's area with a five kilometre margin down to zoom 14. The worker reads only the ranges the box needs, keeps the result in the `map-extracts` bucket and writes its size, digest and build date on the project's row; `GET` on the same path, for every member, streams the file once it is ready, answers 202 with the state while it is being made, and 409 with the reason when the attempt failed. A map younger than a month that covers the area is kept; `force` cuts again. The bundle names the map's state. A park-sized area at zoom 14 is a few tens of megabytes; `MAP_EXTRACT_MAX_ZOOM`, `MAP_EXTRACT_MAX_BYTES` and `MAP_EXTRACT_SOURCE` (a build pinned by URL, or a file for a server without internet) are the settings. The tiles are OpenStreetMap's, under the ODbL, built by Protomaps; Field's map says so. Satellite imagery stays online: its terms do not allow caching.

## What Field gives Protect

The card's files, exactly as read, through `POST /devices/{id}/offload-files`, the same upload the station's device page makes. Protect decodes them, attributes the records as of their record time, and refuses a file it already holds by its content digest and a frame it already holds by its hash, so a card read in the field and uploaded later costs nothing twice.

## What never travels

No decoded row, no master key (Protect holds none, decision D327), and for now no notes or edits made offline. Should people need to record things in the field that must reach Protect, Field's plan parks an append-only outbox for it.

## Still to come

Field's own pages for the bundle, the cards and the upload (Field's phase 2); on this side, nothing is open.
