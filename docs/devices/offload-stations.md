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

Where the people who collect a card have no connection for days, [Protect Go](protect-go.md), a separate app on a laptop, reads the card with Protect's own code and uploads its files later.

## What is on the card

The station keeps its files in numbered folders, `LOG_1`, `LOG_2` and so on, 64 files per
folder, named `STATIONEUI_timestamp[_NNN].jsonl`: the station's EUI in sixteen hex digits, the
Unix second of the first frame's reception, and a collision suffix. One file holds every frame
of every tracker whose session opened within a quarter of an hour of its first frame, so a file
is a window of reception, not a tracker or a visit. The card's root may also hold `sdcheck.bin`,
the 64-byte file the station writes and reads back to test its storage; it is not data, and the
upload of a zip leaves it aside. Each line is a JSON document in the shape a
LoRaWAN gateway forwards: the station's EUI as `gatewayEui`, and under `rxpk` the reception
time (`time`, and `tmst` in Unix seconds), the frequency, the data rate and coding rate, RSSI and
SNR, and the frame as base64 in `data`.

The frame is an ordinary LoRaWAN 1.0 uplink on port 29 addressed by the tracker's LP0 address,
encrypted with the tracker's application session key and signed with its network session key.
Its payload is the device's flash record stream, the same records a raw log file or a port 29
uplink carries, each with the time it was stored at. Since LP0 version 5 (firmware issue 772,
2026-10-16) the tracker builds that frame itself under its own keys before the LP0 transfer, a
deployment master key authenticates the LP0 link alone, and the station stores the frame
unchanged without any device key; the master key never reaches the card and Protect never needs
it. A v5 line adds an `lp0` object beside `rxpk`: the protocol `version` (5), the tracker's
`source_eui` as the station learnt it in discovery, and the transport's `session`, `window` and
`slot`. Files of earlier station firmware have no `lp0` object and read the same way. The
source EUI names an unknown address on Needs attention; when it contradicts the EUI of the
device the address belongs to, the frame is refused rather than decoded (decision D327), since
the registry, not the card, is then wrong somewhere. A line whose `lp0.version` Protect does
not know is refused by name until Protect reads that version.

A station that received a frame again, because its receipt was lost, writes it again; a tracker
whose records went unconfirmed at one station offloads them to the next. The firmware
deduplicates nothing and leaves that to Protect.

## Setting up

