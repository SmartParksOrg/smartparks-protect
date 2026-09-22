# Analytics

The Analyze section: the [Data explorer](data-explorer.md) lists everything an entity or a device produced, one row per moment, aggregates metrics server side and drills down to the rows and source events behind them, and [Export](export.md) produces reproducible files, directly for small selections and through the export service for large ones.

Both are bounded by design (architecture 13.10): no request can return more than a few thousand points per series, and exports stream from the database to the file without holding rows in memory.
- [Data curation](curation.md): reversible, audited corrections on canonical records, bulk jobs, the effective value and export views.
- [Dashboards](dashboards.md): saved views and live tiles on a shared grid per project.
- [Movement](movement.md): distance, speed, rest, day and night, residence time, home range and clusters of tracked animals, computed by the analysis worker from the positions and kept as runs.
- [Grazing](grazing.md): how a herd uses the management areas over time, in animal-days per hectare with rest days, visits, hotspots and the relative pressure per area, compared between periods, seasons and herds.
- [Device performance](device-performance.md): how the devices perform, as a fleet and one by one: battery and reboots, reporting against the settings, GNSS fixes, and the LoRaWAN and Iridium networks per data source, each indicator with a level and a fleet rank.
- [Cardiac monitoring](cardiac.md): how an animal's heart was doing, at what times of day, and how much of it the collar actually heard.
- [Contact tracing](contact-tracing.md): which subjects were near each other, from two kinds of evidence at once — the sightings devices reported over Bluetooth and the proximity their fixes show — with the contact network, the pairs worst first, where they met, and the warnings without which the figures mislead.
