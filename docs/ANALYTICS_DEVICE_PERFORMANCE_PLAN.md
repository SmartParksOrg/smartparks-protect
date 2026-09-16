# Device performance analysis: design and plan

The third analysis module (phase 28 of `PROJECT_PLAN.md`, decisions D213 to D220). It takes the devices Protect knows, their type and driver, and answers how they perform: the device's own health (battery, temperature, reboots, errors), how regularly it reports, how well its GNSS fixes come, and how the networks that carry it behave (LoRaWAN per data source, Iridium per data source). One run reads a fleet or one device; the result is a table of indicators with levels, a section per device with charts, a map of the fixes by quality and the gateways that heard the device, and a PDF report.

This document is the design reference the way `ANALYTICS_PHASE1_PLAN.md` is for movement and grazing. It reuses that plan's framework (the analysis package, the runner, the worker, the API, the pages, the report engine) and changes it in one place: devices become a kind of subject.

## 1. Why this module, and why now

The analytics plan's gate (section 20 there, decision D203) asks for a month of use of movement and grazing before any further module gets a plan. Device performance is admitted early by the admission rule of the brief (decision D213), with these answers:

- **Used repeatedly.** Every operations round asks the same questions of the fleet: which devices are low, which reboot, which stopped fixing, which network drops uplinks. Today those answers are spread over the device page's Health, Data and Connectivity tabs, Explore and Needs attention, one device at a time.
- **The data is already in Protect.** Measurements (battery, temperature, uptime, the GNSS figures), events (device errors, resets), the state history (error flags, reset reasons, firmware), receptions (gateways, RSSI, SNR, frame counters), connectivity states, satellite sessions, and source events per channel. Nothing new is collected.
- **A real decision.** Service or replace a device, change a setting (a GPS interval, a status interval), move or add a gateway, switch a device to satellite, retire a firmware.
- **Substantially easier than outside tools.** The figures need the driver's knowledge of the device (thresholds, message layouts) and the platform's knowledge of the networks; an export to a spreadsheet loses both.
- **Maintenance in proportion.** The module reads existing tables through the analysis primitives and adds no schema beyond the framework's, so the boundary of ADR 0031 holds.

The gate's review of the ecological modules stays where it is; this plan does not replace it.

## 2. What exists to build on

