# Cardiac monitoring from a LINQII tag (CMDQ)

Design for phase 34, asked for by Tim on 2026-09-22: read the heart rate data an OpenCollar Edge
picks up from a LINQII cardiac tag, store it as ordinary measurements, and give it an analysis
module of its own. Decisions D282 to D285.

## 1. What the devices report

A LINQII tag is a cardiac monitor worn by the animal. It advertises over Bluetooth in a burst of
eight packets every three minutes; the full record needs an active scan, so the collar asks for a
scan response. The Edge firmware's `bt_cmdq` module scans for one configured address
(`cmdq_searched_mac_address`, 0x4D) and copies what it hears into port 15, message 0xFC.

Sources: `app/src/bt_module/bt_cmdq/README.md` and `bt_cmdq_messaging.c` of
`SmartParksOrg/smartparks-opencollar-edge-fw-public`, read on 2026-09-22, and the reference
decoders of `SmartParksOrg/raw_logs_decoder` vendored under
`tests/fixtures/payloads/opencollar/decoders/`. The layout is written out in
`docs/devices/opencollar-protocol-research.md` section 3.13.

One record per sighting. The record is a four byte timestamp followed by the "important data"
copied verbatim out of the advertisement at offset 17:

| Offset | Size | Field | Meaning |
| --- | --- | --- | --- |
| 0 | 4 | timestamp, u32 little-endian | the **collar's** own `get_global_unix_time()` at the scan |
| 4 | 1 | rr_median | median time between cardiac R peaks, in tens of milliseconds |
| 5 | 1 | rr_median_modesum | not published |
| 6 | 1 | activity_average | not published |
| 7 | 1 | activity_max | not published |
| 8 | 1 | active_min_in_last_hour | not published |
| 9 | 2 | raw_temperature, big-endian | temperature in C is `raw * 0.0248 - 18.09`; a raw above zero is a successful reading |
| 11 | 2 | h_impedance, big-endian | not published |
| 13 | 2 | hrv_raw, big-endian, firmware 6.9.0 and later | the mean of squared successive R-R differences; its square root is RMSSD in ms |

The record is 13 bytes in firmware 6.1 to 6.8 (nine important bytes) and 15 bytes from 6.9.0,
when HRV was added (eleven important bytes). `Layout.cmdq_record_length` in the driver already
carries which. The frame is `FC len records...` with `len = record_length * n`, and `FC 00` is
the empty report the device sends between detections when
`cmdq_report_zero_messages_to_be_sent` (0x50) is on.

Two things follow from the byte order and are worth stating, because getting either wrong is
silent. The timestamp is little-endian and written by the collar, so it is the collar's clock and
the ordinary clock rules apply to it; the rest is big-endian because it is the tag's own byte
order, untouched. The firmware refuses an advertisement shorter than 28 bytes with "are you sure
you're scanning the right device", so a short record is a wrong tag, not a truncated frame.

What the fields mean beyond this is in IRNAS issue 389, which is private. Heart rate, HRV,
temperature and whether a reading succeeded are derivable from what is published; the other five
are numbers with names and no units. We store them under their own names and say so, rather than
guess (decision D283).

## 2. Decisions

| # | Decision |
| --- | --- |
| D282 | A CMDQ reading is a measurement of the scanning device, so it lands on the animal wearing the collar. The tag's address is already known per device from `cmdq_searched_mac_address` in the settings table, so nothing new stores it |
| D283 | Every decoder field is stored, and the two a person reads are derived from documented arithmetic: `heart_rate` in bpm and `heart_rate_variability` in ms. A new metric category `physiology` |
| D284 | The cardiac study is the fifth analysis module: heart rate over the period, the daily rhythm, a resting heart rate, HRV, body temperature, and what the collar managed to hear |
| D285 | It is proven on simulated frames through the real decoder on the dev server, the way phase 32 proved the fence, until a LINQII reports |

## 3. Decoding

`_decode_cmdq` in the OpenCollar driver, port 15 out of `NOT_CANONICAL_PORTS`:

- The record length comes from the layout, never from the frame. A `len` that is not a whole
  number of records is a note on the trace, not a failure, and the whole records are kept.
