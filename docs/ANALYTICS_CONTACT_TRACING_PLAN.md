# Contact tracing: who met whom, from Bluetooth and from positions

Design for phases 30 and 31, written on 2026-09-18 from Tim's ask and from the OpenCollar
protocol research (`docs/devices/opencollar-protocol-research.md`, sections 3.7 and 3.9).
Decisions D252 to D256.

Two devices are in contact when one saw the other, or when both were in the same place at the
same time. The first is what an OpenCollar reports itself; the second is what any two tracked
things tell us through their fixes. The module treats them as two kinds of evidence for one
question, so a pair seen by both is stronger than a pair seen by either.

## 1. What the device actually reports

This is the part that decides everything else, so it is written out before the design.

An OpenCollar with Bluetooth scanning on sends two kinds of message. Both are already stored as
source events today and neither is decoded into anything a query can reach: ports 7 and 11 sit
in the driver's `NOT_CANONICAL_PORTS`.

**Port 11, message 0xFA, a single scan.** A scan timestamp, then one four byte record per
device seen: three octets of the address and the RSSI. Up to 20 devices per scan. When more
results exist than fit one LoRaWAN payload the firmware writes them all to flash but sends only
the first message, so the air gives a truncated view and the flash log the whole one.

**Port 7, message 0xF9, the aggregated scan.** Nine bytes per record: the same three octets, the
best RSSI, a count of sightings, and the time of the strongest sighting. At most five records per
message out of a buffer of twenty, and the buffer is cleared when the message is composed.

Three things follow, and each one shapes the module:

1. **The address is three octets, not six.** Tim's note said the last six bytes; the firmware
   sends `bt_addr.val[0..2]`, the three least significant octets, which the reference decoder
   prints as `val[2]:val[1]:val[0]`. Three octets is 16.7 million values. Within one project's
   few hundred collars a collision is unlikely; across a large server it stops being unlikely,
   which is why D254 marks an ambiguous match rather than guessing.
2. **Scanning is off unless somebody turns it on.** `ble_scan_interval` (id 28) and
   `ble_scan_aggregated_interval` (id 29) both default to 0, meaning disabled. Protect already
   knows both per device from the settings work of D228 to D231, so the module can say which
   devices could have reported contacts at all, which is the difference between "they never met"
   and "we were not looking".
3. **The default filter already looks for our own devices.** `ble_scan_filter` (id 30) defaults
   to 1, the Smart Parks manufacturer id. So the common case is a collar that sees only other
   Smart Parks devices, which is exactly the case where an address resolves to a device we know.
   Filter 0 sees everything, 3 sees phones. The module reports the filter per device, because a
   contact count means something different under each.

There are no recorded scan payloads in the repository. The driver will be checked against the
vendored reference decoders with frames built for the purpose, as the AWT driver was, and the
first real scans are the true test. That is the reason for building the core half first (D256).

## 2. Decisions

| | |
| --- | --- |
| D252 | Contacts are a canonical record type of their own, a `device_contacts` hypertable beside positions, measurements, states and events. They are raw device output, so they belong in the core, not in the analysis subsystem's tables. |
| D253 | A sighting that resolves to no known device is kept as an unknown counterpart named by its three octets, not discarded. A collar meeting the same unknown address nightly is a finding, and the platform retains what it cannot identify everywhere else. |
| D254 | A sighting matching more than one device is marked ambiguous, named with its candidates, and left out of every pair figure; the run warns how many there were. A wrong contact between two named animals is worse than a missing one. |
| D255 | Bluetooth contacts and position proximity are two kinds of evidence in one module, never two modules, so a pair can be seen by both and read against itself. |
| D256 | The core half ships first and goes live: the driver, the address per device, the store and the device's Data tab. The module follows once real scans have been read. |

## 3. Phase 30, the core half

### 3.1 The driver decodes both scan messages

`shared/device_drivers/opencollar/__init__.py`: ports 7 and 11 leave `NOT_CANONICAL_PORTS` and
gain `_decode_ble_scan_single` and `_decode_ble_scan_aggregated`. Both yield a new
`DecodedContact` on `DecodedRecords`:

```
DecodedContact(time, address, rssi_dbm, sightings=1, best_at=None, scan_kind="single"|"aggregated")
```

