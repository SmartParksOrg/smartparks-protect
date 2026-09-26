# Vehicles: speed and course, speeding, roads, and a vehicle use module

Design for phases 37 to 39, written 2026-09-26 from Tim's request of the same day: SP051307 with active tracking on tracked his car, and reported course and speed over ground in every position message. Decisions D296 to D301 were asked and taken on 2026-09-26. Phase 37 is built; phases 38 and 39 are planned here and start when Tim says so.

## 1. What the device reports

An OpenCollar with `ublox_active_tracking` (0x2B) on fills bytes 29 to 31 of the port 2 position message (`docs/devices/opencollar-protocol-research.md`, section 3.2): the course over ground as hundredths of a degree plus 18000, written little-endian by the firmware (the public decoder reads it big-endian, a bug the research document records), and the speed over ground as whole metres per second in one byte. So a car at 50 km/h reads 13 or 14 m/s, a resolution of 3.6 km/h, and a receiver at a standstill still reports a course, which is noise. A Traccar tracker reports both through the generic JSON driver. The driver already put them on the position row (`speed_mps`, `heading_deg`); nothing read them but the fix panel and the explorer's Speed column, and no `speed` or `heading` measurement was ever written although the registry had seeded both.

The evaluator's `speed_kmh` is the reported speed. Nothing derives a speed between two fixes, and phase 37 keeps it so: at hourly fixes such a figure means nothing, and a device that reports a speed gives a better one.

## 2. Decisions

| Id | Decision | Choice |
| --- | --- | --- |
| D296 | Speed and course become measurements beside the position | The decoder writes `speed` (m/s) for every fix that carries one and `heading` (degrees from north) while the speed is above zero, at the fix's own time and record type, for any driver; the position keeps its columns. Over teaching every reader a second path through the position columns, and over deriving a speed between fixes for every device. |
| D297 | Stored in m/s, read in km/h | The registry keeps m/s, what the receiver reports; every place a person reads a speed shows km/h, and a course shows degrees with a compass point. Over m/s as stored and over a per-project unit setting nobody asked for. |
| D298 | Where it shows | A Speed row that unfolds its trend on the map's entity and device panels, the Last position line of the entity and device pages, the recent positions lists, the fix panel; not on the health card, since speed is not the device's health. |
| D299 | A Speeding template, scoped by entity type | "Speeding": position trigger, `speed_kmh > 60`, cooldown 10 min, alert, the existing `SPEED_LIMIT_VIOLATION` event type; the rule editor gains the entity type scope the schema always had, and a type in a scope takes its sub-types on the server. Over reusing the zone template alone and over a separate event type. |
| D300 | Leaving known roads: roads as route features, a far-from condition (planned) | Roads become route features of the project, imported from OpenStreetMap through the Overpass reading that proposes areas today or from a reserve's files; a new rule condition "farther than N m from any route" raises `OFF_ROAD`. Nothing external is called per position. Over matching every fix against OpenStreetMap live and over a corridor learned from the vehicle's history. |
| D301 | A Vehicle use analysis module (planned) | Entities of type vehicle as subjects: trips, distance and driving hours per day, speeding episodes, time on and off known roads once roads exist, idle time, a map of trips coloured by speed, a PDF report. Over folding vehicle figures into the movement module and over a patrol coverage module. |

## 3. Phase 37, built on 2026-09-26

- `shared/domain/speed.py`: `speed_measurements(positions)`; the pipeline appends them before the writes, like `activity`. The OpenCollar driver normalises the course to 0 to 360.
- `routers/map.py`: `_value_at_fix` puts `speed` and `heading` on the entity and device features only when the measurement is of the newest fix and that fix is the position shown.
- Frontend: `lib/speed.ts`, `scaledUnit` reading m/s as km/h, `SPECIAL.speed` trend, the Speed row on the panels, the pages' position lines, the recent fixes, the fix panel's course, the explorer's Course column and display factor on metric columns.
- Rules: the `speeding` template, `in_scope` on the type lineage, the editor's Entity types field, the corrected explanation.
- Tests: `tests/shared/test_speed.py`, the driver's active tracking frame built from the wiki's worked example, `tests/api/test_map_speed.py`, `tests/shared/test_rule_scope.py`, `lib/speed.test.ts`, `lib/rules.test.ts`, the unit cases in `format.test.ts`.

Exit criteria, on the dev server: the Smart Parks project's entity Tim, tracked by SP051307 with active tracking on, shows a Speed row on the live map's panel while the car moves and none once it stands still for a fix without a speed; the device's Data tab lists Speed and Course in the metrics table with a trend in km/h; a Speeding rule scoped to Vehicles fires when the car passes the limit and never for a collar; the Test tab replays it over yesterday's drive.

## 4. Phase 38, planned: leaving known roads (D300)

**Roads as features.** A road is a `route` feature. Two ways in, both existing mechanisms extended:

