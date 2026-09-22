# Cardiac monitoring

The Cardiac monitoring page under Analyze answers, for up to twenty-five animals of a project
over a period of at most a year: how their hearts were doing, at what times of day, and how much
of it was actually observed. It is the fifth analysis module (phase 34,
`docs/CARDIAC_MONITORING_PLAN.md`, decisions D282 to D285).

The readings come from a [LINQII cardiac tag](../devices/cardiac-monitoring.md) worn by the
animal and heard over Bluetooth by its collar, so every figure rests on two things going right:
the tag had something to say, and the collar was listening when it said it.

## What the collar heard comes first

The run answers coverage before it answers physiology, and the page shows it in that order. This
is not tidiness. **A quiet tag and a calm animal look the same in a heart rate chart**, and only
the coverage block tells them apart:

- **Heard**: how many sightings arrived, and, where the device has reported its
  `cmdq_reporting_interval`, roughly how many were expected. The interval bounds messages rather
  than sightings, so the share is treated as an order of magnitude and never reads above 100%.
- **With a cardiac reading**: the share of sightings that carried one. A tag that is heard every
  time and reads nothing is alive and not against the skin.
- **Longest silence**: the largest gap between sightings. A daily rhythm read over a period with
  a gap of days is missing whole days, and the run says so.

## The figures

- **Heart rate** per subject: the median, the usual range as the tenth and ninetieth percentile,
  and how many readings each rests on.
- **The daily rhythm**: the median heart rate per hour of the local day, on the project's
  timezone, as the module's one chart. Hours without a reading are absent rather than zero.
- **A resting heart rate**: a low quantile of the readings taken in the quiet hours. Both the
  quantile and the hours are settings of the run, shown with the result, because "resting" means
  nothing without them and the quiet hours of a rhino are not those of a bat. The default is the
  tenth percentile of 00:00 to 05:59. The quiet hours may wrap past midnight.
- **Heart rate variability** as RMSSD in milliseconds, where the firmware sends it.
- **Body temperature** from the tag, with the difference against the collar's own temperature
  where both exist. A tag that has come off the animal reads the air while the collar still reads
  the animal, so a large steady difference is worth seeing.

There is no map. A heart rate has no place on one, and the module stores no geometries.

## What it will not tell you

- **There is no normal range.** What a healthy heart rate is depends on the species, the age, the
  season and what the animal was doing a minute ago, and none of that is in this data. The module
  reports what was measured and never judges it.
- **Nothing is interpolated.** The tag is sampled on the collar's schedule, not the heart's, so
  every series is a sample of a fast signal by a slow observer.
- **Readings outside what a heart can do are dropped and counted.** The tag sends the R-R median
  in one byte, so the arithmetic reaches from about 23 to 6000 bpm; a value outside 15 to 300 bpm
  is a byte, not a heartbeat, and the run says how many it set aside.
- **The tag's activity, impedance and mode sum are not interpreted.** They are stored as the
  numbers the tag sent; the manufacturer does not publish what they mean.

## The form

- **Subjects**: entities picked by name, by group (with subgroups) or by entity type, at most
  twenty-five per run.
- **Period**: at most 366 days, with an optional comparison period of the same length before it.
- **Method**, folded away: the quiet hours and the resting quantile.

An estimate that finds no cardiac reading for the chosen subjects in the chosen period refuses
the run before it is queued and says where to look: the collar reports these readings only when
it is set to follow a tag.

## Warnings

Each one names the subject it is about:

| Code | What it means |
| --- | --- |
| `nothing_heard` | No cardiac tag at all in the period: the collar was not scanning, or the tag was out of range the whole time |
| `heard_without_readings` | The tag was heard and carried a reading none of those times |
| `heard_less_than_promised` | Fewer sightings than the reporting interval suggests, so the rhythm rests on the hours the collar happened to be listening |
| `long_silence` | The longest gap is over a day |
| `few_readings` | Too few usable readings to describe a distribution |
| `implausible_dropped` | Readings outside what a heart can do were set aside |
| `temperature_disagrees` | The tag's temperature sits far from the collar's own |
| `no_hrv` | The firmware predates 6.9.0 and sends no HRV |

## Where the data comes from

Measurements of the animal's own devices, read through the effective value, so a correction made
under Curation is the value the analysis sees. The reporting interval is read from the device's
settings table. Nothing else.
