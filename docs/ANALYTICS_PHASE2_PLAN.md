# Analytics phase 2: movement methods and landscape context

Written 2026-09-17 with Tim, after a look at what ecologists and reserve managers ask of
tracking analytics beyond the three modules we have. Decisions D243 to D246 in
`PROJECT_PLAN.md`; the phase is 29 there. Nothing here changes the framework's contract
(`docs/ANALYTICS_PHASE1_PLAN.md`, sections 5 to 7): two modules gain methods and one provider
fills the environmental boundary that section 11 of that plan left empty.

## 1. Why this phase, and why now

The movement module answers where an animal was and how far it went. Two questions ecologists
ask next stay open: how large its range is once the fixes' autocorrelation is accounted for
(a KDE over hourly fixes overstates confidence and understates the range), and what kind of
movement the year shows, resident, migratory or dispersing. Both build on primitives the
module already has, the KDE grid and the net squared displacement per fix.

The grazing module counts animal-hours per management area. The managers' question is use
against what the land offers: a heavily used area that is green means something else than one
that is bare. The plan reserved a place for that as level 3 of grazing and drew an
environmental provider boundary without a provider. A vegetation index per area over time is
the first layer worth having, and Sentinel-2 gives it openly at ten metres every five days.

Forecasting, behavioural states, habitat selection models and corridor analysis stay out: each
needs the landscape layers first or a validation we cannot do without users, and a wrong label
misleads more than none.

## 2. Decisions

| Id | Decision | Choice |
| --- | --- | --- |
| D243 | The phase covers movement methods and landscape context together, released as one | Over movement alone or landscape alone. |
| D244 | The autocorrelation-aware home range is our own approximation, named as such | An Ornstein-Uhlenbeck variogram fitted to the fixes gives the effective sample size; the KDE bandwidth widens with it; the document calls the result an autocorrelation-corrected KDE, never AKDE, and states the approximation. Over running the reference R package in a worker container (a second runtime and language) or skipping it. |
| D245 | The first environmental provider reads Sentinel-2 through the Copernicus Data Space openEO API | Free with an account, European, NDVI aggregated per polygon on their side, so Protect stores time series and no rasters. Over Google Earth Engine (wider catalogue, a cloud project per server), which the boundary admits later. |
| D246 | The vegetation figures appear inside the grazing analysis first | Per management area, as level 3 of the grazing design: the index over the period, the change against the period before, use against forage in one table and one chart. A landscape module of its own follows when land cover or burn scars are wanted. |

## 3. Movement: the autocorrelation-corrected home range

What: a fourth method beside MCP, KDE and clusters, `akde_like` in the parameters and
"KDE, corrected for autocorrelation" in the interface.

How, in `shared/shared/analysis/primitives/homerange.py`:

1. The semivariogram of the fixes per subject: mean squared displacement against the time lag,
   over lags up to a quarter of the period, on the fixes as they are (irregular sampling is
   binned by lag).
2. An Ornstein-Uhlenbeck fit: the variogram's asymptote (the range's variance) and the time
   scale at which it is reached (the position autocorrelation time). Least squares over the
   binned variogram; a fit that does not converge, or an autocorrelation time longer than half
   the period, means the range is not stationary over the period and the method reports so
   instead of a number.
3. The effective sample size: the number of fixes divided by the mean autocorrelation between
   them at the observed lags (the Fleming and Calabrese 2017 form). Hourly fixes of an animal
   whose position decorrelates over two days count as a few dozen independent fixes over a
   month, not seven hundred.
4. The KDE bandwidth by the reference rule on the effective sample size instead of the fix
   count, over the same grid and isopleths as the plain KDE. Areas at 50 and 95 percent, and
   the autocorrelation time and the effective sample size in the summary so a reader sees why
   the corrected range is larger.
5. Tests against a simulated Ornstein-Uhlenbeck track with a known range: the corrected 95
   percent area within twenty percent of the truth where the plain KDE is far below it; the
   non-stationary case reports rather than computes.