| Piece | Where | Used for |
| --- | --- | --- |
| The analysis framework: contract, runner, worker, API, pages, run list and view, result blocks, presentations, report engine | `shared/shared/analysis/`, `services/analysis`, `routers/analyses.py`, `components/analysis/`, `shared/shared/analysis/report/` | Everything but the module itself |
| The driver's health fields with thresholds (`HealthField`: battery warn 3.6 V and critical 3.45 V, temperature warn 50 °C, accuracy warn 30 m, time to fix warn 120 s, flash warn 80 and critical 95 percent) | `shared/device_drivers/opencollar/__init__.py`, `shared/domain/health.py` | The levels of the health and GNSS indicators |
| The device's settings (`lr_gps_interval`, `status_send_interval`, `satellite_send_interval`, `ublox_send_interval`) | the device type's `default_settings`, the device's attributes, the driver's `catalog.json` | The expected reporting intervals |
| Measurements by metric (`battery_voltage`, `device_temperature`, `uptime`, `activity`, `gnss_fix`, `gnss_satellites`, `gnss_accuracy`, `gnss_time_to_fix`, `gnss_pdop`, `lr_satellites`, `link_margin`, `flash_used_percent`) | `measurements`, read through `shared/curation/effective.py` | Health and GNSS figures |
| Positions with `record_type`, `valid`, `accuracy_m`, `satellites` | `positions` | Fix success, rejected fixes, the map |
| Events `device_error` (the flags), `device_reset` (the reason), `no_data`, `battery_low` | `events` | Reboots and errors by kind |
| The state history (`errors`, `reset_reason`, `firmware_version`, `hardware_version`) | `device_state_history` | Error flags per status, firmware over the period |
| Receptions per uplink and gateway (`gateway_id`, `rssi`, `snr`, `frequency_hz`, the frame counter in the source event's `provider_metadata.f_cnt`) | `gateway_receptions`, `source_events` | The LoRaWAN indicators |
| Connectivity states per device and data source (`status`, `last_uplink_at`, `last_join_at`, `last_downlink_at`, `attributes.satellite`) | `connectivity_states` | The joins, the last contact |
| Satellite sessions (`status`, `sequence`, `mt_sequence`, `cep_km`, `bytes`) | `source_events.provider_metadata.satellite_session`, `ConnectivityState.attributes.satellite` | The Iridium indicators |
| Source events per channel and ingestion method, duplicates | `source_events` | Messages per day per channel, redeliveries |
| The connectivity read's link figures (`_lorawan_link`, `_iridium_link`) | `routers/devices.py` | The same figures over a period; the module computes them in the worker, not through the API |

## 3. Subjects: devices

Decision D214. The framework's subjects are entities today (D201). The module needs devices, and a device may track no animal at all (a spare device in a drawer, a freshly onboarded one). The framework gains a subject kind:

- `SubjectSelection` gets `device_ids` (up to 100), `device_type_id` (every device of that type assigned to the project in the period) and `all_devices` (every device of the project in the period), next to the entity fields; a module declares which kind it takes (`subject_kind = "device"`), and the API resolves a type or "all" to ids before the run is stored, so the run stays reproducible.
- `Subject` gets `kind` (`entity` or `device`); for a device subject `name` is the device's name, and `tracked` names the entity it tracked during the period (the first and, when it changed, the last).
- The reader's scope (D186) applies to devices through `narrow_devices`, as the device routes do.
- The results' colours come from `subjectPalette` as today; the report's labels name devices the same way.

Movement and grazing keep entity subjects; nothing changes for them.

## 4. The indicator catalogue

Decision D216: a fixed catalogue per area. Every indicator is computed when its data exists for the device and left out of the device's report when it does not (a device without GNSS has no GNSS block; a device on LoRaWAN alone has no Iridium block). Decision D217: every indicator carries a level, ok, warn or critical, from the driver's declared thresholds where they exist and from the defaults below where they do not; the defaults are named in the result document and in the docs, and every device in a fleet run also gets its rank per indicator.

### 4.1 Health

| Indicator | Definition | Source | Level |
| --- | --- | --- | --- |
| Battery now | The newest battery voltage in the period | `battery_voltage` | The driver's thresholds (warn below 3.6 V, critical below 3.45 V) |
| Battery slope | Least-squares slope of the daily median voltage, in mV per day, over the period | `battery_voltage` | warn when falling more than 5 mV a day, critical more than 15 |
| Days to critical | The days until a proven slope reaches the critical threshold; "steady" or "rising" when no fall is proven, "over a year" beyond that (revised 2026-09-16, decision D232: a flat week gave 243 trillion days) | derived | warn under 60 days, critical under 14 |
| Charging | Days on which the charging voltage was above the battery voltage (a solar device) | `charging_voltage` | none (informative) |
| Temperature | Minimum, median, maximum and the hours above the warn threshold | `device_temperature` | The driver's thresholds (warn above 50 °C, critical above 60) on the maximum |
| Reboots | Count of `device_reset` events and the reasons (watchdog, software, lockup, pin) | `events` | warn at one a week, critical at one a day |
| Uptime | The longest uptime seen and the median | `uptime` | none |
| Errors | Per error flag (`lr_join`, `ublox_fix`, `flash`, ...) the count of status messages with the flag on and the share of statuses | `device_state_history`, `device_error` events | warn when a flag is on in more than 10 percent of the statuses, critical above 50; `flash` and `battery` flags are critical when on at all |
| Flash used | The newest value and the change over the period | `flash_used_percent` | The driver's thresholds |
| Movement | Share of statuses with movement (the `activity` metric above the threshold of D204) and the longest still period | `activity` | none (a still device is a health signal the health card gives already; here it is context) |
| Firmware | The firmware and hardware versions seen in the period and whether they changed | `device_state_history` | none |

### 4.2 Reporting

| Indicator | Definition | Source | Level |
| --- | --- | --- | --- |
| Expected intervals | The GPS, status and satellite intervals from the device's settings (its own, else the type's defaults); "unknown" when neither says | settings | none |
| Observed intervals | The median and the 90th percentile of the interval between consecutive fixes, and between consecutive statuses | `positions`, `device_state_history` | none |
| Missed reports | The share of expected messages that did not arrive: expected from the interval over the period, observed from the messages; per message kind | derived | warn above 10 percent, critical above 30 |
| Silences | Gaps between messages longer than three expected intervals: count, the longest, and the last one's end | derived | warn when the longest exceeds a day, critical when it exceeds a week |
| Messages per day | Source events per day per channel (LoRaWAN, Iridium, Bluetooth sync, file) | `source_events` | none |
| Clock | Records the decoder held as clock-ahead (invalid) and the largest lead seen | `positions.valid`, `measurements.valid` | warn when any, critical above 10 percent |