- `FC 00` is a note, "no cardiac detection in the reporting interval", and no measurement.
- Each record's time is its own timestamp through `_unix`, with `device_clock=True`, so a
  device whose clock runs behind its delivery is corrected the way a scan's contacts are (D259)
  and one ahead of it is written invalid (D119). A timestamp below `MIN_VALID_UNIX` falls back
  to the delivery time, as every other record type does.
- Every field becomes a measurement with `record_type="cmdq"`: `cmdq_rr_median`,
  `cmdq_rr_median_modesum`, `cmdq_activity_average`, `cmdq_activity_max`,
  `cmdq_active_min_in_last_hour`, `cmdq_raw_temperature`, `cmdq_impedance`, `cmdq_hrv_raw`,
  `cmdq_temperature`, `cmdq_success`, and where the firmware sent HRV, `cmdq_hrv`.
- Two derived on top, and only where they mean something: `heart_rate` is `6000 / rr_median`
  when `rr_median` is above zero, `heart_rate_variability` is `sqrt(hrv_raw)` when the raw is
  above zero. A record with `rr_median` zero is a sighting without a cardiac reading: the tag
  was heard, the heart was not, and `cmdq_success` says which. The reference decoder reports a
  zero for each of these and we write nothing, which is the one place we differ from it on
  purpose: a variability of zero would be a heart beating perfectly evenly.
- The reference decoders are the oracle: `scripts/opencollar_golden.py` runs the recorded port 15
  frames through them, so our arithmetic cannot drift from the firmware's own.

## 4. The module

Key `cardiac`, subjects are entities, the subject's devices supply the rows. It answers the
questions a keeper actually has, in this order:

1. **Was the tag heard?** Detections in the period against the expected number from
   `cmdq_reporting_interval` and `cmdq_search_interval` in the device's settings, the share with
   a real cardiac reading (`cmdq_success` and a non-zero `rr_median`), and the longest gap. A
   figure nobody can read without this block, because a quiet tag and a calm animal look the same
   in a heart rate chart.
2. **Heart rate over the period**, per subject, and its distribution.
3. **The daily rhythm**: heart rate by hour of the local day, on the project's timezone, the way
   the movement and grazing modules do it.
4. **A resting heart rate**: the low quantile of the quiet hours, with the quantile and the hours
   named in the settings block, never as a hidden constant.
5. **HRV** where the firmware sends it, as RMSSD in ms.
6. **Body temperature** from the tag, beside the collar's own temperature where both exist, since
   the two disagreeing is a sign the tag is off the animal.

Warnings: sampling coarser than the rhythm asks for, a period where nothing was heard, a subject
whose device reports no CMDQ at all, and firmware older than 6.9.0, which sends no HRV.

No geometries. The module is a time series study, not a spatial one.

## 5. Tasks

- [ ] C1 the driver: `_decode_cmdq`, the constants, port 15 out of `NOT_CANONICAL_PORTS`,
      the recorded frames as fixtures with their sources, the golden test covering them.
- [ ] C2 the metrics: the `physiology` category and the new keys in `shared/metrics/seeds.py`,
      with a migration that seeds them.
- [ ] C3 the settings catalogue: units and descriptions for 0x49 to 0x50 from the firmware
      README, which today are empty or mis-scraped.
- [ ] C4 the interface of the device: a Cardiac row on the live map's entity and device panels
      with its trend, and the same line on the health card, as the fence and trap rows do.
- [ ] C5 the module: `primitives/cardiac.py`, `modules/cardiac.py`, the enum value, the
      migration that widens the run row's check, registration.
- [ ] C6 the frontend: the page, the form, the presentation, the navigation entry, Dutch.
- [ ] C7 docs: `docs/devices/cardiac-monitoring.md`, `docs/analytics/cardiac.md`, the driver row,
      the pages guide, `DEVELOPERS.md`, the changelog, an ADR.
- [ ] C8 the dev server: a Cardiac demo project seeded through the real decoder, and Tim's own
      device when a LINQII reports.

## 6. Exit criteria

- A recorded port 15 frame of each record length decodes to the same values the reference
  decoder gives, through the golden test.
- A collar whose firmware predates 6.9.0 yields no HRV and no warning of a fault.
- An empty report leaves a note and no measurement, and does not fail the source event.
- A run over a subject with a day of readings answers the six blocks of section 4, and a run over
  a subject with none says so rather than drawing an empty chart.