What it is not: the full AKDE of the reference implementation (a fitted continuous-time
movement model with its own kernel). The document's limitations say so in one line.

As built (2026-09-19): step 2's rule is an eighth of the period, not half. The lags drawn reach
a quarter of the period, and the plateau has to lie inside them to be measured rather than
extrapolated; over a month a random walk and a range that takes a week to cross fit the same
rising curve, and the simulated random walks of the tests passed the half rule as stationary.
Step 4 uses the fitted range variance in the reference rule as well as the effective sample
size, which is the same rule with better inputs. Step 5 holds on average over eight simulated
tracks rather than on any one: forty days of a two-day range is ten to twenty independent
looks, and one track's own spread is that far from the process's either way.

## 4. Movement: the strategy from the net squared displacement

What: a classification per subject of the NSD curve the module already computes into
resident, migratory, dispersal or nomadic, with the fitted curve on the existing NSD chart and
the class in the summary and the table.

How, in `primitives/strategy.py`:

1. The four models of Bunnefeld and others (2011) fitted to the NSD by day: resident (a
   plateau, an asymptotic curve), migratory (a double sigmoid out and back), dispersal (a
   single sigmoid to a new plateau), nomadic (a line through the origin).
2. The model with the lowest corrected Akaike information wins; the margin to the second is
   reported, and a margin under two units reads "unclear" rather than a class.
3. The fitted parameters people read: for migration the departure and return days and the
   distance between ranges; for dispersal the departure day and the distance; for residency the
   range radius.
4. The class needs a period long enough to show it: under sixty days the module reports the
   curve without a class and says why.
5. Tests on synthetic NSD curves of each shape, with noise, and one real track from the
   fixtures.

As built (2026-09-19): the migratory curve keeps one time scale for the way out and the way
back (four parameters, not five), and a departure must lie at least a week inside the period —
a step before the first fix is a plateau and belongs to the resident curve, a step after the
last fix is a line and belongs to the nomad's; without that bound the dispersal curve imitated
both and a simulated resident year read "unclear". No real track is in the fixtures yet; the
dev-server run of P8 is that test.

## 5. Landscape: the first environmental provider

What: `shared/shared/analysis/environment/copernicus.py`, an `EnvironmentalDataProvider`
(plan 1, section 11) with key `copernicus_openeo` and the layer `ndvi`.

How:

