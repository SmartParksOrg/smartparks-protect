# 0037. Cardiac readings on the scanning device, with only what is published derived

Date: 2026-09-22

Status: accepted

## Context

An OpenCollar Edge can follow a LINQII cardiac tag over Bluetooth and relay what it hears on port
15, message 0xFC. The driver has known that port and its record length per firmware since phase
15 (decision D100) and has thrown the data away ever since, because there was nothing in the
domain for it to be about. Phase 31 set it aside explicitly when it built the contact store: "the
CMDQ records of port 15, which carry a cardiac monitor's Bluetooth advertisement and are a
different question".

Two questions had to be answered before anything could be stored.

**Whose reading is it?** The tag is a second device. Phase 30 had just built the machinery for
one device hearing another: a contact, resolved through an address, attributed to the pair. It
would have been consistent to make the LINQII a device of its own and the readings its
measurements. But a contact answers "who met whom" between two tracked animals, and this is not
that. The firmware follows exactly one configured address, `cmdq_searched_mac_address`, set per
collar; a tag is not a neighbour that comes and goes, it is a sensor on the same animal. Treating
it as a device would mean a driver that decodes nothing, an onboarding path for hardware nobody
registers, an entity assignment that duplicates the collar's, and a resolver on the way in, all
to express a relationship the settings already state.

**What do the numbers mean?** The record holds eleven bytes of "important data" copied verbatim
out of the advertisement. Four of them can be read from published sources: the median R-R
interval is documented as tens of milliseconds, the HRV as the mean of squared successive R-R
differences, the temperature has a formula, and a temperature above zero is how the firmware's
own decoder judges that a reading happened. The other five, the mode sum, two activity figures,
active minutes and an impedance, are defined only in a private issue of the upstream firmware
repository. We can read their bytes; we cannot say what they are.

## Decision

**Cardiac readings are measurements of the scanning device** (D282). They are attributed like any
other measurement, so they land on the animal wearing the collar, and the tag's address stays
where the device already reports it: in the device settings table. Nothing new stores it, and the
readings carry the record type `cmdq` in their canonical key, so the history can be re-attributed
to a tag device later without decoding anything again, if a tag is ever read by two collars.

**Every field is stored, and only published arithmetic is derived** (D283). The ten decoder
fields go in under their own names in a new `physiology` metric category. Two derived values
stand beside them, because a reader wants a heart rate and not tens of milliseconds:
`heart_rate` in bpm, and `heart_rate_variability` in ms. The five fields without a published
meaning are stored as numbers and their registry descriptions say that their meaning is not
published, rather than a plausible-sounding guess that a reader would take for fact.

**A sighting without a reading writes no reading.** When the tag was heard and reported nothing,
no heart rate and no temperature are written at all. `cmdq_success` records that the sighting
happened and carried nothing.

**The cardiac study is a module of its own** (D284), and it answers what the collar heard before
it answers what the heart did.

## Consequences

The decoding is small: no migration for a table, no new canonical type, no resolver. The rules
engine, the Data explorer, exports, the map panels and the MCP see the readings as ordinary
measurements on the day the driver lands, with no work of their own.

A heart rate is attributed through the collar's assignments. If the collar is moved to another
animal while the tag stays with the first, the readings follow the collar and are wrong. That is
the same failure every other measurement of that collar has, it is visible in the assignment
history, and the alternative buys correctness here at the cost of machinery everywhere else.

Five stored metrics have no interpretation and the interface says so rather than hiding them.
When the manufacturer publishes their definition, the descriptions can be corrected in a
migration and every row already collected gains its meaning.

The derived `heart_rate` is a second number stored beside the one the tag sent. That is
deliberate duplication: `cmdq_rr_median` is the measurement and `heart_rate` is the reading, and
keeping both means the derivation can be checked against the reference decoder in the golden test
rather than trusted.