### 4.3 GNSS

| Indicator | Definition | Source | Level |
| --- | --- | --- | --- |
| Fix success | Share of GNSS attempts that produced a fix (`gnss_fix` true) | `gnss_fix` | warn below 80 percent, critical below 50 |
| Time to fix | Median and 90th percentile of `gnss_time_to_fix` | `gnss_time_to_fix` | The driver's threshold on the 90th percentile (warn above 120 s) |
| Satellites | Median satellites per fix, share of fixes under four | `gnss_satellites` | warn when more than 20 percent of the fixes had fewer than four |
| Accuracy | Median and 90th percentile of the accuracy, share above the driver's warn threshold | `gnss_accuracy`, `positions.accuracy_m` | The driver's threshold (warn above 30 m) on the median |
| PDOP | Median PDOP | `gnss_pdop` | warn above 5 |
| Rejected fixes | Fixes the pipeline or a curation marked invalid, and fixes an analysis would exclude as impossible at the module's default speed | `positions` | warn above 2 percent |
| Fixes per day | Valid fixes per day against the expected count from the GPS interval | derived | folds into Missed reports |

### 4.4 Network, per data source the device has an identity on

LoRaWAN (a data source whose channel is `lorawan`):

| Indicator | Definition | Source | Level |
| --- | --- | --- | --- |
| Uplinks per day | Source events of the source per day | `source_events` | none |
| Lost uplinks | Frame counter gaps as a share of the counter's advance (the uplinks the network never delivered) | `provider_metadata.f_cnt` | warn above 5 percent, critical above 20 |
| Gateways | Distinct gateways that heard the device, the best one and its share of the uplinks | `gateway_receptions` | warn when one gateway carries more than 90 percent and it is the only one (no redundancy) |
| Signal | Median and 10th percentile of the best RSSI and SNR per uplink | `gateway_receptions` | warn when the 10th percentile RSSI is below -120 dBm or SNR below -15 dB |
| Spreading factor | The distribution of data rates when the platform reports them | `provider_metadata` | none |
| Joins | Join events in the period | `connectivity_states.last_join_at`, join source events | warn above one a day |
| Downlinks | Downlinks queued, transmitted, acknowledged and failed for the device (commands) | `commands`, `command_executions` | none |

Iridium (a data source whose channel is `iridium`):

| Indicator | Definition | Source | Level |
| --- | --- | --- | --- |
| Sessions per day | Sessions in the period per day | satellite sessions | none |
| Missed sessions | Counter skips as a share of the counter's advance | `sequence` | warn above 5 percent, critical above 20 |
| Redeliveries | The platform's redeliveries stored as duplicates | duplicates | none |
| Bytes | Bytes carried, and per session | `bytes` | none |
| Estimate against fix | Sessions whose network estimate disagreed with the fix by more than three CEP radii | the trace's note, or recomputed | none |
| Session status | The distribution of session status codes | `status_code` | warn when more than 10 percent are not successful |

## 5. The run

