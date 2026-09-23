# Cardiac monitoring

The Cardiac monitoring page under Analyze answers, for up to twenty-five animals of a project
over a period of at most a year: how their hearts were doing, at what times of day, and how much
of it was actually observed. It is the fifth analysis module (phase 34,
`docs/CARDIAC_MONITORING_PLAN.md`, decisions D282 to D285), and since phase 35 it reads the whole
record the tag sends: the heart rate, its variability, the implant's activity and its temperature
(decisions D287 to D290).

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

The four metrics are read the same way, each in three parts of the day:

- **Day and night** split at the horizon, by the sun at the animal's mean position in the period,
  so they hold at any latitude and in any season. An animal without a position in the period
  takes its current one; one with neither falls back to 06:00 to 18:00 on the local clock, and a
  warning says so.
- **Resting** is the run's quiet hours (00:00 to 05:59 by default), which overlap the night: it
  answers how low the animal goes, not a third of the day.

The metrics:

- **Heart rate** in beats per minute: the median, the usual range as the tenth and ninetieth
  percentile, how many readings it rests on, and a **resting heart rate**, a low quantile of the
  quiet hours (the tenth percentile by default; both are settings shown with the result).
- **Heart rate variability** as RMSSD in milliseconds, where the firmware sends it.
- **Activity**: the implant's own accelerometer score, unitless from 0 to 255, high while the
  animal is awake and moving and low in its sleep. It is not the device's own activity. The implant
  writes a 0 once an hour by a fault of its own and a real score never falls that low, so every 0
  is set aside and counted rather than pulling the night down.
- **Body temperature** from the tag, with the difference against the collar's own temperature
  where both exist. A tag that has come off the animal reads the air while the collar still reads
  the animal, so a large steady difference is worth seeing.

And the views, a metric to a row on the page and the same in the PDF report:

- **By hour of the day**: the median per hour of the local day, on the project's timezone. Hours
  without a reading are absent rather than zero.
- **By day, night and resting**: a box plot per animal, the middle half as the box, the median as
  its line, the whiskers at the furthest readings within one and a half boxes.
- **Per day, by day and by night**: the day and the night median of every date across the
  period, the night dashed, so a change of state shows as a step.
- **Restless minutes per night**: the readings at night whose activity is above the threshold
  (100 by default, a setting), each standing for one report step. A night heard fewer than twelve
  times is left out rather than read as a quiet one. A night is named by the evening it started.

### Before and after an event

An optional **event** on the form (an animal leaving its group, a capture, the start of a
drought) splits the period. Every metric gets its median before and after in the day, the night
and the resting hours, the difference, and each side's middle half; the per-day charts and the
restless nights mark the moment. It is descriptive: no model and no p-value, because one animal's
record is not a sample. A side with fewer than twelve readings gives no difference. An event
outside the period is refused.

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
- **The tag's activity maximum, active minutes, impedance and mode sum are not interpreted.**
  They are stored as the numbers the tag sent.
- **Day and night follow the sun, not the animal.** A nocturnal species is still read by the sun;
  the parts of the day say when, not what the animal was doing.

## The form

- **Subjects**: entities picked by name, by group (with subgroups) or by entity type, at most
  twenty-five per run.
- **Period**: at most 366 days, with an optional comparison period of the same length before it.
- **Event**, optional: a moment inside the period to compare before and after.
- **Method**, folded away: the quiet hours, the resting quantile and the activity above which a
  moment at night counts as restless.

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
| `day_night_by_the_clock` | The animal has no position to read the sun at, so day is 06:00 to 18:00 on the local clock |

## Where the data comes from

Measurements of the animal's own devices, read through the effective value, so a correction made
under Curation is the value the analysis sees. The reporting interval is read from the device's
settings table, and the animal's positions only say where the sun is. Nothing else.
