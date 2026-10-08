# Habitat selection

The Habitat selection page under Analyze answers, for up to forty animals of a project over a period of at most a year: which habitat they selected against what was available to them. It fits a resource selection function (RSF) through [hrHSA](https://hrhsa.readthedocs.io), the framework of Paul Kasko and Ralph Kühn (BSD 3-Clause), validates it one animal at a time with the Boyce index, and draws the relative selection surface on the map. It is the seventh analysis module (phase 41, `docs/HABITAT_SELECTION_PLAN.md`, decisions D313 to D318). Everything comes from the positions and the layers the project can read; nothing new is collected from the devices.

## The question an RSF answers

Every fix is a place the animal used. hrHSA draws, inside each animal's own available area, ten times as many places it could have used, reads the layers at both kinds of point and fits a logistic regression of used against available. A positive coefficient on a layer says the animals were found where that layer is high more often than its availability would give; a negative one the opposite. The result is relative: it says how the animals redistributed over what they had, not how good a place is, and not how likely an animal is to be there.

## The subjects

The project's animals: every tracked entity but the people and the vehicles (the People and Vehicles types and their sub-types), which is what the form offers and what the run admits; a vehicle has no habitat to select. An animal with fewer than twenty fixes in the period is left out with a warning, and when the chosen animals together have fewer than twenty the form says so before the run starts. The run needs at least one animal; the validation needs three.

## The layers

The form offers what the project has, grouped by where it comes from:

- **From satellite data**, when a server admin has set up the environmental data provider under Server admin, Environmental data (the Copernicus account of the grazing analysis): **Vegetation (NDVI, Sentinel-2)**, the mean of the period with clouds masked; **Elevation** from the Copernicus 30 m DEM; **Slope** in degrees, derived from the elevation. These are fetched once per area and period and kept, so a rerun reads them back.
- **Distance to the project's features**: for every feature type the project has features of (sites, routes, zones, geofences, fence lines), the metres from each cell to the nearest one. Water points drawn as sites, roads as routes and the park's zones all become layers this way.
- **Uploaded layers**: GeoTIFFs a project admin uploaded under Project admin, Features, Raster layers (soil, land cover, anything a GIS holds), as a number or as classes.

At most eight layers per run. A continuous layer can also enter **squared**, which lets the response peak: a distance that is good up to a point.

## The form

- **Animals**: entities by name or one or more groups (their members with the subgroups join the picks); at most 40 per run.
- **Layers**: the choice above, and the ones also squared.
- **Period**: the last 24 hours, 7, 30 or 90 days, the last year, or a custom range; at most 366 days. No comparison period: the module does not offer one yet.
- **Method**, folded with its defaults on one line:
    - **Available area (MCP quantile)** (0.95): each animal's available area is the convex hull of its fixes within that quantile of the distances to their centre, hrHSA's default. The area decides every contrast, so this is the setting to think about first.
    - **Available points per fix** (10): how many available places are drawn per used fix.
    - **One fix per (hours)** (12): the fixes kept for the fit, so that an hourly animal does not weigh a hundred times a daily one; 0 keeps every fix.
    - **Buffer around the areas (m)** (1,000): how far the rasters reach beyond the animals' areas.
    - **Stop radius (m)** (0, off): the stop rule of the vehicle and movement modules, off by default because a parked receiver's drift is used habitat too.
    - **Validate animal by animal** (on): leave-one-individual-out validation.
    - The gap threshold and the maximum plausible speed shared by every module.

## What the result holds

- **Cards** per animal: fixes, the available area in hectares, the Boyce index of its validation, the excluded fixes.
- **Map**: the **relative selection** surface as cells, five colours by rank with a fifth of the cells each, the value each colour starts at in the legend; each animal's **available area** as an outline; the fixes and tracks as chips, off until asked. A click on a cell gives its selection value.
- **Charts**: the **selection coefficients** as bars (the constant left out); the **Boyce curves**, one line per held-out animal: the predicted selection in ten bins against the ratio of observed to expected use. A rising line is a model that ranks the animal's fixes well.
- **Tables**: the summary per animal; the **coefficients** with their standard error, p value and 95 percent interval; the **validation** per held-out animal with its Boyce index and the fixes on either side; the **layers** with their source, their own resolution (the run's grid is the finest of them), the cells with a value, their mean and spread, and whether the raster was fetched now or read from the cache.
- **A first run over an area waits for the satellite jobs.** The NDVI of a period is computed on the Copernicus side from every Sentinel-2 scene of the period over the area, so the wait grows with the area and the period: about five minutes for one animal's 50 km² over a week, and the better part of an hour for four animals' 340 km² over a month. The run waits up to an hour for them, the NDVI and DEM jobs run at the same time, and a rerun over the same area and period reads both from the cache in seconds. A shorter period or fewer wide-ranging animals is the way to a quick first look.
- **Warnings**: an animal left out for few fixes, fewer than twenty fixes carrying the fit after the thinning (a week of a daily animal thinned to one fix per twelve hours leaves a handful), a layer that could not be read (the run goes on without it), a layer with a value in fewer than nine in ten of the grid's cells (a fix or an available point without one is left out of the fit), a layer without variation over the area, a validation skipped for too few animals, a fold that failed, a Boyce index under 0.5, a fit that did not converge, and the quality warnings every module gives.

## The method

- The fixes are the device's own, valid, at their effective time and geometry, attributed by the assignment history; a fix that would need an impossible speed is left out and counted.
- The run's grid is the UTM zone of the fixes' centre, over the animals' areas and the buffer, at the finest resolution of the chosen layers (10 m for NDVI, 30 m for the DEM and the distances, an upload's own), doubled until the area fits four million cells, so a large park answers coarser rather than refusing.
- Every layer is reprojected onto that grid: bilinear for a number, nearest for classes. The distance layers are computed on the grid from the project's features; the slope with Horn's method over the elevation.
- hrHSA takes the fixes as relocations in the grid's CRS, builds the available area per animal, samples the available points, reads the layers at both, standardises each continuous layer (the summary gives the mean and spread used) and fits a logistic regression with statsmodels' Newton optimiser. The coefficients are on that standardised scale: one unit is one spread of the layer.
- The validation fits the model on every animal but one, predicts the held-out animal's fixes and compares them with points drawn in its own area through a continuous Boyce index in ten bins; the Boyce index is the rank correlation between the predicted selection and the observed to expected ratio across the bins.
- The surface is `exp` of the fitted linear predictor over the grid, read onto cells for the map, at most two thousand cells with the cell size doubled until they fit.

## What the figures cannot say

- Use is not habitat quality: animals are where they are for many reasons, and a place used much may be a poor one that is all there is.
- A coefficient says how the animals redistributed relative to what was available to them, and the available area decides every contrast.
- The selection surface is relative, never a probability of finding an animal there.
- A layer fetched for the period is its mean over the period; a selection that changes within the period is averaged out.
- The engine is hrHSA; Protect assembles its inputs and reads its answer. The step selection models, the Bayesian hierarchical fits and time-varying layers hrHSA also offers are not in this first step.

## Exports and API

Export gives the summary table as CSV, the cells and the areas as GeoJSON or GeoParquet, the whole document as JSON, and "Make PDF report" renders the run to A4. The API is the analysis API of every module, with `module=habitat_selection` and the parameters `entity_ids`, `time_from`, `time_to`, `gap_hours`, `max_speed_mps`, `layers`, `quadratic`, `domain_quantile`, `sampling_factor`, `thin_hours`, `area_buffer_m`, `loio` and `stop_radius_m`; `GET /projects/{id}/analysis-layers` lists what a run may name, and `GET`, `POST` and `DELETE /projects/{id}/layers` are the uploads.

## Switching it on and off, and where it runs

`ANALYSIS_MODULES` names the modules a server offers and carries `habitat_selection` by default; a project narrows the list with `analysis_modules` in its settings. The module runs in the analysis worker's own image (`docker/analysis.Dockerfile`), which carries hrHSA and its stack; a worker started from the lean image refuses such a run with "the analysis worker is not built with hrHSA". A server that builds from the repository has the image; `docker compose build` builds it beside the others.
