# Movement

The Movement page under Analyze answers, for one to twenty-five collared animals over a period of at most a year: how far and how fast they moved, when they rested, how much ground they used and where they kept returning. It is the first analysis module (decisions D196 to D203, `docs/ANALYTICS_PHASE1_PLAN.md`); it reads the project's positions and writes only its own result tables, and a project or a server can switch it off without touching anything else.

## The page

The page lists the module's analyses: every run a person may see, newest first, with its status, subjects, period, who ran it, when it expires and whether it is saved and shared. "New analysis" opens a dialog with the form; Run queues the analysis and returns to the list, where the new run shows its progress. A run that finishes while the list is open says so with a way to open it. Opening a run shows its result under "All analyses", with a folded "Settings of this run" block listing everything it was asked.

"Edit and run again" on an opened run brings the same dialog back with that run's settings filled in. "Run as new" keeps the old run and adds a new one; "Run and replace" gives the new run the old one's name and sharing and removes the old one, for a saved analysis that should follow new data.

## The form

- **Subjects**: entities picked by name, a group with its subgroups, or every entity of a type; at most 25 per run. Devices are not subjects: a collar's fixes belong to the animals it tracked, by the assignment history.
- **Period**: the last 7, 30 or 90 days, the last year, or a custom range; at most 366 days.
- **Compare with**: nothing, or the period of the same length right before.
- **Method**, folded with its defaults on one line: the gap threshold (4 hours; a longer silence between two fixes is a gap, not movement), the maximum plausible speed (15 m/s; a fix that would need more is left out and counted), the grid cell (100 m; residence time, hotspots and the cluster distance), and the home range methods: MCP 95 %, KDE 50 % and 95 % (bandwidth automatic or in metres), clusters.

The line under the form estimates the run: how many animals, days and fixes it will read, and what to change when a bound is crossed. "Analyse movement" on an entity page opens the dialog with that animal and the last 30 days filled in.

## The run

The analysis worker computes a run, one at a time per server, with its own statement and wall-clock timeouts. A run is unsaved until it is given a name with "Save…"; an unsaved run expires a few days after it finished (`ANALYSIS_RETENTION_DAYS`, 7 by default) and a saved one never. A run is visible to the person who ran it only, until they switch "Shared with the project" on; project admins see every run of the project and may rename, share or delete it. Anyone with `project:read` sees the runs they may see, inside their scope; `analysis:run` (Analysts and Admins) starts, saves, shares, cancels and deletes their own runs.

## What the result holds

- **Cards** per subject: distance, daily distance, median speed, stationary share, MCP and KDE 95 % areas, the number of fixes, and the comparison period's figure beside each.
- **Map**, with the live map's controls (base map, 3D terrain, full screen, zoom, north, fit): the subjects' tracks over the main period (with the fixes as points and a heatmap as further chips) and, toggled by chips, the MCP hull, the KDE isopleths, the hotspot cells and the cluster hulls, each in the subject's colour; a click on a polygon names it with its area and its share of time or fixes.
- **Charts**: daily distance, the speed histogram (fixed bins from under 0.01 to over 10 m/s, so every animal shares one axis), activity by hour of the day, the rose of turning angles, the net squared displacement, and distance by day, twilight and night.
- **Table**: every figure per subject and period, with a mean and standard deviation row for groups; secondary columns hidden on a phone.
- **Warnings** above the results say what the fixes allow: missing fixes against the sampling interval, gaps, irregular sampling, impossible speeds left out, duplicates collapsed, poor GNSS quality, a collar change inside the period, too few fixes for a home range.

## The method

All arithmetic is on the sphere with the haversine; positions are WGS 84 and a park is small.

- Steps between consecutive fixes give length, duration and speed; a step longer than the gap threshold is a gap and counts in nothing but the quality report. Distance is the sum of non-gap steps, reported with the share of the period the non-gap steps cover, so a sparse track is not read as a short one. Daily distance divides by the covered time.
- Displacement is the great-circle distance from the first fix; the net squared displacement per fix draws the chart.
- A step below 0.05 m/s is stationary; runs of at least 30 minutes are stationary periods.
- Day, twilight and night follow the sun's elevation at the start of each step (a compact solar position formula, no dependency); calendar days follow the project's time zone.
- Residence time snaps each fix to a cell of the chosen size on a local metric grid; each fix carries half the interval to its neighbours, capped at the gap threshold, so a silent day puts no time anywhere. A visit ends after 12 hours away from the cell. Hotspots are the cells that together hold half of the time.
- MCP is the convex hull of the fixes inside the 95th percentile of distance from their centre. KDE is a Gaussian kernel density on a grid of at most 250 cells a side (the reference bandwidth of Worton unless given); the 50 and 95 % isopleths are the unions of the densest cells holding that share of the volume, not smoothed contours. Areas come from PostGIS on the geography.
- Clusters are `ST_ClusterDBSCAN` in PostGIS over the subject's fixes, with the grid cell as the distance and five points as the minimum; their convex hulls and fix shares are geometries of their own.

## What the figures cannot say

- Distance from fixes underestimates the path between them; the sampling interval stands next to the distance for that reason.
- Speed is the mean over a step, not an instantaneous speed.
- The KDE depends on the bandwidth and the grid; its isopleths are cell unions. The MCP includes ground never visited between far fixes.
- Residence time on a regular grid depends on the cell size and is biased by irregular sampling.
- Day and night by the sun ignore the animal's own rhythm and the cloud cover.
- The results describe the collared animals, not the population.

## Exports and API

Export gives the summary table as CSV, the polygons as GeoJSON (with subject, kind, level, area and period as attributes, for QGIS), the whole document as JSON, and "Make PDF report": the server renders the run to A4 (the project, the period and the subjects, the settings, the warnings, the key figures, the map as a picture, the charts, the tables, the limitations, page numbers) and "Download PDF" appears on the run when it is ready; the PDF stays with the run; "The fixes behind it" opens the export dialog with the positions of the subjects over the period, as GeoJSON by default. The API is `GET /analysis-modules`, `GET /projects/{id}/analyses/estimate`, `GET|POST /projects/{id}/analyses`, and on a run `GET`, `PATCH` (`name`, `shared`), `POST .../cancel`, `DELETE`, `GET .../geometries` (GeoJSON, `kind` and `subject_id` filters) and `GET .../export?what=document|geometries|summary&format=json|geojson|csv`.

## Switching it on and off

`ANALYSIS_MODULES` (default `movement,grazing`) names the modules a server offers; an empty value hides the section, the routes answer 404 and the worker sleeps. A project narrows the list with `analysis_modules` in its settings. `ANALYSIS_CONCURRENCY`, `ANALYSIS_TIMEOUT_SECONDS`, `ANALYSIS_STATEMENT_TIMEOUT_SECONDS` and `ANALYSIS_MAX_FIXES` bound the worker. The `analysis` service in `docker-compose.yml` runs it; the core keeps working when it is stopped, and queued runs wait for it.