1. **The station.** On the Offload page under Network, **Make an offload station**. Its first
   step is the device: one of the project's, or a new one made right there when the RangerEdge
   is not a device yet (decision D326): over Bluetooth the device gives its own name, DevEUI
   (the serial of every OpenCollar, which the station names the card's files after), hardware
   and firmware; by hand you type the name and the DevEUI; the device type is an OpenCollar type of the server, asked only when there are several. A server admin may also create it
   under Server admin, Devices, and assign it to the project. Then, in the same dialog: pick the device, give it a place (a click on the map, the coordinates, or the
   browser's position while standing at it) and it gets an entity of the type **Offload
   station** (under Equipment; the entity the device tracks today is kept), the place, and its
   row among the gateways of the built-in data source "Offload station files", linked to the
   device, so the Gateways page, the coverage layer and every tracker's Connectivity tab know
   it before its first card. The same can be done by hand: an Offload station entity with the
   device assigned, the place on the device page (the Place card), and the gateway row comes
   with the first card. A station does not move, so its place is never read from its data.
2. **The trackers.** A tracker added over Bluetooth in that dialog brings its LP0 address and
   keys with it, read from the device and saved on it in the same call (source: the device).
   Otherwise, on each tracker's device page, the **LP0 offload** card takes the LP0
   address and the two session keys (eight and twice 32 hex digits) that were provisioned on
   the device; "Use the device's reported values" takes the three from the device's own
   settings readback when it has sent one. The address becomes the tracker's identity on the
   offload station source; the keys are encrypted at rest and shown to whoever may set them, each on its own line named as the LoRaWAN variable (AppSKey, NwkSKey), masked until the eye beside it is pressed; a viewer sees only that they are set. A tracker
   whose address another device holds is refused with that device's name. Project admins and
   operators (`devices:control`) set them, as they upload log files.
3. **A card.** On the Offload page, **Upload SD card files** takes one or more `.jsonl` files or
   zips of the cards' `LOG_*` folders, of any number of stations at once, and puts each file
   with the station named in it: the EUI in the file's name, matched to a device of the project
   by serial number or DevEUI identity (`POST /projects/{id}/offload-files`, `devices:control`;
   Tim, 2026-10-18: the person who collected the cards should not have to find each station's
   page). A file of an EUI no station of the project has is kept back and the EUI is named: the
   page then offers to make the station, with its label name and the EUI as serial, set it up
   and upload the files again to it (decision D343), so nothing is guessed and nothing is lost. A station's device page takes its own
   files too, under Log files. Each file becomes a row with the station as its device and the
   kind "SD card"; the decoder reads it line by line, in batches, with the progress bar the raw
   log files have. In every log files list the kind of each file is on show, SD card, raw log or
   browser sync, since a station has raw logs beside its card files.

## A tracker the card knows before Protect does

A card often arrives before every tracker on it is a device in Protect (decision D338). Its frames
land under **Unknown devices** on the Offload page, with the tracker's DevEUI when the
station wrote it (a v5 card). The plus on such a row, first in the row so a phone reaches it, makes the device: a new one, with
the LP0 address, the DevEUI as serial and a name filled in, read over Bluetooth, which brings the
name, the DevEUI and the keys from the device itself, or typed; or a device of the project that
takes the address. The keys are not on the card, so they may follow: the address alone makes the
frames the device's, they fail plainly for want of keys and the Setup column says "keys not set";
the keys, set under LP0 offload on the device page, hand the waiting frames to the decoder at
once. The DevEUI is never guessed. The name defaults to the DevEUI; the form asks for the label
name (SP…), since the keys are looked up by it anyway. Protect Go lists the unknown trackers of
the cards it read and hands one over to this page with `?add=<address>`.

When a tracker is added after its cards were read, the decoder walks the frames that waited for it
and sums the card files it touched anew (decision D342), so the Files section shows the records,
the period and the figures per tracker without a second decode. The stations' figures on the
page count by arrival at Protect, the upload of a card, not by the station's clock.

With the newer firmware a station also records the status reports of the other stations in
range, so an unknown device may be a station rather than a tracker (decision D341). The ports a
frame carries in the clear tell them apart before anyone has the keys: a station's own status
report travels on port 23, a tracker's stored stream on port 29. The Unknown devices table says
what each looks like, and the add dialog opens on that choice, a tracker or an offload station;
a station is set up at once, with its entity and its gateway row, and its place is set on its
page afterwards.

Once such a device is heard on a LoRaWAN server, its DevEUI identity links itself to the device
whose serial it is (decision D339), so nothing waits on Needs attention for it. When the network
names it otherwise, Needs attention's **Names** lists the pair, to rename the device or keep its
name; a kept name is not raised again until the network's changes.

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
  network) fails with `PAYLOAD_DECODE_FAILED` and is never guessed around. The counter in the
  frame is the whole counter the tracker signed with (its 16-bit allocator, upper half zero),
  so it verifies as it stands; Protect also tries the upper half the device was last verified
  at, as a LoRaWAN receiver does, and the MIC decides. After 65536 frames the tracker's counter
  wraps and reuses its keystream under unchanged keys; that is a limit of the firmware, which
  Protect records (`f_cnt32` on the frame) and does not work around.
- A tracker made today holds its project from today, while its card carries weeks of history.
  When the device has had one project assignment ever, that assignment is moved back to the
  earliest record the file brought once the file is decoded, and so is its entity assignment
  when the device and the entity never had another; the records then belong to the project and
  the animal without a hand on the window (decision D330). The file's properties say what moved
  and to when. A device with an earlier membership or a gap keeps its start, since the gap
  means something; the device page offers the move by hand, as before.
- A frame whose station-given tracker EUI (`lp0.source_eui`) is not the EUI of the device its
  address belongs to fails with `DEVICE_IDENTITY_AMBIGUOUS` and lands on no device: either the
  address is set on the wrong device, or a serial is wrong. Correct the registry, then "Decode
  again".
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
they stay on the device page, masked until shown. The page lists and links: a station or a tracker is a
link away. **Upload SD card files**, in the page's header, takes the files of any number of
cards and puts each with its station (step 3 above). The Stations section is a list or a map,
switched at its heading and remembered per person (Tim, 2026-10-18): the map shows every station
with a place as Protect's station marker with its name, a press on a marker opens the station's
device page, and stations without a place are counted under the map (the overview carries each
station's `location` as a GeoJSON point). The Trackers section has the same switch: its map
shows each tracker's last known position with its entity's icon and its name, a press opens the
live map on the tracker (the overview carries `last_position`, `last_position_at` and
`entity_icon` per tracker), and a pin beside each tracker's name in the list does the same.

**Static or mobile** (decision D336, Tim, 2026-10-18). A station is static by default: it stands
where a person placed it (decision D261), and the Setup column asks for that place. A station
that travels, on a vehicle or with a ranger, is made mobile, in the station dialog or on its
device page ("Make it mobile", `devices:write`): it then reports its position itself, like a
tracker, a place set by hand is taken away, the Offload page marks it with a badge, its row
says "no position yet" until a fix arrives, and the stations map draws it at its last known
position with the time of that fix. The choice lives on the station's gateway row
(`attributes.mobility`), so `POST /projects/{id}/offload/stations` with `mobile` alone switches
it; the overview's stations carry `mobile`, `location` and `location_at`. A mobile station's
row on the Gateways page keeps the location it had; the coverage layer does not follow it yet. The footer counts the devices of the project that have no address yet. Built before
a real card was read (Tim, 2026-10-16), to be tuned once there is data.

The one thing the page does itself is the station's setup (Tim, the same day: a guide and an
easy way to turn a device into a station belong in one place). **Make an offload station**
opens the dialog of step 1 above for project admins, whose first step adds the RangerEdge as a
device of the project when it is none yet, by hand or read over Bluetooth with its LP0
credentials (decision D326), and carries on with it; a station with an Offload station entity
is listed from then on, with no card. The **Setup** column says what a row still misses: for a
station no entity, no place, not a gateway yet (each opens the dialog for that station), no card
yet (a link to its device page) and card not writable (its own report); for a tracker the
address and keys not set, or an address that differs from the one the device reports (links to
its device page). A complete row says so. **How to set up** unfolds the three steps on the
page and hides them again; they are hidden until asked for.

## The project's files

The Offload page ends with **Files** (Tim, 2026-10-17): every file uploaded for the project's devices in one place, the SD card files of the offload stations, the raw logs and the browser syncs, newest first, as the device page's log files explorer shows them, with the device as a column and a filter, a search box over every text of a row, and a click on a header to sort. A click on a file opens its properties; the device's name opens its page, where files are uploaded. The listing is `GET /projects/{id}/log-files` (project read; the caller sees the files of the devices it may see), each row with its `device_name`, a page of 200 at a time (`limit`, `before` the last row's `uploaded_at` for the next, `device_id` for one device), so a project with years of cards never arrives as one wall; the page shows "Load more" while there is more.

