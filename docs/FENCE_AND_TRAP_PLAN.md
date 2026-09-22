# Fence lines and traps: the FenceEdge and TrapEdge modes of the OpenCollar Edge

Design for phase 32, written 2026-09-19 from Tim's request of the same day. Decisions D263 to
D266 were asked and taken on 2026-09-19.

## 1. What the devices report

Both modes run on RangerEdge hardware with the fence port (`docs/devices/opencollar-protocol-research.md`, sections 3.10 and 3.15), and both are already decoded:

- **FenceEdge** (`tracker_type` 10). Every `fence_interval` seconds the device listens on the fence wire for `fence_sampling_length` seconds and sends port 12: whether the measurement worked, how many pulses it counted, the average peak voltage in volts and an energy figure in arbitrary units. Protect stores `fence_voltage`, `fence_pulse_count` and `fence_energy` measurements and a `fence_measurement` state, and raises a `fence_measurement_failed` event when the measurement did not work. The device does not move: its place is set by hand (decision D261).
- **TrapEdge**: the external switch on the same port (firmware 6.13.0 and later). Port 19 says the switch became active or inactive, at once, with how long the previous state lasted; port 20 repeats the state every `external_switch_detection_reporting_interval` with a count of activations. Protect stores a `switch_active` measurement and `switch_activated` / `switch_deactivated` events.

Two facts drive the design. A fence voltage is measured at one point, but the question is about a stretch of fence: a reserve draws its fence line and wants to see which part of it is live. And a switch is a switch: whether "active" means the trap door closed depends on how the magnet and the reed contact were mounted.

The registry seeded `fence_voltage` in kV; the driver stores volts, as the firmware README says. The unit is corrected to V and the interface shows kV where a fence person expects it.

## 2. Decisions

| Id | Decision | Choice |
| --- | --- | --- |
| D263 | A fence line is a feature type of its own, `fence`, and FenceEdge devices attach to it through entities | Drawn like a route (a LineString). Each FenceEdge is a device on a **Fence monitor** entity with a fixed place; the entity is attached to one fence line; a line holds any number of monitors. Over reusing routes with an attribute (the fence would share the route's icon, rules and lists) and over a line-shaped entity (new to the map, the panels and the rules). |
| D264 | A line's status is read per section between its monitors, the worse of the two ends | The line is cut where its monitors stand (each monitor's place projected onto the line); a section reads the worse of the monitors at its ends, the ends of the line read the nearest monitor, one monitor colours the whole line. Levels: **ok** at or above the ok threshold, **low** below it, **down** below the down threshold or when no pulses were counted, **unknown** when the newest measurement failed or is older than twice the fence interval. Thresholds per fence line, defaults 4 kV and 2 kV. Over one colour per line (cannot say which stretch is down) and over thresholds per monitor. |
| D265 | The status is computed in the decoder and every change is an event on the fence line | When a fence measurement lands, the decoder recomputes the line's sections into a `fence_status` row; a change of any section's level raises a `FENCE_STATUS` event on the line (info for ok, warning for low or unknown, critical for down), so the feed, the automations and the history see it. The history of a line is its events and its monitors' voltage series. Over a periodic job (a minute late, and the decoder has the measurement in hand) and over computing on read (no events, no history). |
| D266 | A trap is an entity; the switch's active state means closed, configurable per device | A **Trap** entity type (equipment). The switch state becomes a `trap_triggered` measurement and `TRAP_CLOSED` / `TRAP_OPENED` events (closed is a warning: somebody has to go); a shipped rule template "Trap closed" alerts; a closed trap reads critical on the live map through that alert. Whether "active" means closed is an attribute of the device, default yes, because it depends on the wiring. Over a fixed convention and over events only. |

## 3. The fence line

### 3.1 Data

- `FeatureType.FENCE = "fence"`, drawn as a LineString; `attributes.fence = {"ok_v": 4000, "down_v": 2000, "interval_s": 60}` with those defaults when absent.
- `fence_monitors (entity_id PK, feature_id)`: which fence line a Fence monitor entity is on. One line per entity; set from the entity page and from the fence line's panel.
- `fence_status (feature_id PK, project_id, level, sections JSONB, monitors JSONB, changed_at, updated_at)`: the current reading of the line. `sections` is a list of `{from_m, to_m, level, monitor_ids}` along the line; `monitors` a list of `{entity_id, name, position_m, level, voltage_v, pulses, measured_at, failed}`.
- Entity types `fence_monitor` ("Fence monitor", equipment, icon `infrastructure.fence_sensor`) and `trap` ("Trap", equipment, icon `event.trap`), seeded by migration on servers that already hold the catalogue.
- Migration 0047: the feature type check admits `fence`, the two tables, the two entity types, `fence_voltage` in V.

### 3.2 The rule, in `shared/domain/fence.py`, pure