- Import from OpenStreetMap: a "Roads from OpenStreetMap" action on the Features page reads the `highway` ways of a box the person draws (the walking ways left out, as `WALKING_HIGHWAYS` does for areas) through `shared/overpass.py`, bounded like the area proposal (25 km² per read, the public server's patience), previews them on a map with a checkbox per way and a name from `name` or `ref`, and saves the kept ones as route features with `imported_from: openstreetmap` and the way id in the attributes, so a later import updates rather than duplicates. Long roads become one feature per OpenStreetMap way; a "Combine into one route" like the zones' union merges what a person wants as one.
- Import from files: the shapefile, KML, KMZ, GPX and GeoJSON import of phase 33 already yields lines; a line becomes a route.

**The condition.** `FarCondition` in `shared/rules/schema.py`: `{"type": "far", "meters": N, "feature_ids": [], "feature_type": "route"}`, the counterpart of `near` (D140): true when the subject's position is farther than `meters` from every named feature (or every feature of the type). Evaluated with `metres_to_geometry`; the nearest distance is the condition's value, so the title can say "{entity} {value} m from the nearest road". Edge-triggered like every condition, so a vehicle that leaves the road fires once and again after the cooldown; `for_seconds` guards against one GNSS error beside the road (a fix's `accuracy_m` above the distance should not count: the evaluator skips a sample whose accuracy exceeds `meters`). A template "Off the roads": position trigger, `far` 50 m from any route, for 120 s, cooldown 30 min, `OFF_ROAD`, warning, alert, scope Vehicles. The replay tests it over history. `docs/rules/index.md` and `explanations.py` gain the type; Dutch follows.

**Bounds.** A project may hold hundreds of route features; the evaluator loads the features of the type once per rule evaluation as `near` does. If that proves slow at 250 events per second, the feature geometries get a per-project cache in the rules service keyed on the features' newest `updated_at`.

**Not in this phase.** Roads drawn from the vehicle's own history; a road's direction; speed limits per road (a `max_speed_kmh` attribute on a route and a speeding rule that reads it is the natural next step, and the feature attributes already allow it).

Deliverables: [ ] 38a `FarCondition`, evaluator, replay, the template, the explanation, Dutch, tests; [ ] 38b the OpenStreetMap roads import with its preview and bound; [ ] 38c the Features page's action, the docs, the changelog.

## 5. Phase 39, planned: the Vehicle use module (D301)

The sixth analysis module, on the framework of `ANALYTICS_PHASE1_PLAN.md`. Subjects are entities of the `vehicle` type and its sub-types (the form offers them the way the movement form offers animals). Every figure comes from the positions and the `speed` measurements; nothing new is collected.

**Trips.** A trip starts when the vehicle moves (speed above `moving_kmh`, default 5, or a step longer than the GNSS noise when no speed is reported) and ends when it stands still for `stop_minutes` (default 10). Per trip: start and end time, duration, distance (the sum of the steps, through `primitives/trajectory.py`), average and top speed (from the reported speed when there is one, else the step speed, and the result says which), the start and end named by the nearest site of the project within `site_radius_m` (default 200), else the coordinates. A gap in the record longer than `gap_hours` closes the trip and is counted as a warning, as the movement module does.

**Per vehicle and per day.** Distance, driving hours, trips, idle hours (engine on, not moving: a reported speed of zero while the fix interval is the active one, so it applies only to devices with active tracking), the first and last movement of the day, the share of fixes that reported a speed.

**Speeding.** Episodes above `limit_kmh` (default the project's Speeding rule's value when one exists, else 60): count, the longest, the fastest, where (points on the map); they use the `SPEED_LIMIT_VIOLATION` events when the rule ran, else the readings. Once phase 38 is in, time and distance on and off known roads per vehicle.

**Result.** Summary per vehicle and for the fleet, the tables `trips` (worst first by top speed), `days`, `speeding`; charts: distance per day per vehicle (bars), the speed histogram on fixed bins so vehicles share one axis, the hour-of-day profile of movement; the map: trips as lines coloured by speed on the five-step warm ramp, the sites, the speeding points; a PDF report with the same, the trips table turned on its side when wide. The limitations block says what a one-byte speed is worth (3.6 km/h steps), that a trip cut by a gap is two trips, and that idle time needs active tracking.

**Framework changes.** None expected: entity subjects, the parameters model, the result document and the report engine carry it. `AnalysisModuleKey` gains `vehicle_use`, migration for the run row's module check, `ANALYSIS_MODULES` offers it by default.

Deliverables: [ ] 39a the primitives (`primitives/trips.py`: segmentation, trip figures, tests on synthetic tracks); [ ] 39b the module, the run, the document; [ ] 39c the form, the page, the result blocks, the map layers, the report; [ ] 39d docs (`docs/analytics/vehicle-use.md`), the changelog, Dutch. Exit: a run over Tim's car for the week of 2026-09-25 lists the drive of that afternoon as trips with plausible distance and top speed, and a run over a collar refuses with "no vehicle among the subjects".

## 6. Later, not in these phases

Speed limits per road and a speeding rule that reads them; a corridor learned from history for tracks nobody has mapped; patrol coverage (which areas the vehicles and people covered, how often), which is a different question and a module of its own; fuel and maintenance figures, which need data nobody sends.
