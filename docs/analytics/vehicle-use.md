# Vehicle use

The Vehicle use page under Analyze answers, for up to twenty-five vehicles of a project over a period of at most a year: what they did. Trips with their distance, duration, mean and top speed and where they started and ended, distance and driving hours per day, the speeding episodes, the time paused inside trips, and a map of the trips. It is the sixth analysis module (phase 39, `docs/VEHICLE_PLAN.md` section 5, decisions D301, D303 and D304; the speed bands of the map and the charts are phase 40, decisions D306 to D308). Everything comes from the positions and the speed a device reports with its fix; nothing new is collected.

## The subjects

A vehicle is an entity of the **Vehicles** type or one of its sub-types (a car, a 4x4, a boat, a quad bike). The form offers those and nothing else, and the server refuses a run over anything else before it is queued: an animal has trips only in name. "Analyse vehicle use" on a vehicle's entity page opens the dialog with that vehicle and the last 30 days filled in.

## The form

- **Vehicles**: entities picked by name, one or more groups (their members with the subgroups join the picks) or every vehicle of a sub-type; at most 25 per run.
- **Period**: the last 24 hours, 7, 30 or 90 days, the last year, or a custom range; at most 366 days. A day is the quick look after a drive.
- **Compare with**: nothing, or the period of the same length right before.
- **Method**, folded with its defaults on one line:
    - **Moving above** (5 km/h): a fix whose reported speed is above this is movement even before the next fix has arrived.
    - **Stop after** (20 minutes): standing still this long ends a trip; a shorter halt (a gate, a fuel stop, a look) is a pause inside it. Ten minutes cut one drive in two at a fuel stop, which is why the default is twenty.
    - **Shortest trip** (300 m): a move shorter than this is not a trip; moving the car in the yard and a fix that wandered are left out.
    - **Stop radius** (15 m, decision D303): fixes within this radius of where a stop began are one place, so a parked vehicle's GNSS drift is neither distance nor a trip. The radius widens to a fix's own accuracy when that is worse.
    - **Site radius** (200 m): a trip that starts or ends within this distance of a site of the project is named after it; otherwise the coordinates stand in.
    - **Speed limit** (60 km/h): what a speeding episode is judged against, and the line the speed charts draw first. The Speeding rule under Rules watches the same figure live; this is the look back.
    - The gap threshold shared by every module (4 hours): a longer silence between two fixes is a gap, and a trip the silence falls in is closed there and marked.

## What the result holds

- **Cards** per vehicle: trips, distance, driving time, mean and top speed, speeding episodes, minutes paused inside trips, fixes; the comparison period's figure beside each.
- **Map**: every trip's path coloured by its speed in six bands that widen: under 10 km/h, from 10, from 20, from 40, from 80 and over 120, green through yellow and red to dark, the way fleet tools and sport apps colour a path. The bands do not move with the limit, so two runs read alike and a drive over a highway is more than one colour. A stretch driven **over the limit** has a dark outline, which is what says speeding on the map; one layer of trip markers, a numbered green one where each trip began and a numbered dark one where it ended, the number being the trip's place in the table; and a red marker carrying the speed where each speeding episode was fastest. The trips table is linked to the map: the trip under the pointer lights up in blue, a click pins it and fits the map to it, a second click lets go. The legend names the speed each colour starts at and shows the outline with the limit. A click on a stretch names its trip with the speed there, and whether that was over the limit, the distance, duration, top speed and where it went from and to. The raw track of the period is a chip of its own, off until asked, so trips and tracks are never the same line.
- **Charts**, in the order a vehicle manager asks:
    - **Speed over the period**, one line per vehicle over the whole selection, not per trip: the fastest speed per step of time (a minute for a day, a quarter of an hour for a week, coarser for more vehicles or a longer period). A vehicle that stood reads zero; where the record is silent the line breaks, since a silence is not a standstill. The **known speed limits** cross it as named lines: the limit of the run, and one per enabled rule of the project that judges a speed (a threshold on `speed_kmh` that asks for more than a value). A rule that holds inside an area says so on its line, since its limit is no limit outside it. Limits of the same speed share a line, and the six lowest stay.
    - **Distance per day** and **driving time per day**, a bar per day of the period with the vehicles stacked, so the bar is the fleet and its parts the vehicles. A day nothing moved is an empty place, not a missing one.
    - **Driving time by hour of the day**, on the project's clock: when the vehicles are on the road, a drive at night included.
    - **Speed by hour of the day**: per vehicle the speed it usually drove at that hour (the median, a solid line) and the fastest (dashed), with the same limit lines.
    - **Time per speed band**: the minutes driven in each band of the map. For one vehicle the bars wear the map's colours; several vehicles stand side by side in their own.
    - **Speeding per day**: the minutes over the run's limit per day, an episode counted on the day it began: whether speeding is a habit or one afternoon.