- **Parameters.** `DevicePerformanceParameters(CommonParameters)` with the device subject fields of section 3, the period (default the last 30 days, D218), the optional comparison period (the 30 days before, by the form's button), and the areas are always all four (D216 chose a fixed catalogue; no per-run switches).
- **Limits.** Up to 100 devices (`MAX_DEVICES_PERFORMANCE`), a year at most (`MAX_DAYS`), at most `MAX_FIXES_PER_SUBJECT` fixes per device as in movement; the estimate endpoint counts fixes, statuses and receptions and refuses what the run could not read.
- **Reads.** Per device, four streamed queries through the effective-time helpers: positions (fixes) for GNSS and the map; measurements by metric for health and GNSS figures, aggregated in SQL per day (`time_bucket`) where a distribution is not needed and streamed where it is; the state history for flags, reasons and firmware; receptions with their source events for the network block; the satellite sessions from the source events of the Iridium source. Every read is bounded by the period and the device, on the indexes the hypertables have (device, time).
- **Comparison.** The same indicators over the comparison period, per device, as `comparison` rows next to `main`, the way the other modules do.
- **Progress.** One step per device and area, so a fleet run of 100 devices reports progress a hundred times.

## 6. The result document

- `summary.main[device_id]` and `summary.comparison[device_id]`: the indicators as flat figures (`battery_v`, `battery_slope_mv_day`, `days_to_critical`, `reboots`, `fix_success`, `ttf_p90_s`, `lost_uplinks_share`, ...), each with its level in `summary.levels[device_id][indicator]` (`ok`, `warn`, `critical`) and, in a fleet run, its rank in `summary.ranks[device_id][indicator]`.
- `summary.devices`: the device's name, type, driver, firmware, the entity tracked, the data sources with their channel; `summary.defaults`: the default thresholds used, named, so the reader sees what "warn" meant.
- **Tables.** `fleet` (one row per device: the indicators that matter most, with their levels; the module's headline table), `health`, `reporting`, `gnss`, `network` (one row per device and data source), `errors` (one row per device and flag), `reboots` (one row per reboot with time and reason).
- **Charts.** Per device: battery over the period (daily median, with the critical threshold as a line), temperature range per day, fixes per day against expected, time to fix distribution, accuracy distribution, satellites distribution, uplinks per day per source, RSSI and SNR per day (median and 10th percentile), lost uplinks per week, sessions per day. In a fleet run the charts are per device too; the page shows them under the device's section, folded.
- **Geometries** (D220): the coverage hull of the device's valid fixes (a convex hull, `kind = "coverage"`, per device) and the gateways that heard the device as points (`kind = "gateway"`, labelled with the share). The report engine draws the hulls; the page's map draws the fixes coloured by accuracy class (under 10 m, under 30 m, under 100 m, above), the hulls, the gateways sized by share, and the network estimates.
- **Warnings.** The framework's quality warnings plus: an expected interval unknown (the settings say nothing), a device with no message in the period, a driver without health fields (thresholds from defaults only), and a period shorter than three expected intervals.

## 7. Fleet and deep dive on the page

Decision D215: one module, one result shape. `pages/project/DevicePerformancePage.tsx` follows the movement page: the run list, the dialog with the form (`DevicePerformanceForm.tsx`: devices by picker, by type, or every device; the period; the comparison), and the run view with a presentation of its own in `presentations.tsx`:

- **Summary block**: the fleet table when the run has more than one device, sorted by the worst level then by the worst rank, with a level dot per cell and a click that scrolls to the device's section; for one device the block is its cards (health, reporting, GNSS, network) with the levels.
- **Map**: `ResultMap` with the fixes, hulls, gateways and estimates of section 6, the same chips.
- **Per device**: a folded section per device (open for a single device) with the cards and the charts.
- **After**: the defaults used, and the limitations of section 10.

Entry points (D219): "Analyse performance" in the device page's header (the device chosen), on the devices list's selection (the chosen devices), and a "Devices of this type" shortcut in the form. The module is switched on with `ANALYSIS_MODULES=movement,grazing,device_performance` and per project like the others; the key `analysis:run` starts runs, `exports:create` makes the report.

## 8. The PDF report

Decision D220: from the start. The report engine gets the module's labels and key figures in `render.py` (the fleet table as the key figures block, one row per device with the headline indicators and their levels marked by a coloured dot), the per-device sections with their charts two to a row, the map with the coverage hulls and gateways, and the defaults and limitations at the end. Nothing else in the engine changes.

## 9. Framework changes, listed

| Change | Where | Why |
| --- | --- | --- |
| The device subject kind: `device_ids`, `device_type_id`, `all_devices` on `SubjectSelection`; `Subject.kind`, `Subject.tracked`; `AnalysisModule.subject_kind` | `parameters.py`, `base.py`, `routers/analyses.py` (`_resolve_subjects`, `_visible_run` through `narrow_devices`) | Section 3 |
| Device trajectories: `load_trajectory` takes `device_id` as well as `entity_id` | `primitives/trajectory.py` | The GNSS block reads fixes by device, whoever wore it |
| New primitives: `intervals.py` (expected against observed, silences, missed share), `network.py` (frame counter gaps, best gateway share, signal percentiles from receptions, satellite session counters), `health.py` (slope and days to threshold, flags and reasons from the state history) | `shared/analysis/primitives/` | Section 4 |
| A level per indicator (`levels.py`): the driver's `HealthField` thresholds first, the catalogue's defaults second; the defaults as one table | `shared/analysis/` | Decision D217 |
| The form's device picker (`components/analysis/DevicePicker.tsx`) and the type shortcut | frontend | Section 7 |
| The report's labels and key figures for the module | `report/render.py` | Section 8 |
| `MAX_DEVICES_PERFORMANCE = 100` | `limits.py` | Section 5 |

No new table: the run row and the geometries table hold everything (D202).

## 10. Limitations, stated in the interface

- A missed report is inferred from the settings and the messages: a device whose interval changed in the period, or whose settings Protect never read, shows a share the reader must weigh; the document names the interval it assumed.
- Lost uplinks come from the frame counter; a platform that does not deliver it (some Iridium and HTTP sources) shows none, not zero.
- The battery slope is linear; a battery's curve is not, and days to critical is an indication, not a forecast. A slope is reported only when proven (five days, 1 mV a day, twice its standard error; decision D232).
- Missed fixes are split between the network and the device by the frame counter (decision D233); the four area tables repeat the cards, so the page and the report show a details table, the error flags and the reboots (decision D234; Tim's reading of the "Pangolins - 7days" run, 2026-09-16).
- Signal figures are the best gateway's per uplink; a moving device changes gateways, so the figure describes the network as the device met it.
- Levels come from the driver's thresholds and the catalogue's defaults, both named; they are not a verdict on the device, and a fleet rank says only where a device stands among the chosen ones.
- Fix success counts attempts the device reported; a device that does not report failed attempts shows a success rate of one.

## 11. Testing

- Unit tests per primitive on synthetic series: a falling battery gives the slope and the days to critical; a status series with a flag on in a fifth of them gives the share and the warn level; frame counters with gaps give the lost share; intervals with a week of silence give the longest silence; a fix series with failed attempts gives the success rate.
- A module test on inserted rows for two devices (one healthy, one failing) through the runner: the fleet table order, the levels, the comparison rows, the geometries, the warnings.
- An API test: a run by device ids, by device type and by "all", the scope of a member limited to one device, the estimate's refusals, the report.
- The frontend's presentation and form tests, the fleet table's sort.
- The benchmark section: a run over 100 devices with a month of data against the budgets of the analytics plan (section 14 there).

## 12. Tasks

- [x] **P1 device subjects in the framework**: `SubjectSelection` device fields, `Subject.kind` and `tracked`, `subject_kind` on modules, the API's resolution by ids, type and "all" with the scope, `load_trajectory` by device; tests.
- [x] **P2 primitives**: `intervals.py`, `network.py`, `health.py`, `levels.py` with the defaults table; unit tests on synthetic series.
- [x] **P3 the module**: `modules/device_performance.py` with the four areas, the fleet summary, the tables, the charts, the geometries and the warnings; `MAX_DEVICES_PERFORMANCE`; the estimate; the module test.
- [x] **P4 the pages**: `DevicePerformancePage.tsx`, `DevicePerformanceForm.tsx` with the device picker and the type shortcut, the presentation with the fleet table and the per-device sections, the map's fix classes and gateway points in `analysisLayers.ts`; "Analyse performance" on the device page and the devices list.
- [x] **P5 the report**: labels, key figures as the fleet table with level dots, the per-device sections; a rendered fixture test.
- [x] **P6 docs**: `docs/analytics/device-performance.md` (what each indicator means, its default threshold, its limits), the analytics index, `DEVELOPERS.md`, the changelog, ADR 0034 (device subjects and the indicator levels).
- [x] **P7 dev server** (the runs made and read on 2026-09-16; Tim's reading and the exit criteria below are still his): a fleet run over the FreeNature and Smart Parks devices and a deep dive of SP050969 read by Tim; the benchmark section over 100 devices; the budgets of the analytics plan held during a run.
- [x] **P8 release**: v2.6.0 on 2026-09-16, one tag for phases 22 to 28 (Tim's choice), after Tim read the runs and the PDF and closed the phase.

### Built on 2026-09-16, and where it differs from the sections above

- The device's settings come from four layers, later ones winning: the driver's catalogue defaults, the type's `default_settings`, the device's `attributes.settings`, and the settings frames the device sent (the `port_3_tlv` states decoded by the catalogue's ids and types). A device whose settings frames were never received falls back to the type's defaults, and the document says the interval it assumed.
- The clock indicator of section 4.2 became "records held invalid": every record the pipeline or a curation holds invalid in the period, the clock-ahead rule D119 among them, with its share; the decoder does not keep the reason apart.
- The fleet table's network columns take the worst data source of the device (the highest lost share, the lowest RSSI); the network table has one row per device and source.
- The frame counter comes from `provider_metadata.f_cnt` of the uplink source events, the joins from source events of type `join`; a source that delivers neither shows no figure.
- The trajectory loader takes `by_device=True` rather than a `device_id` argument; the `Trajectory.entity_id` field then holds the device's id (the subject's id either way).
- The limit constant is `MAX_DEVICES` (100) and the rows one device may hold per read `MAX_ROWS_PER_DEVICE` (500,000); the estimate counts the device's fixes, the run refuses beyond the bound.
- Statuses are counted from the state history and, when it holds none in the period, from the battery readings: the state history is not curated, so SP050969's repaired clock (D212) moved its measurements into 2025 and left its states in 2064. Messages and the network figures count by arrival at Protect (a raw log counts on the day of its upload); the interface and the docs say so.
- On the dev server (2026-09-16, commit 374ee3b): a fleet run over FreeNature's one device and a deep dive of SP050969 over 1 June to 14 September 2025 (204,504 input rows in 13 s): battery 3.61 V falling 0.48 mV a day with 336 days to critical, 28,222 fixes of 28,285 attempts, time to fix 7 s median and 18 s at the 90th percentile, accuracy 21 m median, 2,452 statuses with 3 percent missed, the longest silence 52.9 hours (warn), no network figures because the raw log's messages arrived by file; the PDF report of it has seven pages. The benchmark: 100 devices over a month on the local 1/10 fixture, 958,175 input rows, completed in 22.7 s with a 566 kB result and 102 MB peak memory, two devices critical on their battery and twenty warn. A fleet's repeated warnings fold into one line above three devices.
- The expected interval (D225 to D227, built the same evening): `shared/domain/reporting.py` resolves the declared interval from the sources Protect has, most trustworthy first (a person's override on the device, the newest settings frame, an acknowledged interval command, the type's settings), `shared/domain/reporting_rules.py` learns the dominant interval from the fixes with its regularity, and a declared interval the device plainly does not keep gives way to the learned one with the `interval_disagrees` warning; the result names the source (`expected_fix_source`) and the regularity (`fix_regular_share`) beside the figure, and the device page's Reporting card shows the same expectation with a way to set it. The interval rules live in the core so the analysis boundary holds.
- The interface folds the charts into the device sections and lets the presentation replace the run view's chart grid and table list (`render.charts`, `render.tables`), so a run over a hundred devices does not draw a hundred series in one chart.

## 13. Exit criteria

- A fleet run over the devices of a project on the dev server puts the device with the lowest battery, the one that reboots and the one that fixes worst at the top of the fleet table, each with the reason readable in its cells, and Tim agrees with the order.
- A deep dive of SP050969 over its raw log period shows the battery slope, the reboot, the error flags by kind, the fix success and time to fix, and no network block (the log came by file); the PDF report of it reads on paper.
- A member scoped to one device sees only that device in the form and in the runs.
- A run over 100 devices and a month finishes within the worker's budget without touching the live map's or ingest's figures.

Tim read the fleet run and the SP050969 deep dive with its PDF on the dev server and closed the phase on 2026-09-16; the module is released in v2.6.0.

## 14. Later, not in this phase

- The all-projects scope for server admins: a fleet run across projects, once the analysis tables carry a scope (D219's follow-up).
- Scheduled runs: the monthly fleet report queued on a timer and mailed, on the report engine of D211.
- Rule templates from the indicators: "battery falling faster than", "fix success below" as rules that fire per device, so the analysis becomes an alert.
- Cost of connectivity: bytes and sessions against a tariff per data source.
