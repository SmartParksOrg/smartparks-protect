# Device performance

The Device performance page under Analyze answers, for one to a hundred devices of a project over a period of at most a year: how healthy each device is, how regularly it reports against its settings, how well its GNSS fixes come, and how the networks that carry it behave. It is the third analysis module (decisions D213 to D220, `docs/ANALYTICS_DEVICE_PERFORMANCE_PLAN.md`), built on the framework of the movement and grazing modules, and the first whose subjects are devices rather than entities: a collar in a drawer or without an animal is analysed like any other.

## The page

The page lists the module's runs the way the movement page does, and a run opens on the fleet table when it holds several devices: one row per device, the worst first, with the headline indicators of the four areas and a coloured dot beside each (green ok, amber warn, red critical). A click on a row scrolls to the device's section. Under the table, one folded section per device holds the four area cards with every indicator the device reports, the comparison figure in brackets when the run has one, and the device's own charts. A run over one device opens on its section. The map shows the fixes coloured by their accuracy (under 10 m, under 30 m, under 100 m, worse), the coverage hull of each device's fixes and the gateways that heard it, sized by their share of the uplinks; the "Fixes", "Coverage of the fixes" and "Gateways heard" chips switch them.

"Analyse performance" on a device page opens the dialog with that device; a selection on the devices list opens it with the chosen devices.

## The form

- **Devices**: devices picked by name (the entity each tracks today beside it), every device of a type ("Devices of a type"), or every device of the project ("Every device"); at most 100 per run. A device counts when it was assigned to the project at some point in the period; a member with a device scope sees only their devices.
- **Period**: the last 7, 30 or 90 days, the last year, or a custom range; at most 366 days. The figures are daily up to 120 days and weekly beyond.
- **Compare with the period before**: the same indicators over the period of the same length right before, shown in brackets.

The line under the form estimates the run: how many devices, days and fixes it will read.

## The indicators

Every indicator is computed when the device reports the data behind it and left out when it does not: a device without GNSS shows no GNSS card, a device on LoRaWAN alone no Iridium figures. Each carries a level from the driver's declared thresholds (an OpenCollar collar's battery, temperature, accuracy, time to fix and flash bounds) or, where the driver declares none, from the defaults named below; in a fleet run every device is also ranked per indicator, 1 the worst.

### Health

| Indicator | Meaning | Default level |
| --- | --- | --- |
| Battery (V) | The newest battery voltage in the period | warn below 3.6 V, critical below 3.45 V |
| Battery slope (mV/day) | The least-squares slope through the daily medians | warn when falling more than 5 mV a day, critical more than 15 |
| Days to critical | How long the slope gives until the critical voltage; none when the battery is not falling | warn under 60 days, critical under 14 |
| Charging days | Days on which the charging voltage rose above the battery voltage (a solar collar) | none |
| Temperature | The lowest, median and highest device temperature, and the hours above the warn bound | warn at 50 °C, critical at 60 on the highest |
| Reboots | `device_reset` events in the period, with the reason of each in the reboots table | warn at one a week, critical at one a day |
| Longest uptime (days) | The longest uptime the device reported | none |
| Statuses with an error | The share of status messages with any error flag on; the error flags table lists each flag | warn at 10 percent, critical at 50; the flash and battery flags are critical as soon as they are on |
| Flash used (%) | The newest value | warn at 80 percent, critical at 95 |
| Statuses with movement | The share of statuses whose activity was above zero | none |
| Firmware | The firmware versions seen in the period | none |

### Reporting

| Indicator | Meaning | Default level |
| --- | --- | --- |
| Fix interval set, status interval set | The seconds between fixes and statuses the device's settings promise: the type's defaults, the device's attributes, and the settings frames the device sent, in that order of precedence | none |
| Fix interval seen | The median and the 90th percentile of the interval between consecutive fixes | none |
| Missed fixes, missed statuses | One minus the messages seen over the messages the interval promised | warn at 10 percent, critical at 30 |
| Silences | Gaps longer than three expected intervals, the period's edges included, and the longest of them | warn when the longest exceeds a day, critical when it exceeds a week |
| Messages | Source events of the device in the period, over every data source | none |
| Records held invalid | Records the pipeline or a curation holds invalid (a clock ahead, decision D119, among them) and their share | warn when any, critical above 10 percent |

### GNSS