- `monitor_level(voltage_v, pulses, failed, measured_at, now, thresholds)`: unknown when failed or when `now - measured_at > 2 * interval_s`; down when `pulses == 0` or `voltage_v < down_v`; low when `voltage_v < ok_v`; ok otherwise.
- `along_line(line, point)`: the metres from the line's start to the point's projection, on a local equirectangular frame around the line (a fence is kilometres, not continents).
- `sections(length_m, monitors)`: the monitors sorted by position; one section per gap, level the worse of the two ends; the first and last sections run to the line's ends with the nearest monitor's level; no monitor gives one unknown section; one monitor gives one section of its level.
- `line_level(sections)`: the worst.
- `recompute_fence(session, feature_id, now)`: loads the line, its monitors, each monitor's newest fence measurement (voltage, pulses, time) and newest failed measurement state, writes or updates `fence_status`, and returns which sections changed level. The decoder calls it after writing a fence record for a device whose entity is on a line, and raises the `FENCE_STATUS` event when anything changed, with the line's geometry on the event so it lands on the map where the fence is.

The API also applies the staleness rule when it reads the status, so a line whose monitors fell silent shows unknown even though no measurement arrived to trigger the decoder. An alert on silence comes from the shipped "Fence monitor silent" rule (a no-data rule scoped to the Fence monitor type).

### 3.3 What a person sees

- **Features**: a fence line is drawn or imported like a route; its form carries the two thresholds and the interval.
- **Live map**: fence lines are drawn in their level's colour (green ok, amber low, red down, grey unknown) per section, under the Features group as their own type. Clicking a line opens its panel: the level, since when, the sections with their monitors, each monitor's newest voltage (kV), pulses and time, a voltage chart over a day, a week or a month, and the recent fence events.
- **Entity page** of a Fence monitor: a "Fence line" card to attach it to a line, with the monitor's own level and newest reading.
- **Feed and alerts**: `FENCE_STATUS` events with the line's name and the section; the shipped "Fence down" rule (a threshold on `fence_voltage` below the down threshold, an alert) and "Fence monitor silent" (no data for six hours, an alert).

## 4. The trap

- The decoder, for a device on a Trap entity, derives from each `switch_active` measurement a `trap_triggered` measurement (closed = `switch_active == closed_when_active`) and, on a change against the device's newest `trap_triggered`, a `TRAP_CLOSED` (warning) or `TRAP_OPENED` (info) event.
- `devices.attributes.trap_closed_when_active` (default true) is set on the device page under a "Trap" card, beside the battery type.
- The shipped rule template "Trap closed" (a threshold on `trap_triggered` at or above 1, an alert, cooldown a day) makes a closed trap critical on the live map and in the feed.

## 5. Tasks

- [x] F1 data: the feature type, the two tables, the two entity types, the metric unit; migration 0047; the rules schema and the interface enumerations admit `fence`.
- [x] F2 `shared/domain/fence.py` and `shared/domain/trap.py` with their unit tests.
- [x] F3 the decoder: the trap derivation before the writes, the fence recompute and the event after them; an API test through the whole path.
- [x] F4 the API: attach a monitor to a line, read a line's status, the feature list with its level, the trap wiring on the device.
- [x] F5 the rules: the three templates, the Dutch of their titles.
- [x] F6 the interface: the feature form, the map layer and the fence panel, the monitor's card on the entity page, the trap card on the device page, Dutch.
- [x] F7 docs: `docs/devices/fences-and-traps.md`, the OpenCollar driver row, the pages guide, `DEVELOPERS.md`, the changelog, this document's state.
- [ ] F8 the dev server: the simulated half done on 2026-09-19 (the Fence demo and Trap demo projects, a day of frames through the real decoder); Tim's field devices when they report.
- [ ] F9 a trap's alert does not clear when the door opens again (seen on the Trap demo project, 2026-09-19): `TRAP_OPENED` raises its event and the open `TRAP_CLOSED` alert stays, so the second exit criterion of section 6 does not hold yet.
- [ ] F10 six metric keys this phase's messages registered stand in the registry as `uncategorized` (`switch_active`, `switch_count`, `lr_satellites`, `gnss_pdop`, `flash_used_percent`, `flash_messages`); seed them with their label, unit and category.

## 6. Exit criteria

- A fence line drawn on the map with two monitors on it shows three sections; a low reading at one monitor colours the sections on either side of it amber and raises one `FENCE_STATUS` event; a failed measurement turns them grey; a fence line without monitors is grey and says so.
- A trap device whose switch closes raises `TRAP_CLOSED`, the shipped rule alerts, and the trap reads critical on the map; when it opens the alert clears with `TRAP_OPENED`.
- The fence voltage reads in kV on the panel and the chart with the stored volts unchanged.
- The core boundary holds: no analysis import; the rules, exports and the MCP see the new records as ordinary measurements and events.

## 7. Later, not in this phase

- A fence section's history as a timeline of its own (when which stretch was down, for how long); today it is the events.
- Energiser-side monitoring (a device at the energiser reporting output) as a distinguished monitor role.
- The trap's count of activations (port 20) as a figure on the entity.
