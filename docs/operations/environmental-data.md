# Environmental data

The grazing analysis can show how each management area's vegetation moved over the period
beside how much it was used (decision D246). The figures come from Sentinel-2 imagery through
the Copernicus Data Space, which a server reaches with its own account (decision D245). Without
an account the analysis runs exactly as before and says once, in its warnings, that there is no
vegetation layer.

## The account

1. Register at [dataspace.copernicus.eu](https://dataspace.copernicus.eu/). An email address
   and a password are enough; the basic tier is free and carries a monthly processing quota.
2. Sign in to the [dashboard](https://shapps.dataspace.copernicus.eu/dashboard) and create an
   OAuth client under the user settings. The client id and the secret are shown once.
3. Put both in the server's environment as `COPERNICUS_CLIENT_ID` and
   `COPERNICUS_CLIENT_SECRET` (in the vaulted host variables for an Ansible-managed server,
   never in the repository), then `--tags env-refresh` to deploy them.

A large deployment can ask Copernicus for a service account instead, through their help centre
with a project description; the two settings are the same.

## What it costs

One grazing run with a landscape layer is one batch job on their side: the areas' bounding box,
the period, the cloud mask and a weekly mean. Two small areas over two months took about four
and a half minutes and five credits on 2026-09-17. A run reads the cache first
(`environment_samples`, one row per area, week and layer), so a rerun, a comparison period and
the next month's report ask only for the weeks that are new.

## What Protect asks for

The vegetation index (NDVI) per area and week: Sentinel-2 level 2A, the scene classification's
cloud mask, the red and near-infrared bands, the weekly mean per pixel and then the mean per
area. Protect stores the weekly numbers, never the imagery. Weeks without a cloud-free
observation are kept as gaps, and a period where fewer than half the weeks have one is marked
in the run's warnings.

## When it fails

A provider that cannot answer (no credits, an outage, a job that ends in error) never fails a
run: the analysis completes without the layer and carries a warning that says what happened.
The same holds when the settings are empty.
