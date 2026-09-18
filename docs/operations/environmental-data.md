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
3. Open **Server admin, Environmental data** in Protect, put the client id and the secret in
   and press Save, then **Test connection**. The secret is stored encrypted and never shown
   again; a change takes effect on the next analysis run, without a restart.

A server may carry the account in its environment instead, as `COPERNICUS_CLIENT_ID` and
`COPERNICUS_CLIENT_SECRET` (in the vaulted host variables for an Ansible-managed server, never
in the repository, then `--tags env-refresh` to deploy them). What is set on the page wins; the
environment stands in while the page is empty, and the page says so.

A large deployment can ask Copernicus for a service account instead, through their help centre
with a project description; the credentials go in the same place.

## Turning the layer off for one run

The vegetation layer is the slowest part of a grazing run. The run form has a **Vegetation per
area** switch under the method options; off, the run does everything else exactly as before and
asks the provider nothing.

## What it costs

One grazing run with a landscape layer is one batch job on their side: the areas' bounding box,
the period, the cloud mask and a weekly mean. Two small areas over two months took about four
and a half minutes and five credits on 2026-09-17. A run reads the cache first
(`environment_samples`, one row per area, week and layer) and asks the provider only for the
weeks it does not hold, so a rerun, a comparison period and the next month's report cost only
what is new. A week that has not ended yet is never cached, because a cloud-free pass may still
come, so a period that runs up to today asks for its last week again every time.

## What Protect asks for

The vegetation index (NDVI) per area and week: Sentinel-2 level 2A, the scene classification's
cloud mask, the red and near-infrared bands, the weekly mean per pixel and then the mean per
area and per cell of the map's mosaic (both go up in one job, so the mosaic costs no second
run). Protect stores the weekly numbers, never the imagery. Weeks without a cloud-free
observation are kept as gaps, and a period where fewer than half the weeks have one is marked
in the run's warnings.

## When it fails

A provider that cannot answer (no credits, an outage, a job that ends in error) never fails a
run: the analysis completes without the layer and carries a warning that says what happened.
The same holds when no account is set up. **Test connection** on the Environmental data page
asks for a token and the collection, which costs no processing quota, so it tells an
administrator whether the account works without spending anything.
