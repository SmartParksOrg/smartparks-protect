# Cardiac monitoring with a LINQII tag

An OpenCollar Edge can follow one **LINQII cardiac tag** worn by the same animal. The tag
advertises over Bluetooth, the collar listens for it and relays what it heard on port 15, and
Protect stores the readings as ordinary measurements of the collar, which means of the animal the
collar is on (decision D282, phase 34).

The firmware calls the tag a "cardiac monitoring device Q", CMDQ for short, and so do the field
names.

## What the tag sends, and what it means

One record per sighting. Four of the values can be read directly, and five cannot:

| Reading | Metric | What it is |
| --- | --- | --- |
| Heart rate | `heart_rate` | Beats per minute, derived from the median time between R peaks, which the tag sends in tens of milliseconds |
| Heart rate variability | `heart_rate_variability` | RMSSD in milliseconds, the square root of the tag's mean squared successive R-R difference. Firmware 6.9.0 and later only |
| Body temperature | `cmdq_temperature` | Degrees Celsius from the tag's raw value |
| A reading happened | `cmdq_success` | True when the tag's temperature came through, which is how the firmware's own decoder judges a reading |
| R-R median | `cmdq_rr_median` | The measured value the heart rate is derived from, in tens of milliseconds |
| Activity | `cmdq_activity_average` | The implant's own accelerometer score, unitless from 0 to 255: high while the animal is awake and moving, low in its sleep. A 0 is the implant's hourly fault, not a reading, and the analysis sets it aside (D287). Not the device's own accelerometer activity |
| Activity, highest | `cmdq_activity_max` | A number the tag sends; not interpreted |
| Active minutes in the last hour | `cmdq_active_min_in_last_hour` | Reads as minutes, though the unit is not published |
| Impedance | `cmdq_impedance` | A number the tag sends. Its meaning is not published; it reads like a contact quality, but that is a guess |
| Mode sum | `cmdq_rr_median_modesum` | A number the tag sends. Its meaning is not published |
| Raw values | `cmdq_raw_temperature`, `cmdq_hrv_raw` | What the temperature and the HRV are derived from, kept so the derivation can be checked |

The five without a published meaning are stored as the numbers they are. Nothing in Protect
interprets them, and the metric registry says so in each one's description. Their definition sits
in a private issue of the firmware's upstream repository; when it is shared, the descriptions can
be filled in without touching any stored data.

## A sighting is not a reading

The tag can be heard and have nothing to say: `rr_median` is zero, the temperature is zero, and
`cmdq_success` is false. That is normal, not a fault. It usually means the tag is not against the
skin.

This matters more than it sounds, because **a quiet tag and a calm animal look the same in a
heart rate chart**. Every figure Protect shows is accompanied by how many sightings there were
and how many of them carried a reading. When no reading came through, no heart rate, no
temperature and no variability are written at all, rather than zeros that would drag an average
down. The raw fields are still stored, so the record is complete.

## How often it reports

The collar does not hear the tag continuously. It scans on a schedule and reports in batches:

| Setting | What it does |
| --- | --- |
| `cmdq_enabled` | Switches the scanner on. Switching it off while a scan runs stops the scan |
| `cmdq_searched_mac_address` | The Bluetooth address of the tag this collar follows. One collar, one tag |
| `cmdq_scan_duration` | How long a short scan listens, in milliseconds |
| `cmdq_search_interval` | How long to wait between scans, in seconds. Set it to the tag's advertising interval |
| `cmdq_on_no_detection_wait_duration` | How long to wait after a long scan found nothing, in seconds |
| `cmdq_reporting_interval` | How often the detections held in the buffer become a port 15 message, in seconds |
| `cmdq_report_zero_messages_to_be_sent` | Report an empty message when nothing was detected between two reporting intervals. A debugging aid: it proves the scanner is running |

The firmware uses four kinds of scan (immediate, short, long and a timeout scan) to find the
tag's rhythm and then stay in step with it. A LINQII advertises a burst every three minutes, so
a reporting interval of several minutes usually carries a few detections per message.

These settings are in the device's settings catalogue, so they are read and set on the device's
**Settings** tab like any other (ADR 0035). The command **Send latest CMDQ results** asks the
collar to report what it has now.

## Where the readings appear

- On the **live map**, an animal's panel carries a **Heart rate** row with the newest reading;
  clicking it unfolds the trend over the period, the way the battery does.
- On the **Data** tab of the entity or the device, in the metrics table and the Data explorer,
  under the `physiology` category.
- In the **[Cardiac monitoring](../analytics/cardiac.md)** analysis module, which is where the
  figures that need a method live: the daily rhythm, a resting heart rate, and what the collar
  managed to hear.

Rules and automations can use the readings like any other measurement: a rule on `heart_rate`
fires the same way one on `battery_voltage` does. Protect ships no such rule, because a healthy
heart rate depends on the species, the age, the season and what the animal was doing a minute
ago, and none of that is in the data.

## Firmware differences

| Firmware | Record | Note |
| --- | --- | --- |
| 4.x | none | No CMDQ module. A port 15 frame from such a device is noted on the trace and the delivery is kept |
| 6.1 to 6.8 | 13 bytes | No HRV |
| 6.9.0 and later | 15 bytes | HRV added |

The record length comes from the firmware version the device reports, never from the frame, so a
device that sends an unexpected number of bytes leaves a note rather than eleven fields read at
the wrong offsets.

## Checking a decode

The firmware's own reference decoders are vendored under
`tests/fixtures/payloads/opencollar/decoders/` and the golden test runs every recorded frame
through them, so what Protect reads cannot drift from what the firmware means. The full record
layout is in [OpenCollar protocol research](opencollar-protocol-research.md), section 3.13, and
the design of this phase is in `docs/CARDIAC_MONITORING_PLAN.md`.
