# Protect Go, the app for the place without a connection

Smart Parks Protect Go (named Field until 2026-10-17; the repository and the installers were renamed with it) is a separate program ([`SmartParksOrg/smartparks-protect-go`](https://github.com/SmartParksOrg/smartparks-protect-go), [its documentation](https://smartparksorg.github.io/smartparks-protect-go/)) that a person runs on a laptop they take to the [offload stations](offload-stations.md). It reads a station's SD card where there is no connection, decodes the trackers' frames with Protect's own code, shows the positions and measurements, and hands the untouched card files to Protect when there is a connection again. Protect decodes them itself; nothing decoded in the field comes back. Decision D331 (2026-10-17); Protect Go's own design is its ADR 0001.

## Installing the app from the Offload page

The Offload page's "Protect Go, the app for the laptop" button opens a card that gets a person from Protect to a running app in three steps, without leaving the page (decision D332): the installer for the computer they are on (Windows `ProtectGo-Setup.exe`, macOS `ProtectGo-arm64.dmg` for Apple Silicon, Debian and Ubuntu `ProtectGo-amd64.deb`; the other two a link away), always the newest release since the links point at `releases/latest/download`; this server's address with a copy button, which Protect Go asks for at its first start; and "Open Protect Go", which starts the installed app connected to this server and signed in as the person on the page (decision D333): the button asks Protect for a one-time code (`POST /api/v1/auth/go-handoff`, for the signed-in person, good for two minutes), opens `protect-go://connect?server=…&code=…`, and the app exchanges the code once (`POST /api/v1/auth/go-handoff/exchange`, throttled like the login) for a token of its own that lasts 30 days (`GO_TOKEN_LIFETIME_DAYS`), cut short by a password change like every token. Both ends are written to the audit log. The address on the card is for typing it in by hand, and the app still signs in with a Protect email and password when the link does not reach it. The card links the app's own step-by-step page, which also says what to do about the warnings an unsigned installer draws on Windows and macOS until Smart Parks holds code-signing certificates. The app is installed and updated the way the desktop AddaxAI is (its decision D6): a release on GitHub carries the three installers, and the app tells its user at start when a newer one exists; on Windows it downloads and installs that one itself (its decision D17), macOS follows once the app is signed.

## What Protect gives the app

**The field bundle**, `GET /projects/{id}/field-bundle`, for a member of the project. One document with:

- the project (id, name, slug, time zone) and the versions that made the bundle (Protect's version and commit, the server's address for the upload);
- the project's devices the caller may see, each with its type and driver, its serial and DevEUI, its status and firmware, the entity it tracks now, and whether it is an offload station;
- each tracker's LP0 address, and its two session keys when the caller may set keys in this project (device control in the project, or a server admin, the rule of the device page's credentials card); a viewer gets the address and `keys_set` and no key;
- the entities those devices track, with type and icon and a place set by hand;
- the offload stations with their EUI and where they stand;
- the project's area: the bounding box of its features, its entities' places and its devices' places, which Protect Go cuts its offline map for.

Every download is an audit log entry (`project.field_bundle_downloaded`) with how many devices, stations and keys it carried. The caller's visibility applies as everywhere: a member limited to some groups gets those groups' devices.

**The decode path**, `shared/station_decode.py`: `unwrap_station_frame` opens a frame with the tracker's keys and refuses it with the same code and words the server's trace carries (no keys, a station naming another tracker than the address belongs to, an LP0 metadata version this code does not read, a frame that does not verify); `decode_station_frame` has the device's driver read the records exactly as the pipeline has it read them. The pipeline calls the same two functions, and a test decodes one frame both ways and compares the positions, so Protect Go's reading of a card and Protect's cannot drift.

**The parser**, `shared/station_files.py`: the module that reads a station's files and unpacks a card's zip, with no database, broker or settings import, so Protect Go reads a card on a laptop with the same code the file worker runs on the server. Protect Go installs Protect's `shared` package pinned to a commit and imports this module, the LP0 codec and the OpenCollar driver.

## The offline map

Protect Go draws positions on a map where there is no connection, so the map must travel with the bundle (Protect Go's decision D4; phase 43 P3). Protect cuts it: `POST /projects/{id}/field-bundle/map`, for a member who may create exports (an analyst or an admin; a map is a file made for members as an export is), asks the export worker to run `pmtiles extract` on the newest Protomaps planet build, a single file of some 140 GB at `build.protomaps.com` that answers range requests, for the project's area with a five kilometre margin down to zoom 14. The worker reads only the ranges the box needs, keeps the result in the `map-extracts` bucket and writes its size, digest and build date on the project's row; `GET` on the same path, for every member, streams the file once it is ready, answers 202 with the state while it is being made, and 409 with the reason when the attempt failed. A map younger than a month that covers the area is kept; `force` cuts again. The bundle names the map's state. A park-sized area at zoom 14 is a few tens of megabytes; `MAP_EXTRACT_MAX_ZOOM`, `MAP_EXTRACT_MAX_BYTES` and `MAP_EXTRACT_SOURCE` (a build pinned by URL, or a file for a server without internet) are the settings. The tiles are OpenStreetMap's, under the ODbL, built by Protomaps; Protect Go's map says so. Satellite imagery stays online: its terms do not allow caching.

## What the app gives Protect

The card's files, exactly as read, through `POST /devices/{id}/offload-files`, the same upload the station's device page makes. Protect decodes them, attributes the records as of their record time, and refuses a file it already holds by its content digest and a frame it already holds by its hash, so a card read in the field and uploaded later costs nothing twice.

## What never travels

No decoded row, no master key (Protect holds none, decision D327), and for now no notes or edits made offline. Should people need to record things in the field that must reach Protect, Protect Go's plan parks an append-only outbox for it.

## Still to come

Protect Go's own pages for the bundle, the cards and the upload (Protect Go's phase 2); on this side, nothing is open.
