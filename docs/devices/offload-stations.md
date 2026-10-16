# Offload stations

An offload station is a RangerEdge with a battery board and an SD card, standing where an
animal passes. A tracker that comes within range offloads the records of its flash log it has
not offloaded yet over LP0, a raw LoRa path of the OpenCollar Edge firmware (8.1, in test since
October 2026), and the station writes every frame it receives to its card. Several stations in a
home range cover an animal that never meets a LoRaWAN gateway: a CollarEdge on a pygmy hippo
fixing every 15 minutes is the case the feature was built for. A person carries the card to a
computer and uploads its files; Protect verifies and decrypts every frame with the tracker's
own keys, decodes the records through the pipeline it uses for a raw log file, and keeps the
station's reception beside each one. Phase 42, decisions D319 to D324; the design is in
[`LP0_OFFLOAD_PLAN.md`](../LP0_OFFLOAD_PLAN.md).

## What is on the card

The station keeps its files in numbered folders, `LOG_1`, `LOG_2` and so on, 64 files per
folder, named `STATIONEUI_timestamp[_NNN].jsonl`: the station's EUI in sixteen hex digits, the
Unix second of the first frame's reception, and a collision suffix. One file holds every frame
of every tracker whose session opened within a quarter of an hour of its first frame, so a file
is a window of reception, not a tracker or a visit. Each line is a JSON document in the shape a
LoRaWAN gateway forwards: the station's EUI as `gatewayEui`, and under `rxpk` the reception
time (`time`, and `tmst` in Unix seconds), the frequency, the data rate and coding rate, RSSI and
SNR, and the frame as base64 in `data`.

The frame is an ordinary LoRaWAN 1.0 uplink on port 29 addressed by the tracker's LP0 address,
encrypted with the tracker's application session key and signed with its network session key.
Its payload is the device's flash record stream, the same records a raw log file or a port 29
uplink carries, each with the time it was stored at. The station holds no keys and reads nothing
of the frame; the tracker's EUI is not on the card today, only its LP0 address. Firmware issue
772 (2026-10-15) sets the model Protect builds for: a deployment master key authenticates the
LP0 link, each tracker encrypts its records with its own unique credentials, the station stores
them as opaque bytes and may keep the tracker's EUI as routing metadata, and the backend decrypts
per device. A line that carries the EUI (`devEui`) names the unknown identity on Needs attention
with it; a line that names a frame format other than the ordinary LoRaWAN frame is refused by
name until Protect reads it.

A station that received a frame again, because its receipt was lost, writes it again; a tracker
whose records went unconfirmed at one station offloads them to the next. The firmware
deduplicates nothing and leaves that to Protect.

## Setting up