1. Authentication with a Copernicus Data Space account through openEO's OpenID Connect client
   credentials (a client id and secret made in the account's dashboard), stored as a server
   setting the way mail and Telegram are: `COPERNICUS_CLIENT_ID` and `COPERNICUS_CLIENT_SECRET`
   in the environment, vaulted in the host vars, shown on the System health page as
   configured or not. No key, no provider: the grazing analysis runs as today.
2. `sample("ndvi", geometries, period)`: one openEO process graph per run, `load_collection`
   of Sentinel-2 level 2A over the union of the areas and the period with the cloud mask from
   the scene classification, NDVI from the red and near-infrared bands, `aggregate_spatial`
   with the mean and the count of valid pixels per area, `aggregate_temporal_period` by week,
   run as a synchronous job (the areas are small, the periods months). The answer is a time
   series per area with the valid-pixel share, which the module uses to grey out weeks under
   cloud.
3. A cache of the sampled series in a table of its own, `environment_samples` (provider,
   layer, geometry hash, week, value, valid share), so a rerun or the comparison period reads
   what was fetched before and the provider is asked only for new weeks. The analysis tables
   stay the module's own; the cache is the provider's.
4. Budget: one openEO request per run, bounded to fifty areas and two years; a request that
   exceeds openEO's synchronous limit is split by period. A provider error or a timeout adds a
   warning and the run completes without the layer, as section 11 rules.
5. Tests with a recorded openEO answer as a fixture (the shape of the JSON, from the API's
   documentation until an account exists) and a fake provider in the module tests.

## 6. Grazing: level 3 columns

What the grazing document gains when the provider answers:

- Per area: the mean vegetation index over the period, its change against the period before
  (or the same weeks a year earlier when the comparison is the seasons), the share of weeks
  with a valid observation, and the level: warn when the index fell more than a named share
  while use stayed or grew.
- One table, "Use against vegetation": animal-days per hectare beside the index and its
  change, sorted by pressure, so the areas used hard while greening down come first.
- One chart per run: the index per area by week over the period, the comparison period faint.
- The area cards carry the index with its dot; the PDF report gets the table and the chart.
- Warnings: the provider not configured (once, with the setting to fill), a cloudy period
  (share of valid weeks under half), a provider failure (the run is complete without the
  layer).

Nothing here interprets: no carrying capacity, no forage demand, no recommendation. Those are
the plan's level 4 and wait for the users' reading of level 3.

## 7. Framework changes, listed

- `MovementParameters.methods` admits `akde_like`; `strategy: bool` (default on) asks for the
  classification.
- `GrazingParameters.landscape: bool` (default on when a provider is configured) asks for the
  vegetation layer.
- `environment.py` gains the registry's first entry and the `LayerSample` time-series shape it
  already describes; a module asks for a layer by name and never names the provider.
- Migration: `environment_samples`.
- Settings: `COPERNICUS_CLIENT_ID`, `COPERNICUS_CLIENT_SECRET`; the System health page shows
  the provider's state.
- The report engine: the new table and chart of grazing, the corrected range in movement's key
  figures and legend, the strategy class on the movement cards.
- Limits: the corrected range and the strategy fit are bounded by the existing subject and fix
  limits; the provider by fifty areas and two years.

## 8. Tasks

- [x] P1 `primitives/homerange.py`: the variogram, the Ornstein-Uhlenbeck fit, the effective
  sample size, the corrected KDE; unit tests on a simulated track.
- [x] P2 `primitives/strategy.py`: the four NSD models, the selection with its margin, the
  parameters people read; unit tests on synthetic curves.
- [x] P3 the movement module: the method and the classification in the document, the fitted
  curve on the NSD chart, the class on the cards and in the table, the limitations; the report.
- [x] P4 `environment/copernicus.py`: authentication, the process graph, the synchronous job,
  the time series per area; a recorded answer as fixture; the settings and the System health
  line.
- [x] P5 the cache `environment_samples` and its migration; the reuse across runs.
- [x] P6 the grazing module: the level 3 columns, the table, the chart, the levels and the
  warnings; the report.
- [ ] P7 docs: `docs/analytics/movement.md` and `grazing.md`, this document's state, the
  operations guide for the Copernicus account, `DEVELOPERS.md`, the changelog.
- [ ] P8 the dev server: a Copernicus account and its credentials in the vault; a movement run
  over the Okonjima devices with the corrected range and the strategy; a grazing run over the
  Smart Parks cows with the vegetation columns; Tim's reading.
- [ ] P9 release v2.7.0 after the exit criteria.

## 9. Exit criteria

- A movement run over an animal with hourly fixes shows the corrected 95 percent range larger
  than the plain KDE's, with the autocorrelation time and the effective sample size beside it,
  and a simulated track with a known range comes within twenty percent of it.
- A movement run over a full year classifies a resident animal as resident with a clear
  margin, and a run over sixty days or less says it cannot.
- A grazing run over the management areas shows the vegetation index per area by week with the
  cloudy weeks greyed, the change against the period before, and the "Use against vegetation"
  table; the same run without the Copernicus credentials completes with the warning and no
  layer.
- The PDF reports of both carry the new table, chart and figures.
- The framework's contract, the core and the live map are untouched; the module list empty
  still hides the section.

## 10. Later, not in this phase

- Land cover, burn severity and surface water from the same provider or from Google Earth
  Engine through the same boundary, as a landscape module of its own.
- Behavioural states and movement forecasts, once a validation with users is possible.
- Habitat selection models and corridors, which need the landscape layers above.
- Interpretation: carrying capacity, forage demand, thresholds and recommendations (level 4
  of grazing).