## The station's own report

Firmware 8.1 lets a station report on itself every `lp0_statistics_interval` seconds on port 23:
whether the card is in and writable, whether it is listening or in a visit, its uptime, the
frames waiting for the card, and 21 counters since it started (visits complete, partial,
cancelled and failed; frames received, saved, failed and dropped; bytes saved; card and reader
errors; channel and signal rejections; radio errors; reports made and lost). Since report
version 2 it also carries the card's size in whole MB and its free share in whole percent
(unknown until the reader's units are verified in the firmware), and since version 3 (the
firmware of 2026-10-20) two more observations: that a completed card check found no card, and
that a storage fault is latched until the station's own test of the card passes again; a
station in that state offers no offloads and sends a report at once. The report reaches
Protect over LoRaWAN when the station's send mask selects port 23, or on another station's card,
or inside the station's own port 29 records. The driver keeps it as the state `lp0_station` and
the figures as measurements in the `offload` category, so the health card shows an **SD card**
line (critical when the card is absent, faulted or not writable), an **SD card free** line
(warning under 10 %), the card errors and the frames waiting, the Offload station card shows
the report with the card's space, the Offload page's Setup column says "card not usable", and
the rule template **Offload station without a card** raises an alert on a station whose card
is out or faulted. The observations a station could not make are unknown, never false, and a
report version Protect does not know is refused by name.

## Demo data

`uv run scripts/lp0_demo_cards.py --project-id <id> --email <ops> --password <secret>` fills a
project with a month of synthetic LP0 traffic (`--days`; `--until YYYY-MM-DD` ends the data at
that day instead of the run's hour, so a second set covers another period and is new to the
server; `--out DIR` writes the zips and the cards' folders for Protect Go or an SD card instead
of uploading) to try the page and the import before a real card
exists (Tim, 2026-10-16): three RangerEdge stations (SP050101 to SP050103) around a pygmy hippo's
range in the Gola Rainforest, each an Offload station entity with its place and its own LP0
credentials, and a CollarEdge (SP100001) on a hippo entity. The collar fixes every 15 minutes
(port 2), reports its status hourly (port 4) and offloads once a day to the station of the day;
each station reports itself hourly on port 23 into its own card. The cards are LP0 v5 files, one
zip per station, uploaded on the station's device and decoded by the server in the background
(about a quarter of an hour on the dev server). The keys are synthetic, derived from `--seed`,
and never printed; a re-run finds the devices by serial and the server refuses a card it holds.
`--out DIR` writes the zips and uploads nothing.

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
- `POST /api/v1/projects/{project_id}/devices` (a device as `POST /devices` takes it, status
  active by default, plus optional `lp0` with `dev_addr`, `app_s_key`, `nwk_s_key` and `source`
  person or device): the device made and assigned to the project from now, its LP0 credentials
  set at once; `devices:write`; a serial or an LP0 address another device holds is 409.
- `GET /api/v1/device-types/{device_type_id}/driver-catalog`: the driver's protocol catalogue
  by device type, for reading a device over Bluetooth before it exists; `?firmware=` names the
  version the device's status reported, which picks the catalogue's generation (a RangerEdge on
  firmware 8 addresses its settings by family and id, decision D346).
- `POST /api/v1/projects/{project_id}/offload/stations` (`device_id`, optional `entity_id` or
  `entity_name`, optional `latitude` and `longitude`): a device of the project becomes an offload
  station, or a station is completed; answers what was made (`entity_created`, `entity_kept`,
  `placed`, `gateway_created`). Needs `devices:write`, and `entities:write` for a new entity; the
  device's DevEUI must be known (its serial number or a `dev_eui` identity), else 409.
- `GET /api/v1/devices/{device_id}/connectivity`: the `offload` block per LP0 source.
- Uploading and setting keys need `devices:control` in the device's project, or server admin.