1. **The station.** Create the RangerEdge as a device if it is not one already (its serial
   number is its DevEUI, as for every OpenCollar; the station names the card's files after it)
   and assign it to the project. Then, on the Offload page under Network, **Make an offload
   station**: pick the device, give it a place (a click on the map, the coordinates, or the
   browser's position while standing at it) and it gets an entity of the type **Offload
   station** (under Equipment; the entity the device tracks today is kept), the place, and its
   row among the gateways of the built-in data source "Offload station files", linked to the
   device, so the Gateways page, the coverage layer and every tracker's Connectivity tab know
   it before its first card. The same can be done by hand: an Offload station entity with the
   device assigned, the place on the device page (the Place card), and the gateway row comes
   with the first card. A station does not move, so its place is never read from its data.
2. **The trackers.** On each tracker's device page, the **LP0 offload** card takes the LP0
   address and the two session keys (eight and twice 32 hex digits) that were provisioned on
   the device; "Use the device's reported values" takes the three from the device's own
   settings readback when it has sent one. The address becomes the tracker's identity on the
   offload station source; the keys are encrypted at rest and shown, behind Show, to whoever may set them; a viewer sees only that they are set. A tracker
   whose address another device holds is refused with that device's name. Project admins and
   operators (`devices:control`) set them, as they upload log files.
3. **A card.** On the station's device page, under Log files, upload one `.jsonl` file or a zip
   of the card's `LOG_*` folders. Each file becomes a row with the station as its device and the
   channel "station card"; the decoder reads it line by line, in batches, with the progress bar
   the raw log files have.

## What happens to a line

Every line is a delivery on the "Offload station files" source, addressed by the LP0 address in
the clear, with the station as the gateway that received it and the line's reception time as
the delivery time. The decoder then verifies the frame with the device's network session key,
decrypts it with its application session key, and decodes the records as the stored stream they
are: positions keep their fix time, clockless messages the time the device stored them.

- A frame of an address no device has is kept and listed on **Needs attention** as an unknown
  identity of type `dev_addr`. Link it to the device (or create one) and set the keys on that
  device; the retained frames are then decoded without a second upload.
- A frame of a device whose keys are not set fails with `CREDENTIALS_MISSING` and the file
  says how many such frames it holds; once the keys are set, "Decode again" on the file takes
  them up. Setting the keys on a device that already has retained frames hands them to the
  decoder at once.
- A frame that does not verify under the device's keys (a wrong key, a frame of another
  network) fails with `PAYLOAD_DECODE_FAILED` and is never guessed around. The frame carries
  the counter's low 16 bits; Protect tries the upper half zero, then the half the device was
  last verified at and the next, as a LoRaWAN receiver does across a rollover, and the MIC
  decides.
- A frame with the same address, counter and bytes as one stored in the last 30 days is the
  station's repeat after a lost receipt: it is stored as a duplicate of the first and not decoded
  again. A record that also came over LoRaWAN, from another card or over Bluetooth is one record
  with several deliveries, through the canonical key as for every path.
- A reception time before 2024, or after the upload, is a clock the station never set: the
  frame then carries no delivery time of its own and the records are judged against the upload
  time, as a raw log file's are. The line's time stays in the frame's metadata.

The file's row shows its frames, the records new and known, and for a card the frames
repeated, the frames of trackers not known yet and the frames of a tracker without keys; the
Offload station card on the station's page sums them over its files and lists the trackers the
station served in the last 30 days with their frames and signal.

## What a tracker shows

On a tracker's Connectivity tab, the "Offload station files" source has an **Offload** block:
the frames offloaded in the period, the repeats and the frames not verified apart, the records
new and known, the last offload, and every station that stored frames with its share and mean
signal, each a link to the station's device. The Traffic page lists every frame with its port,
counter, spreading factor, signal, the station and when the card was read; the source event
dialog shows the line as the station wrote it.

## The Offload page

Under Network, **Offload** shows the project's LP0 network on one page: every offload station
(its entity, its EUI, the cards uploaded with their frames, what it received in the last 30 days
and of how many trackers, the gist of its own last report, and whether its place is set), every
tracker with an LP0 address or with frames (its address, whether the keys are set and since when,
what the device itself reports as its address when that differs, the frames and stations of the
window, the last station, the last verified counter), and the addresses the stations received
that no device has, with the tracker's EUI when a line named it. The keys are never on this page;
they stay on the device page behind Show. The page lists and links: a station or a tracker is a
link away. The footer counts the devices of the project that have no address yet. Built before
a real card was read (Tim, 2026-10-16), to be tuned once there is data.

The one thing the page does itself is the station's setup (Tim, the same day: a guide and an
easy way to turn a device into a station belong in one place). **Make an offload station**
opens the dialog of step 1 above for project admins; a station with an Offload station entity
is listed from then on, with no card. The **Setup** column says what a row still misses: for a
station no entity, no place, not a gateway yet (each opens the dialog for that station), no card
yet (a link to its device page) and card not writable (its own report); for a tracker the
address and keys not set, or an address that differs from the one the device reports (links to
its device page). A complete row says so. **How to set up** unfolds the three steps on the
page; they show by themselves while the project has no station.

## The station's own report

Firmware 8.1 lets a station report on itself every `lp0_statistics_interval` seconds on port 23:
whether the card is in and writable, whether it is listening or in a visit, its uptime, the
frames waiting for the card, and 21 counters since it started (visits complete, partial,
cancelled and failed; frames received, saved, failed and dropped; bytes saved; card and reader
errors; channel and signal rejections; radio errors; reports made and lost). The report reaches
Protect over LoRaWAN when the station's send mask selects port 23, or on another station's card,
or inside the station's own port 29 records. The driver keeps it as the state `lp0_station` and
the figures as measurements in the `offload` category, so the health card shows an **SD card**
line (critical when the card is absent or not writable), the card errors and the frames waiting,
the Offload station card shows the report, and the rule template **Offload station without a
card** raises an alert on a station whose card is out. The observations a station could not make
are unknown, never false.

## Limits

A file of at most `LOG_FILE_MAX_BYTES` (64 MB), a zip of at most `LP0_ZIP_MAX_BYTES` (512 MB)
unpacked file by file, at most 32 records per frame by the wire format. The reception time is
believed from `LP0_EARLIEST_RECEPTION` (2024-01-01) on. Decoding runs at the decoder's pace,
about two frames a second on the dev server, with a commit every few seconds, so a full card
takes minutes and the row's bar says where it is.

## API

- `GET`, `PUT` and `DELETE /api/v1/devices/{device_id}/lp0-credentials`: the address and whether
  the keys are set; `PUT` takes `dev_addr`, `app_s_key` and `nwk_s_key`, or `from_device: true`;
  answers how many retained frames were handed to the decoder.
- `POST /api/v1/devices/{device_id}/offload-files` (multipart `file`, a `.jsonl` or a zip):
  the rows made, the members skipped with their reason, and the files named after another
  station.
- `GET /api/v1/devices/{device_id}/offload`: the Offload station card.
- `GET /api/v1/projects/{project_id}/offload`: the Offload page, for anyone who reads the project.
- `POST /api/v1/projects/{project_id}/offload/stations` (`device_id`, optional `entity_id` or
  `entity_name`, optional `latitude` and `longitude`): a device of the project becomes an offload
  station, or a station is completed; answers what was made (`entity_created`, `entity_kept`,
  `placed`, `gateway_created`). Needs `devices:write`, and `entities:write` for a new entity; the
  device's DevEUI must be known (its serial number or a `dev_eui` identity), else 409.
- `GET /api/v1/devices/{device_id}/connectivity`: the `offload` block per LP0 source.
- Uploading and setting keys need `devices:control` in the device's project, or server admin.