| Indicator | Meaning | Default level |
| --- | --- | --- |
| Fix success | The share of GNSS attempts that produced a fix (`gnss_fix`) | warn below 80 percent, critical below 50 |
| Time to fix | The median and the 90th percentile of `gnss_time_to_fix` | warn at 120 s on the 90th percentile (the driver's bound) |
| Satellites | The median satellites per fix and the share of fixes under four | warn when more than 20 percent had fewer than four |
| Accuracy (m) | The median and the 90th percentile, and the share above the warn bound | warn at 30 m on the median (the driver's bound) |
| PDOP | The median PDOP | warn at 5 |
| Rejected fixes | Fixes an analysis excludes as impossible at the run's maximum speed (15 m/s by default) | warn above 2 percent |
| Fixes per day | Valid fixes per day | none |

### Network, per data source

A LoRaWAN source:

| Indicator | Meaning | Default level |
| --- | --- | --- |
| Messages per day | Source events of the source per day | none |
| Lost uplinks | The frame counter's gaps over its advance: the uplinks the network never delivered; a counter that goes back (a rejoin) starts a new run | warn at 5 percent, critical at 20 |
| Gateways, best gateway, best gateway's share | The distinct gateways that heard the device, the one with the most uplinks and its share; a device heard by one gateway alone warns | warn when a single gateway carries every uplink |
| RSSI, SNR | The median and the 10th percentile of the best gateway's RSSI and SNR per uplink | warn when the 10th percentile RSSI is below -120 dBm or SNR below -15 dB |
| Joins | Join events in the period | warn at one a day |

An Iridium source:

| Indicator | Meaning | Default level |
| --- | --- | --- |
| Satellite sessions, bytes | Sessions in the period and the bytes they carried | none |
| Missed sessions | The MOMSN counter's gaps over its advance | warn at 5 percent, critical at 20 |
| Failed sessions | Sessions whose status carried no data (a timeout, a lost link, a barred modem) | warn at 10 percent |
| Redeliveries | The platform's redeliveries stored as duplicates | none |

The fleet table shows the worst source's lost uplinks and RSSI per device; the network table has one row per device and source.

## What the result holds

The result document carries the summary per period and device, the levels and ranks, the device list with its type, driver and the entity tracked, the defaults used, seven tables (fleet, health, reporting, gnss, network, error flags, reboots), the charts (battery, highest temperature per day, fixes per day, time to fix, accuracy and satellites histograms, messages per day and RSSI per day per source, satellite sessions per day) and the warnings: a device that sent nothing, an unknown fix interval, a period shorter than three expected reports, records held invalid, a driver without health thresholds. The geometries are the coverage hull per device and the gateways heard as points with their share.

## What these figures cannot say

- A missed report is inferred from the device's settings and its messages; a device whose interval changed in the period, or whose settings Protect never read, shows a share to weigh, with the interval it assumed beside it.
- Lost uplinks come from the frame counter; a data source that does not deliver it shows no figure, not zero.
- The battery slope is a straight line through the daily medians; a battery's curve is not straight, so the days to critical are an indication, not a forecast.
- Signal figures are the best gateway's per uplink; a moving device changes gateways, so they describe the network as the device met it.
- Levels come from the driver's thresholds and named defaults; they are not a verdict on the device, and a rank says only where a device stands among the chosen ones.
- Fix success counts the attempts the device reported; a device that never reports a failed attempt shows every attempt as a fix.
- Messages and the network figures count by the time a message reached Protect; a raw log uploaded later counts on the day of the upload, and its records on their own days. The status count falls back to the battery readings when the state history holds no status in the period (a clock repaired by a time offset moves the measurements, not the states).

## Exports, the report and the API

Export gives every table as CSV, the geometries as GeoJSON, the document as JSON, and "Make PDF report": the fleet table as the key figures with its level dots, one section per device with the four cards and the device's charts, the map with the coverage hulls and the gateways, the thresholds behind the levels and the limitations. "The fixes behind it" opens the export dialog with the positions of the devices over the period. The API is the analysis API of [Movement](movement.md) with the module key `device_performance`; the parameters take `device_ids`, `device_type_id` or `all_devices` in place of the entity fields, and a run stores the resolved `device_ids`.

## Switching it on and off

The same switches as [Movement](movement.md): `ANALYSIS_MODULES` (default `movement,grazing,device_performance`) on the server, `analysis_modules` in the project's settings; `analysis:run` starts runs, `project:read` sees them within the scope, `exports:create` makes the report.