- **Tables**: the summary per vehicle and period with a mean row for several vehicles; the **trips**, fastest first, each with its number (the marker on the map), start and end, duration, distance, mean and top speed, whether the speed was reported or read between fixes, from where to where, the fixes it holds, the minutes paused and whether a stop or a gap ended it; **per day**, with the trips started, the distance, the driving hours and the first and last movement; and the **speeding** episodes with their start, end, duration, fastest speed and where.
- **Warnings** say what the fixes allow: missing fixes against the sampling interval, gaps, few fixes, impossible speeds left out, and two of the module's own: a vehicle whose fixes carry no reported speed (the speeds are then means over a step and no speeding is judged), and trips cut by a silence in the record.

## The method

- The fixes are the device's own, valid, at their effective time and geometry, attributed to the vehicle by the assignment history. A fix that would need more than 250 km/h from the fix before it is left out and counted.
- The **stop rule** folds the track first: consecutive fixes within the stop radius of the first fix of their run take that fix's coordinates. A receiver standing still wanders a few metres between fixes, and over a night of fixes that wandering adds up to a walk nobody made.
- A step between two fixes is **movement** when the fixes stand apart after the fold, or when the fix it starts from reported a speed above the moving threshold. A **trip** opens at the fix a movement starts from and closes at the fix where the vehicle last arrived once it has stood there for the stop time; a gap closes it at the last fix before the silence. Still time inside a trip shorter than the stop is paused time.
- **Distance** is the sum of the moving steps of a trip; the mean speed divides it by the trip's time without the pauses. The **top speed** is the fastest reported speed on the trip, else the fastest step speed, and the table says which.
- **Speeding** is read off the reported speed alone: consecutive fixes above the limit are one episode, and a fix without a reported speed ends it, since nothing is known of that moment. The episode's marker sits at its fastest fix. A speed reported by an OpenCollar is a whole number of metres per second, a resolution of 3.6 km/h.
- Per day and per hour of the day follow the project's time zone, by the moment each moving step started.
- The **speed of a stretch** is the faster of the speeds its two fixes reported, else the mean over the step; the band and the side of the limit are read off that speed, and the path is cut where either changes.

## What the figures cannot say

- A trip is what the fixes show of it: the distance misses the bends between fixes, and the sampling interval stands beside it for that reason.
- A speed without a reported one is the mean over a step and says nothing about a moment; speeding is judged on reported speeds alone.
- A real move shorter than the stop radius is lost in the fold; a trip cut by a gap may be two.
- A site the project has not drawn cannot name a start or an end.
- The figures describe the tracked vehicles, not the fleet.
- The run has one limit. A line of a rule on the chart says which limits the project knows, not which one held where the vehicle drove: the module does not know the limit of a road.
- A run made before 2026-09-29 keeps the three charts it was made with; its map is coloured by the new bands, since its stretches carry their speed.

## Exports and API

Export gives the summary table as CSV, the trips and speeding points as GeoJSON, the whole document as JSON, and "Make PDF report" renders the run to A4 with the cards as key figures, the map, the charts and the tables. The API is the analysis API of every module (`GET /analysis-modules`, `GET /projects/{id}/analyses/estimate`, `GET|POST /projects/{id}/analyses`, and on a run `GET`, `PATCH`, `POST .../cancel`, `DELETE`, `GET .../geometries` with `kind=trip` or `kind=speeding`, and `GET .../export`), with `module=vehicle_use` and the parameters `entity_ids`, `time_from`, `time_to`, `comparison`, `gap_hours`, `moving_kmh`, `stop_minutes`, `stop_radius_m`, `site_radius_m`, `limit_kmh` and `max_speed_mps`.

## Switching it on and off

`ANALYSIS_MODULES` names the modules a server offers and carries `vehicle_use` by default; a project narrows the list with `analysis_modules` in its settings. The rest is the analysis worker's, as for [Movement](movement.md).