The address is normalised to a lowercase zero padded `aa:bb:cc`. The reference decoder prints it
without zero padding (`toString(16)`), so the golden comparison normalises before comparing, the
way the AWT golden already handles that decoder's quirks.

Canonical time is the scan time for port 11 and the best sighting's time for port 7, both
device-origin, both subject to the clock-ahead rule that already guards positions.

An empty scan is a record of its own worth keeping: `ble_scan_report_zero_connections_found`
(id 71) makes the device send them, and "looked and saw nothing" is different from "did not
look". It writes no contact rows but does move a `last_ble_scan_at` on the device's current
state, so the module can tell the two apart.

### 3.2 Each device's Bluetooth address becomes known

The driver already decodes the device's own six octet address from port 31 message 0xFD into an
`identity` state, and nothing reads it. Three ways in, all of them writing the same place:

- the decoder, from that message;
- a `Request the Bluetooth address` command (`cmd_get_mac`, 0xB7), which is how that message
  comes to be sent at all, and which works over LoRaWAN, satellite or Bluetooth alike;
- a person, on the device page, for a device that cannot be asked.

The design first said the browser could read the address over WebBLE. It cannot: Web Bluetooth
deliberately exposes an opaque per-origin id and never a MAC address, so asking the device is
the route, and the browser's part is simply carrying the command.

The address is stored the way addresses are printed, `val[5]` first. The driver had been joining
`val[0..5]` in storage order since the message was first decoded, which nothing read and so
nothing caught. It matters here: a scan reports `val[0..2]`, the last three octets *as printed*,
so only an address written this way ends with what a neighbour will say about it.

Stored as `devices.ble_mac`, a column rather than an attribute, because the lookup is "which
device of this project ends with these three octets" and that wants an index. A functional index
on the last three octets serves the resolver.

`GET` and `PUT /devices/{id}/ble-address` with an audit row, project admins of the device's
current project or a server admin, the same rule as the battery type of D248.

### 3.3 The contacts store

Migration 0042: `device_contacts`, a TimescaleDB hypertable on `time` (0041 is the address column above).

| Column | Why |
| --- | --- |
| `time`, `device_id` | when, and which device did the scanning |
| `project_id`, `entity_id` | attribution at the record's device-origin time, the same rule as every canonical row (D103), so a contact belongs to whoever owned the collar then |
| `address` | the three octets as seen |
| `rssi_dbm`, `sightings` | the strength and, for an aggregated record, how many times |
| `contact_device_id` | the device it resolved to, null when unknown or ambiguous |
| `resolution` | `resolved`, `unknown` or `ambiguous` (D253, D254) |
| `scan_kind` | `single` or `aggregated`, since their meanings differ |
| `source_event_id`, `ingested_at` | provenance, as every canonical row carries |

Resolution happens in the decoder, at write time, against the devices of the observer's project;
`resolution` records what was decided so a later read never re-guesses. A device whose address
becomes known later leaves older contacts unresolved: a re-resolve action on the device page
fixes those, rather than a nightly job nobody asked for.

Retention and compression follow the other hypertables.

### 3.4 What a person sees in phase 30

A Contacts card on the device's Data tab: the counterparts of the last period with their
sightings, strongest RSSI and when they were last seen, unknown ones among them. It is
deliberately plain. It exists so the decoding can be read against reality before any analysis is
built on it, which is the whole point of splitting the work.

## 4. Phase 31, the module

### 4.1 Subjects, parameters, evidence

Subjects are entities, as in movement and grazing, with devices allowed the way device
performance allows them. The Bluetooth half needs OpenCollar devices; the position half works
for anything that reports a fix, so a run mixing an OpenCollar and a Traccar tracker gets
proximity for both and Bluetooth for one, and says so.

```
ContactParameters:
  bluetooth: bool = True          # use the reported sightings
  proximity: bool = True          # use the fixes
  max_distance_m: float = 100     # a proximity needs both within this
  max_time_s: float = 600         # and their fixes within this of each other
  min_rssi_dbm: int | None = None # a floor on sightings, off by default
  min_contact_s: float = 0        # ignore encounters shorter than this
```

The two limits Tim asked to be configurable are `max_distance_m` and `max_time_s`, with defaults
that say what they mean: a hundred metres is beyond GNSS error but within sight, ten minutes is
tighter than the usual fix interval.

