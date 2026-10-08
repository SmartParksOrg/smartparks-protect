# 0039. Habitat selection through hrHSA, in an image of the analysis worker's own

Date: 2026-10-08

Status: accepted

## Context

Tim asked whether hrHSA (Paul Kasko and Ralph Kühn, BSD 3-Clause), a Python framework for habitat selection analysis from telemetry and environmental rasters, could become a separate analysis module. The analytics brief (`docs/ANALYTICS_PHASE1_PLAN.md`, section 20) kept habitat selection out until a module could be used repeatedly, read data Protect holds, support a real decision and beat the external tool; the fixes are here, the question sits behind zoning and corridor decisions, and the package exists and is maintained by the people who asked it. Two things stood in the way: the package's stack (pandas, geopandas, scipy, statsmodels, xarray, rasterio, dask, about a gigabyte, with numpy pinned below 2.5 while the workspace pins 2.5.2) cannot live in the one image of decision D200, and Protect held no per-pixel covariates, only a weekly NDVI mean per polygon.

## Decision

hrHSA is the engine of the seventh module, `habitat_selection`, pinned to one commit and never reimplemented (decision D313): the pooled frequentist resource selection function with one availability domain per animal, leave-one-individual-out validation with the Boyce index, and the relative selection surface; the step selection models and the Bayesian fits are a later step.

The analysis worker gets an image of its own, `docker/analysis.Dockerfile`, built from `services/analysis/image/pyproject.toml` with its own lock: the workspace packages as editable path dependencies, hrHSA from its git commit with the `dask` extra (its `rsf` package imports dask at module level although the authors list it as optional), and numpy overridden to 2.4 for this environment alone (decision D314). Every other service keeps the lean image. The module imports hrHSA inside its run, so the lean API lists it and validates its parameters; a worker whose image lacks the engine fails the run with `MODULE_UNAVAILABLE` and a message that names the image (decision D318).

Covariates come from three sources through a raster boundary beside the weekly series of decision D245 (decision D315): the openEO account's Sentinel-2 NDVI mean of the period and the Copernicus 30 m DEM as GeoTIFFs on the run's grid, the slope derived from the elevation; the distance to the nearest feature of a type, computed on the grid from the project's features; and GeoTIFFs a project uploads, whose header the lean API reads without a raster library so a file without a CRS is refused at once. Fetched rasters are cached in the analysis layers bucket by area, grid and period.

## Alternatives considered

- Our own logistic RSF on numpy: a published method rewritten, without its validation and without the authors' corrections; rejected.
- An export recipe alone: the GeoParquet export already feeds hrHSA outside Protect, which is what the module has to beat; kept as the way for an ecologist with Python, not instead of the module.
- Downgrading numpy and carrying the stack in the one image: a gigabyte in every service for one worker's sake; rejected.
- The covariates from uploads alone (every project would have to bring its layers) or from fetched layers alone (no soil, no land cover); rejected for the three sources together.
- The distance layers through PostGIS as the plan first said: a shapely tree over the projected features in the worker is faster and bounded by the grid; the plan's text notes the departure.

## Consequences

- A server builds two Python images; the lean one is unchanged, and the analysis image rebuilds in seconds on a code change through the uv cache.
- CI runs the habitat tests inside the analysis image against the same services as the other test jobs, and audits the image's lock beside the workspace's.
- The module's figures are hrHSA's; a defect in the fit is reported upstream, not patched here. The pin moves by hand when a release exists.
- A project without the openEO account still runs on an upload and a distance layer; without any layer the form says what to set up.
- The three cautions hrHSA's authors state (use is not quality, the domain decides every contrast, the surface is relative) are printed on every run as its limitations.