- The access matrix holds for the new module: a viewer of another project cannot read the run.

## 7. Later, not in this phase

- The five fields whose meaning is private, once IRNAS issue 389 is shared: today they are
  stored and shown as numbers.
- Alerting on a heart rate out of bounds, which belongs to the rules engine and wants a
  threshold per species that nobody has yet.
- Heart rate against the collar's own movement, which needs the two clocks to agree and is the
  natural second question once the first has been read on real data.
- The LINQII as a device of its own, if a tag is ever read by more than one collar (D282 keeps
  the address on the device's settings, so the history can be re-attributed without decoding
  anything again).

## 8. Phase 35: the whole record

Asked for by Tim on 2026-09-23: the module showed the heart rate by hour of the day and little
else, while a port 15 record carries the heart rate, the variability, the tag's own activity and
its temperature. How the people who study these animals read such a record was shared by Tim
from their unpublished work and is not cited here; what it taught is written into the decisions.
Decisions D287 to D290.

### 8.1 What the record gives, read as a researcher reads it

- **Activity** (`cmdq_activity_average`) is the implant's accelerometer score on a unitless scale
  of 0 to 255, one value per report. It is not the device's own activity. Awake and moving scores
  sit high, sleep sits low. The implant writes a 0 once an hour by a fault of its own, and a real
  score never falls that low, so a 0 is set aside and counted (D287).
- **Day, night and resting** are the three parts of a day every figure is read in. Day and night
  follow the sun at the animal's position, so they hold at any latitude and in any season; the
  resting part is the run's quiet hours, as before, now for every metric (D288).
- **The daily rhythm** of each metric: heart rate peaks in the afternoon and bottoms out before
  dawn, the variability peaks as the animals wake, activity follows daylight.
- **Restless nights**: the minutes per night with activity above a threshold (100 by default),
  a measure of disturbed rest.
- **A change around an event**: an animal leaving its group, a capture, a drought. The period is
  split at a date and every part of the day compared before and after (D289). Descriptive only,
  no model and no p-value: one animal's record is not a sample.

### 8.2 The views (D290)

- The hour-of-day median of all four metrics, one chart each.
- Day, night and resting as a box plot per subject for each metric: a new chart kind, `box`, on
  the page and in the report.
- The daily course over the period: day and night medians per date, the event date marked.
- Restless minutes per night per subject.

The page and the PDF report show the same things. The report gains its own cardiac section; it
fell back to the movement module's labels, key figures and limitations until now.

### 8.3 Tasks

- [x] P1 primitives: `box`, `daylight` (the sun's elevation at a place), `part_masks`,
      `daily_medians`, `restless_nights`, `before_after`; activity zeros set aside.
- [x] P2 the module: activity loaded, the position for the sun, the parts, rhythms, daily course,
      nights and the event split per subject; the tables and charts; the parameters `event_at`
      and `restless_activity`; the rhythm chart's series as `data` (it wrote `points`, which
      neither the page nor the report reads, so the chart drew empty).
- [x] P3 the chart kind `box` and the chart's `marks` in `base.Chart`, `ResultChart.tsx` and
      `report/charts.py`; a night series drawn dashed.
- [x] P4 the frontend: the form (event date, restless threshold), the summary cards, the labels,
      Dutch.
- [x] P5 the report: the cardiac labels, key figures and limitations.
- [x] P6 tests: the primitives, the module over synthetic days, the report, the run through the
      API.
- [x] P7 docs: `docs/analytics/cardiac.md`, `docs/devices/cardiac-monitoring.md` (activity is a
      score now), `DEVELOPERS.md`, the changelog, the plan.
- [x] P8 the dev server: the Cardiac demo reseeded with activity on 2026-09-23 and read by Tim; real LINQII data in the Baboon project followed the same day (the flash-stream repair in the plan's session log).

### 8.4 Exit criteria

- A run over a subject with several days of readings answers all four metrics in the day, the
  night and the resting hours, draws their rhythms, the daily course and the restless nights,
  and says where day and night came from.
- An event date inside the period gives before and after figures for every metric and part; one
  outside it is refused with a warning, not ignored.
- A subject without any position still gets day and night, from fixed hours, and is told so.
- The PDF of a cardiac run carries the cardiac figures, charts and limitations and none of the
  movement module's.