### 4.2 Position proximity, and being honest about it

`primitives/proximity.py`: for each pair, merge the two fix series in time; for every fix of A
find B's fixes within `max_time_s`, take the nearest in time, and measure with the haversine in
`shared/geodesy.py`. Numpy over sorted arrays, a sweep rather than a cross product, so a pair
costs about the length of the two tracks. Pairs are bounded: `MAX_SUBJECTS_CONTACT` of 40 gives
780 pairs, which is the honest limit rather than a number that quietly melts the worker.

Three warnings the module must raise, because without them the figures mislead:

- **the fix interval dwarfs the window.** Two animals an hour apart in the record may have been
  a kilometre apart in between. When a subject's expected interval (D225 to D227 already knows
  it) is longer than `max_time_s`, the run says its proximities are coincidences of sampling.
- **accuracy against the distance.** A `max_distance_m` near the fixes' own accuracy is noise;
  the run compares the two and says so.
- **a network location is not a fix.** Proximity reads device fixes only, through
  `device_fix()`, exactly as the rules and the tracks do.

### 4.3 What comes out

The summary is a contact network: nodes are subjects, edges are pairs with their contacts,
total time, first and last, and which evidence saw them. Tables: pairs worst first, a per
subject row of how many others it met, and the unknown counterparts. Charts: contacts per day,
and a rose of the hour of day, since when animals meet is half the question.

The network itself is a new chart kind, `network`, drawn in the interface and in the PDF. It is
the one picture that makes a contact study legible and the only new visual the phase adds.

On the map, a contact has a place: the midpoint of a proximity, or the observer's fix nearest a
sighting. Those become a `contact` geometry kind, points sized by the number of contacts, so the
map answers where animals meet, which is usually a water hole.

### 4.4 What it is not

It does not infer transmission, and it says so in its limitations block. RSSI is not converted
to metres: that needs a calibration per device and enclosure that nobody has, so sightings are
banded by RSSI and the dBm is shown. A contact is evidence that two animals were near each
other, which is what the data can carry.

## 5. Tasks

- [ ] C1 the driver: ports 7 and 11 decoded, `DecodedContact`, the golden check against the
      reference decoders with built frames, the empty scan case.
- [ ] C2 `devices.ble_mac` with its three ways in, the endpoint, the device page control.
- [ ] C3 migration 0041, the `device_contacts` hypertable, the decoder writing and resolving,
      the re-resolve action.
- [ ] C4 the Contacts card on the device's Data tab.
- [ ] C5 the dev server: scanning turned on for a few collars, the first real scans read against
      the decoder. **The gate between the phases.**
- [ ] C6 `primitives/contacts.py` and `primitives/proximity.py` with tests on synthetic tracks.
- [ ] C7 the module, its parameters, the three warnings, the tables and charts.
- [ ] C8 the `network` chart kind and the `contact` geometry kind, in the interface and the PDF.
- [ ] C9 docs: an analytics guide, the device guide's scanning section, `DEVELOPERS.md`, the
      changelog; an ADR for the new canonical type.
- [ ] C10 release.

## 6. Exit criteria

Phase 30: a collar with scanning on reports contacts that appear on its Data tab within a fix
interval; an address of another collar in the project resolves to that collar by name; an
unknown address is kept and named by its octets; the settings tab shows the scan interval and
filter that produced them; a flash log upload of the same period yields the scans the air
truncated.

Phase 31: a run over two collars known to be together shows contacts from both kinds of
evidence, and the pair's total time is within a fix interval of the truth; a run with
`bluetooth` off gives proximity alone and the counts fall to what the positions support; a run
over an animal whose fix interval is longer than the time window carries the sampling warning; an
ambiguous address is counted in the warning and absent from the pairs; the PDF carries the
network and the pair table.

## 7. Later, not in these phases

Contact chains over time (A met B, B later met C), which is what tracing actually means and
wants the pairwise work proven first. Wi-Fi scans, which arrive in the same shape on ports 6 and
10 and would drop into the same store. The CMDQ records of port 15, which carry a cardiac
monitor's Bluetooth advertisement and are a different question. Alerting on a contact as it
happens, which belongs to the rules engine and not to an analysis run.
