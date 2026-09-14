# Grazing

The Grazing page under Analyze answers, for a herd of tracked grazing animals and the management areas a person picks: how much each area was used, by how many animals, when it rested and for how long, where inside it the animals kept to, and how that compares with the period before, with the seasons, or with another herd. It is the second analysis module of phase 1 (decisions D196 to D203, `docs/ANALYTICS_PHASE1_PLAN.md`), level 1 of the grazing design: from the fixes and the polygons alone, with no environmental data.

Time in an area is a proxy for potential grazing pressure. It is not measured feeding, and the tables say "use", never "grazing".

## The page and the form

The page works as the [Movement](movement.md) page: a list of the analyses, "New analysis" opening the dialog with the form, an opened run with "Edit and run again", "Run as new" or "Run and replace". The form asks:

- **Herd**: entities picked by name, a group with its subgroups ("Analyse grazing" on the Groups page and on the entities list's group filter opens the form with the group), or every entity of a type; at most 100 animals.
- **Areas**: 1 to 50 of the project's zones and geofences (polygons; a circle is a polygon already). No new feature type: a management unit is a zone the person picks. When a project marks its units with `attributes.management.unit = true`, "All management units" picks them at once; the run stores the chosen ids either way. "Grazing in this area" on a zone's panel on the live map and on the Features page opens the form with that area chosen.
- **Period**: presets or a custom range, at most 366 days.
- **Compare with**: nothing, the period before, the seasons (meteorological, in the project's time zone, swapped in the southern hemisphere), or another herd (a group).
- **Weighting**: each animal counts one (the default), an attribute of the entity (`livestock_unit`, for example), or metabolic (body mass to the 0.75, normalised to the herd mean). Animals without a value count one and are named in a warning; every weighted header names the unit.
- **Method**, folded: the gap threshold (4 hours), the absence that starts a new visit (6 hours), the grid cell (100 m), the animal-hours at or below which a day is a rest day (0), the maximum plausible speed (5 m/s for livestock).

The estimate line under the form names what the run cannot use before Run is pressed: an area under one hectare, an invalid polygon, a feature that is not a zone or a geofence.

## What the result holds

- **Cards** per area: use in animal-days per hectare, the relative pressure with its rank, the animals that used it, use and rest days, the longest rest, the hours since the last use; the comparison period's use beside it; the herd's tracked animal-hours and the share inside and outside the areas above the cards.
- **Map**: the use intensity inside the areas as a choropleth of animal-hours per grid cell (the convention of grazing distribution maps: time per cell over the paddock, light to dark), the areas coloured by relative pressure on a five-step ramp (1.0 is the herd's average over the chosen areas), the hotspot outlines and the herd's tracks as toggles that start off; a click on an area names it with its hectares, use, pressure, rank and rest days.
- **Charts**: the daily animal-hours per area over the period, and use per hectare per area (with the comparison period or the second herd beside it).
- **Use and rest by day**: one row per area, one cell per day, empty on a rest day, darker with more animal-hours against the area's busiest day.
- **Tables**: the areas (one row per area and period, per season when asked, per herd when two), the animals (hours, visits, mean visit, first and last use, days used per area), the changes (this period against the period before with the change in percent) and the overlaps (areas that share ground, not a boundary).
- **Warnings**: missing fixes, gaps, irregular sampling, impossible speeds, duplicates, poor GNSS quality, collar changes, animals without a weighting value, animals without fixes, overlapping areas.

## The method

- Each fix carries a time weight: half the interval to the fix before and to the fix after, each capped at the gap threshold, so a collar silent for a day puts no animal-hours anywhere.
- Containment is computed over the fixes already loaded for the herd; a fix inside overlapping areas counts in each and the overlap is listed.
- Per area and animal: time, weighted time, visits (a visit ends after the chosen absence), the mean visit length, first and last use, days used. Per area: animal-hours and animal-days, per hectare from the polygon's geodesic area computed at run time, the weighted figure, the share of the herd's tracked time, the animals that used it, the use days, the rest days (days at or below the threshold), the longest rest, the last use and the hours since.
- Relative pressure is an area's animal-days per hectare divided by the mean over the chosen areas; the rank orders the areas by it.
- Hotspots inside an area are the cells of the residence grid that together hold half of the area's time, at most 60 per area.
- The comparison period and the seasons run the same computation over their windows; a second herd adds rows per herd.

## What the figures cannot say

- Time in an area is a proxy for potential grazing pressure, not measured feeding.
- Only collared animals count; the herd is not extrapolated unless a weighting is chosen, and then the document names it.
- Fix sampling and gaps bias the hours; the missing fix share and the gaps stand in the warnings next to the totals.
- Overlapping areas double-count by design; the overlap is listed.
- Areas are fixed polygons without validity in time; an area that changed during the period must be two features.

## Reports and exports

A saved run with a name, shared with the project, is the report of phase 1; the tables export as CSV, the polygons as GeoJSON and the whole document as JSON, and "The fixes behind it" opens the export dialog with the herd's positions over the period. A monthly utilisation report as a fixed document is noted for later; the result already holds every number and the provenance it needs.

## Levels not built

Level 2 (landscape context: vegetation class, habitat, soil, terrain, water per area), level 3 (environmental response: NDVI, biomass, rainfall, recovery as time series per area) and level 4 (management interpretation: forage demand, carrying capacity, utilisation thresholds, recommendations) would read providers through the extension point of the plan's section 11. None is a prerequisite for level 1, and the level 1 tables are complete without them.

## Switching it on and off

The same switches as [Movement](movement.md): `ANALYSIS_MODULES` on the server, `analysis_modules` in the project's settings; `analysis:run` starts runs, `project:read` sees them within the scope.
