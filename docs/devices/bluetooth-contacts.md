# Bluetooth contacts

An OpenCollar device can listen for the Bluetooth advertisements around it and report what it
heard. Protect stores each sighting as a **contact**: a record of its own beside positions,
measurements, states and events, carrying who was listening, when, what address was heard, how
strong the signal was, and what the address was found to mean (ADR 0036, decision D252).

The same feature is used in three ways, and what a contact means differs in each:

| What is listening | What it hears | What a contact says |
| --- | --- | --- |
| A collar on an animal | other collars in the project | two animals were within Bluetooth range of each other |
| A reader on a post | tags on animals that carry no GNSS | an animal came near a known place |
| A collar or a reader | phones and other devices people carry | somebody was there |

## What a device actually reports

A scan reports the **last three octets** of each address it heard, not the whole address, and a
signal strength in dBm. Three octets are not an identity: several devices can end with the same
three. Protect resolves each sighting once, on the way in, and says which of three things it
found:

- **Resolved** — exactly one device in the project has an address ending in those octets. The
  contact names that device and the entity it was on.
- **Unknown** — no device in the project matches. The sighting is kept anyway, named by its
  octets (decision D253): a collar that meets the same unknown address every night is a finding,
  and it becomes a name the moment somebody records whose address it was.
- **Ambiguous** — more than one device matches. The sighting keeps the list of candidates and is
  counted in no pair figure (decision D254). A wrong contact between two named animals is worse
  than a missing one.

Resolution is scoped to the project: three octets are unique enough among a few hundred collars
and not among tens of thousands.

## Making a device resolvable

A device is only ever named in somebody else's scan if Protect knows its own Bluetooth address.
The device page has a **Bluetooth address** control with three ways in:

- the device reports it by itself (port 31, message 0xFD);
- **Ask the device** sends `cmd_get_mac` and the answer arrives as a frame, over any route;
- a person types it, which is how the EdgeTags are recorded, since their addresses were assigned
  by hand and they never speak.

Web Bluetooth cannot supply it: a browser exposes an opaque per-origin identifier and never a MAC
address.

Recording an address **repairs the past**. Sightings stored as unknown while the address was not
known are resolved to the device, in both directions: if a second device turns out to share the
same three octets, readings that had confidently resolved to the first become ambiguous again.

## Reading the list

The device's **Data** tab has a **Bluetooth contacts** card: the last week's neighbours grouped,
with the number of contacts, the sightings behind them, the strongest signal and when it was last
seen, and above the list the device's scan settings.

Those settings are the important part. An empty list means "it met nobody" **only if the device
was looking**, and Bluetooth scanning is off until somebody turns it on. The card says which of
three it is: scanning with this interval and this filter, scanning off, or nothing known about
it. The filter matters as much as the interval, because a count under "Smart Parks devices"
means something entirely different from a count that included every phone that walked past.

The filters come from the firmware: every device, Smart Parks devices, one manufacturer, phones.

On the live map, a device's panel and the panel of the entity it is on show **Bluetooth
sightings** of the last 24 hours when the device reports scans at all. The figure unfolds a chart
of how much the device hears, over a day, a week or a month, the way the battery does, with a
link to the list underneath. Every scan window leaves one `ble_contacts` measurement — the
devices it saw — so the same figure is available in the data explorer, on a dashboard and to a
rule. A scan that saw nothing is a **zero**; a gap in the line means the device was not looking
at all, which is a different thing.

A device whose position came from a sighting carries a **Heard by** row naming the reader, as a
link to it on the same map. That is the point of such a position: the animal is there because a
named device heard it.

## A tag is a device

The EdgeTags used in the PWN project are small Bluetooth tags on rabbits. They advertise an
identifier and nothing else: no uplink, no position, no battery reading.

They exist in Protect as devices with the `ble_tag` driver, which decodes nothing on purpose,
and they carry an entity like any other device (decision D257). Being heard is the only sign a
tag is alive, so a sighting moves its **last seen** time, and its own Bluetooth contacts card
shows only what heard it.

## A reader with a place puts an animal on the map

A device that does not move can be given a place by hand, on its page, under **Fixed position**
(decision D261). That is how the PWN readers work: their positions are known, so reporting them
would spend power and airtime on a fact nobody needs.

Setting a place states that the device does not move. Its position becomes that place, its
location source becomes **static**, and nothing the device sends moves it afterwards. The live
map's Position row says "fixed place" so nobody reads it as a fix. Clearing the place gives the
device back to whatever it reports.

Once a reader has a place, a sighting by that reader also writes a position for the device it
heard, **at the reader** (decision D258). It is an estimate with a radius
(`CONTACT_POSITION_ACCURACY_M`, 100 m by default), not a fix: Bluetooth range depends on the tag,
the antenna and what stands between them, so the radius is a stated assumption. For a rabbit
wearing a tag and no GNSS it is the only position there will ever be.

Setting a place also repairs the past: the sightings that reader already made get their
positions, which matters because a reader is put up first and measured later. The same happens
from the other side, when a device's address is recorded: its sightings stop being unknown
neighbours and the positions they earned are written then. Neither writes anything twice.

An estimate never displaces a newer fix a device made itself. A device that has never fixed at
all takes the estimate whatever its location setting says: that setting is there to choose
between a fix and an estimate, and there is no fix to choose.

## Phones are presence, never identity

Under the phone filter, a sighting says that something human-worn was within Bluetooth range and
nothing more (decision D260). Protect never resolves such a sighting to a device, even when the
octets happen to match one, because a phone's advertised address is random and a match would be a
coincidence.

Each scan window that heard anything raises one **Human presence** event on the device, carrying
how many addresses were heard and the strongest signal, and a `human_presence` measurement of 1
so a rule can be written on it ("tell me when somebody is at the north gate"). One event per
window, not one per address: one person carries a phone, a watch and a pair of earbuds.

The number of addresses is **not** a number of people, and two sightings can never be known to be
the same phone: addresses rotate every few minutes by design. The contacts card says so above the
list whenever the filter is the phone one.

## Clocks

Some OpenCollar firmware sets the device clock wrongly; one PWN reader is 45 hours behind. On a
path that delivers as it happens, a contact whose device time is further behind its delivery than
`CLOCK_BEHIND_TOLERANCE_SECONDS` (a day) is recorded at the delivery time instead, with the
device's own claim and the offset kept on the row (decision D259). A log file carries the past on
purpose and is never moved this way, and a device out of coverage for a few hours delivers late
for good reasons, which is why the tolerance is generous.
