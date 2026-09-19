# Contact tracing

The Contact tracing page under Analyze answers, for up to forty subjects of a project over a period of at most a year: which of them were near each other, how often, for how long, where, and on what evidence. It is the fourth analysis module (phase 31, `docs/ANALYTICS_CONTACT_TRACING_PLAN.md`, decisions D252 to D261).

It is built on two kinds of evidence and never one, which is the whole design (decision D255):

- **Bluetooth sightings**: one device heard another and reported it. An observation. See [Bluetooth contacts](../devices/bluetooth-contacts.md) for how a sighting becomes a record.
- **Position proximity**: two subjects' own fixes put them close together at close to the same moment. An inference.

They fail in different ways, so the run keeps them apart and shows both. A pair found by both is solid. A pair found only by proximity rests on how often the animals report. A pair found only by Bluetooth was heard but never fixed together.

## What a contact is, and is not

A contact is **evidence that two subjects were near each other**. That is all.

It is not evidence that anything passed between them. This module infers no transmission and says so in its own limitations block, in the result, where a reader will see it. What to make of a contact is a question for somebody who knows the disease, the species and the season.

A signal strength is **never converted to metres**. Doing that needs a calibration per device, per antenna and per whatever stands between them, and nobody has one. A sighting's signal is banded — near, middling, far — and the dBm is carried through so a reader can judge for themselves.

## The form

- **Subjects**: entities picked by name, by group (with subgroups) or by entity type. At most forty per run, because every pair is compared with every other: forty subjects is 780 pairs, and the work grows with the square. A larger selection is narrowed to the first forty by name and the run says so.
- **Period**: at most 366 days, with an optional comparison period of the same length before it.
- **Bluetooth** and **Position proximity**: either can be switched off. Switching both off finds nothing, and the run says that too.
- **Distance** (`max_distance_m`, 100 m): how close two fixes must be to count as a proximity. A hundred metres is beyond GNSS error but within sight.
- **Time** (`max_time_s`, 10 minutes): how close in time the two fixes must be. Tighter than the usual fix interval.
- **Signal floor** (`min_rssi_dbm`, off): ignore sightings weaker than this. What it drops is counted and reported, never silently lost.
- **Shortest contact** (`min_contact_s`, 0): ignore encounters shorter than this.

## The three warnings

These are the point of the module as much as the figures are. Without them the numbers mislead, so they appear above the results and name the subject they are about.

| Warning | When | Why it matters |
| --- | --- | --- |
| The sampling is coarser than the window | A subject reported less often than the time window a proximity is judged in | Two animals an hour apart in the record may have been a kilometre apart in between. Its proximities are coincidences of sampling as much as of animals. |
| The distance is inside the fixes' own error | The distance asked for is no larger than the typical accuracy the subject's fixes claim | At that distance the receiver alone could put two animals together. |
| A network estimate is not a fix | Always, while proximity is on | Proximity reads the fixes the devices made themselves. A position the network estimated takes no part, however recent it is. |

The sampling warning measures **what a subject actually did**, not what its settings declare. A collar set to five minutes that manages an hour because the sky is poor would pass a check against its setting and fail reality, and it is reality that decides whether a proximity means anything.

## What comes out

**The network** is the picture: subjects as nodes sized by how many contacts they had, pairs as edges thickened by how often they met and dashed when only one kind of evidence saw them. A subject that met nobody stays on the picture as a small unattached dot — leaving it out would answer "who met" instead of "who met whom", and the animals that met nothing are often the finding. On screen the layout can be dragged and roamed; in the PDF it is a circle in the subjects' own order, so a report filed this month can be held against last month's and the same animal is in the same place.

**The pair table**, the pairs that spent longest together first: the two names, the period, how many contacts, how many hours, which evidence saw them, the sightings behind it, the signal band, the closest the fixes came, and when it started and ended.

**The subject table**: how many *others* each subject met, how many contacts that came to, and how many hours. Meeting one animal ten times is not the same as meeting ten animals, and this is the column that separates them.

**The charts**: contacts per day, and a rose of the hour of day, since when animals meet is half the question. Both count on the project's own clock, as the movement and grazing modules do.

**The map**: a point where each pair met, sized by how often. For a pair the fixes found it is the midpoint of the two, because neither of them is the place and the meeting is — usually a water hole, which is the answer a map gives that a table cannot. For a pair only a sighting found it is the place of the device that did the hearing: exactly, when that device stands on a post with a place set by hand, and its nearest fix when it was walking about (decision D261). The device that was heard has no say, since its position is what the sighting was meant to establish. Clicking a point gives the contacts, the hours, the first and last time and which evidence saw them. The "Where pairs met" chip switches the layer.

**What was set aside** is in the summary and not hidden: sightings whose neighbour no device of the project matches (an unknown neighbour is a real finding, decision D253, but it is not a pair) and sightings whose three octets could be more than one device, which are deliberately in no pair figure at all (D254).

## What the module reads

Sightings come from `device_contacts`, resolved on the way in and never re-guessed, and only those whose counterpart resolved to a device that was carrying one of the chosen subjects at that moment. Proximity reads `positions` through the same `device_fix()` the rules and the tracks use, so a curated or invalidated fix is treated identically everywhere.

Both are attributed at the record's own time (decision D103): a collar that changed animals last month met whoever wore it then. The one exception is the place of a fixed reader, which is read from the device the subject is on today: a post does not change animals.

## Switches

The same as the other modules: `ANALYSIS_MODULES` (which now carries `contact_tracing` by default) on the server, `analysis_modules` in the project's settings; `analysis:run` starts runs, `project:read` sees them within the scope, `exports:create` makes the report.
