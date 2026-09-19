# 0036. Contacts as a canonical record type, and a place a device does not report

Date: 2026-09-18

Status: accepted

## Context

An OpenCollar device can scan for Bluetooth advertisements around it and report what it heard:
per sighting the last three octets of the address and an RSSI, on port 11 one scan at a time and
on port 7 a window aggregated by the device. Until now Protect stored those messages as raw
frames and decoded nothing; the PWN project had 2,088 of them sitting undecoded.

A sighting is not a position, a measurement, a state or an event. It is an observation about a
second device, and its subject is the pair. Forcing it into an existing type loses the
counterpart: a measurement has a metric and a number, an event has a type and a place, and
neither has a room for "who". The pair is the whole point.

Three uses arrived at once, and they are not variations of one another. Collars worn by animals
scan for other collars, which is two animals meeting. Stationary RangerEdge readers scan for
EdgeTags on rabbits, which is a fixed point noticing that an animal came near it. And a collar
set to the widest filter scans for phones and other human-worn devices, which indicates a person
was there. What the platform can honestly say about a sighting differs in each: the first two can
name a device, the third never can, because a phone changes its advertised address every few
minutes by design.

The readers also showed what the real data does to a design. They report no positions at all —
turned off on purpose, because they do not move and reporting would spend power and airtime on a
fact already known. One of them has a clock 45 hours behind. The tags are heard weakly, between
-86 and -95 dBm.

## Decision

A contact is a canonical record type of its own: `device_contacts`, a hypertable beside
positions, measurements, states and events, carrying the scanning device, the time, the
advertised address, the RSSI, the number of sightings in the window, the scan kind, the device
clock offset and the resolution (decision D252). It is raw device output attributed like every
other canonical row, so it belongs in the core and not in the analysis subsystem's tables.

Resolution is three-valued and never guesses. Three octets are not an address: several devices
can share them. A sighting that matches exactly one known device is `resolved`; one that matches
none is `unknown` and is kept, named by its octets, because a collar meeting the same unknown
address nightly is a finding (D253); one that matches several is `ambiguous`, keeps its
candidates and is left out of every pair figure, because a wrong contact between two named
animals is worse than a missing one (D254). A device never resolves to itself. Resolution is
repaired in both directions when an address is later learnt, so history does not depend on the
order in which addresses were entered.

For that to work a device's own Bluetooth address must be known, so `devices.ble_mac` is stored
with an index on its last three octets, and can arrive from a frame the device sends (port 31,
message 0xFD), from a command Protect issues (`cmd_get_mac`), or from a person typing it.
Web Bluetooth cannot supply it: the browser exposes an opaque per-origin id and never a MAC.

A tag is a device like any other (D257): the EdgeTags get a driver that decodes nothing on
purpose, because they transmit only an advertisement and never speak to Protect. They exist as
devices so a sighting can name them, they can carry an entity, and they can hold a position.

Any device may be given a place by hand (D261). Setting one states that the device does not move:
`location_source` becomes `static`, the place goes on the current state at once, and nothing the
device sends moves it afterwards. A sighting by a placed device then writes a `proximity`
position for the device it heard, at the reader, with `CONTACT_POSITION_ACCURACY_M` as its radius
(D258) — a stated assumption, not a measurement. An estimate never displaces a newer device fix,
but a device that has never fixed at all takes the estimate whatever its location setting says:
that setting chooses between a fix and an estimate, and for a tag there is no fix to choose.

On a path that delivers as it happens, a record whose device time is further behind its delivery
than `CLOCK_BEHIND_TOLERANCE_SECONDS` is recorded at the delivery time, with the offset kept on
the row (D259). The tolerance is a generous 24 hours: a device out of coverage for a few hours
delivers late for good reasons, and only an implausible gap is the clock's fault.

A sighting under the phone filter counts as human presence and never as identity (D260).

## Alternatives considered

- A measurement with the counterpart in attributes: no index on the counterpart, no resolution
  state, and every query over pairs would be a JSON scan of a hypertable.
- An event per sighting: events are read by people and by the rules engine, and a scanning collar
  would drown both — one aggregated window is hundreds of rows.
- A table in the analysis subsystem: the analysis subsystem is optional and its tables are
  derived (ADR 0031). Contacts are what the device said; deleting an analysis must not delete
  them.
- Discarding unknown sightings: cheaper, and it throws away the only thing the widest scan filter
  can ever produce.
- Resolving an ambiguous address to the nearest candidate by position: plausible, and it invents
  a meeting between two named animals out of three octets.
- A separate record type for a static place: the `location_source` column already distinguishes
  where a position came from, and `static` is one more value in it.

## Consequences

The canonical set is five types, not four. Everything that enumerates them — the export
machinery, the data explorer, the retention policy, the MCP surface, the device Data tab, the
attribution repair — gains a case, and the ones that have not yet gained it are the work that
remains.

Three octets stay ambiguous forever in a large fleet: the ambiguous count is a number every
analysis run must report, not a defect to be eliminated. Full addresses could be obtained per
device to narrow it, and the EdgeTags already have theirs assigned by hand.

Resolution is stored, not computed at read time, so it can be stale: the re-resolve action exists
for that, and the decoder repairs both directions on every new address. A contact read before an
address was known will say `unknown` until it is repaired.

The clock rule applies to contacts on live channels and to the records of the scan that made
them, and stops there (decision D262, Tim, 2026-09-19). A position with the same implausible
offset keeps the time its device claimed: moving it would rewrite where an animal appears to have
been, which changes tracks, attribution and every analysis built on them, and the record would
say the animal was somewhere it was not. A device with a bad clock therefore files its fixes in
the past, visibly, rather than having them invented into the present.
