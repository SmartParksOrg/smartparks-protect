# Gateways and connectivity

Gateways are separate objects from devices (architecture 20, decision D66). The registry is
server level: one row per (data source, provider gateway id) with a name, location, state,
last seen, the platform's latest counters and provider diagnostics as attributes. A project
sees every gateway of the data sources its devices have an identity on, whether or not that
gateway heard one of them (decision D175, ADR 0027); the all-projects scope sees the whole registry.

## Where rows come from

- Receptions: every uplink's gateway list (`gateway_receptions`) registers the gateway, marks
  it online and records the reception's location when the platform sends one.
- Gateway events: the ChirpStack adapter subscribes to `gateway/+/event/stats` (counters and
  location) and `gateway/+/state/conn` (online, offline). They are stored as source events
  without a device and update the registry; nothing is published on the bus.
- Gateway Mesh relays (ChirpStack 4.9 and later, decision D237): a relay gateway has no
  backhaul; its uplinks reach ChirpStack through a border gateway and are credited to that
  one, so a relay never has receptions of its own, and ChirpStack learns of it from the
  heartbeat it sends every stats interval. The sync reads the tenant's relay gateways with the
  ordinary ones and keeps them in the registry marked `kind: relay` (the 4-byte relay id as
  the external id, state, last seen, region), so the Gateways page and the map show them
  beside the border gateways with a "Relay (mesh)" mark; a person can set a relay's location
  like any gateway's. The relay path (which relay hears which, with the signal per hop) is only
  in the heartbeat on ChirpStack's MQTT broker, not in the API; reading it waits for a source
  whose broker is reachable (decision D238).
- Sync: the ingest service reads every listing adapter's gateway list through the adapter's
  management connector (names, descriptions, locations, states) two minutes after start and
  every 24 hours after that, per data source with its API channel switched on, logging and
  skipping a source that fails (decision D176); Server admin, Data sources, Sync gateways does
  the same read immediately for one source. Public networks without a gateway API (KPN,
  Netmore, akenza) only ever show what receptions reveal.

Administrators can override the name and location of a gateway under `PATCH /admin/gateways/{id}`. A project admin places a gateway the network gave no location for (a Gateway Mesh relay, a gateway on a network without a gateway API), or corrects one, from the gateway's dialog on the Gateways page or its panel on the live map (decision D239): type the coordinates, click the small map, or take the browser's position while standing at the gateway; `PATCH /projects/{id}/gateways/{gateway_id}/location`, both coordinates empty clearing a location set by hand. A location set by a person is kept over the platform's.

## Screens

Network, Gateways lists every gateway of the project's data sources: the ones that heard the
project's devices in the last 30 days busiest first with state, when the network last heard
from the gateway itself, source, receptions, devices, mean RSSI and SNR, last reception and
location, then the ones that heard nothing, most recently seen first; a source filter narrows
the list to one network and the footer says how many heard nothing in the last 30 days. There
is no window to pick: every figure covers the last 30 days, and the gateway's own last seen has
no window at all, so a gateway that heard nothing in a month still says when the network last
heard from it. On a phone both tabs show a card per row with the same figures. A row opens
the gateway's own page (decision D369), as a device or an entity has one, under Network,
Gateways, {gateway}; the live map's gateway panel and the search lead there too:

- Overview: the status with the reason when it is silent, when the network last heard from
  the gateway and when it last relayed one of the project's devices, when it was first seen,
  the source, the gateway id, the location with its origin and a small map, the devices heard
  in the last 30 days with receptions, mean signal and last reception, the platform's counters
  and diagnostics, and the platform's own page when the data source has a gateway link. Rename
  and Set or Change location sit in the header for a project admin. A gateway the network's
  list does not carry (another tenant's, heard through its uplinks alone) says so: its name
  and its own status reports never reach Protect, so its status follows its receptions.
- Coverage: the positions the project's devices were at when this gateway heard them over a
  period (a day to 90 days), coloured by signal as the live map colours them, each with its
  line to the gateway, the view fitted to all of it.
- Traffic: the receptions it relayed per day over a window as bars, a day it relayed nothing
  left empty, then the messages themselves with the Traffic page's filters and pages.

## Status

A gateway's status is derived when it is read (decision D370). The registry keeps the last
word about the gateway and who gave it: the platform's gateway list or a connection event
(`platform`), or an uplink the gateway relayed (`reception`), with the moment. The platform
hears a gateway's own status reports whether or not a device spoke, so its word stands while
it is fresh, within `GATEWAY_PLATFORM_WORD_HOURS` (36 hours, longer than the daily sync).
Otherwise the gateway reads `online` while something was heard from it within
`GATEWAY_SILENT_HOURS` (24 hours by default) and `silent` after that, in the sand tint on the
list, the page and the map; `offline` is the platform's word and stands until the gateway is
heard again; a gateway nothing was ever heard from is `unknown`. A gateway known from its
receptions alone, such as another tenant's gateway on a shared ChirpStack, therefore reads
silent a day after its last relayed uplink, which is all Protect can know about it; switching
on the source's MQTT channel brings the gateway status reports of that network in as well.

Device connectivity lists every device with the number of gateways that heard it, the best
gateway and its share of the device's uplinks, mean signal and last reception, least covered
first. A device heard by one gateway only is at risk: when that gateway fails, the device is
silent. Network health and device health stay distinct: a device can be healthy but poorly
connected, or connected well while reporting internal faults.

## Where a gateway's position comes from

The registry keeps one position per gateway with its source and time. A platform's gateway list or gateway event places it (`platform`); coordinates that a platform sends on an uplink for the receiving gateway place it as well (`reception`; ChirpStack, The Things Stack and LORIOT send them per gateway, KPN's ThingPark for the best receiving gateway only); a position set by an administrator on the gateway (`admin`) is kept whatever the platform sends afterwards. Every reception keeps the platform's gateway fields as they came, so nothing is lost for a later network map or coverage analysis.

## Coverage

Heard positions (decision D107) are where the project's devices were when a gateway received their uplink. Every position is joined to the receptions of the same uplink, so a heard position carries the best RSSI among the gateways that heard it, and shows as a dot coloured from red (weak, about -120 dBm) to green (strong, -80 dBm and better). The layer shows only where trackers were: a blank area may still have coverage. Positions that reached the platform without a LoRaWAN reception, such as a Bluetooth log, are not part of it.

The controls work like the tracks and the heatmap (decision D373). A signal icon sits behind every entity and device in the layers panel and in their panels on the map, and behind every gateway on the Coverage tab and in the gateway's panel: a click shows that object's heard positions, a second click hides them, and several add up. For an entity or a device these are every position of the device heard in the period, with every gateway that heard it; for a gateway, every position that gateway heard, wherever the map looks. The Coverage tab's tick "Heard positions in view" adds everything heard inside the current view for the whole project, kept within a box a little larger than the view so a small pan needs no new read. The toggles travel in the link, as the tracks do, so a view can be shared.

While anything is on, a "Heard positions" card beside the Tracks and Heatmap cards says how many toggles and how many positions over which period, shows a bar while a read runs, and its gear opens the settings: the period (a day to 90 days), "Lines to the gateways" and the signal legend; Clear switches everything off. The lines (decision D368), off until switched on and kept with the period in the layer preference, draw the path every uplink took: one thin grey line from the heard position to each gateway that received it, so a fix heard by three gateways shows three lines and a gateway's reach reads off the map; they follow the drawn points, the newest ten thousand, and come as one feature per gateway. A gateway's own Coverage tab shows the same for that gateway alone. The read is answered from an index on the receptions by device and uplink (decision D371).

## API

`GET /projects/{id}/gateways?hours=`, `GET /projects/{id}/gateways/{gateway_id}`,
`GET /projects/{id}/gateways/{gateway_id}/days?hours=` (the receptions of the scope's devices per UTC day, with devices and mean signal; 24 hours to 30 days),
`GET /projects/{id}/connectivity?hours=`, `GET /admin/gateways`, `PATCH /admin/gateways/{id}`,
`POST /data-sources/{id}/sync-gateways`. `GET /projects/{id}/traffic` and its `count` take `gateway_id` for the messages one gateway relayed.
- `GET /projects/{id}/coverage?bbox=&zoom=&hours=&gateway_id=&device_id=&lines=`: heard positions in the window and viewport as points (the newest 10,000, each with its position `id`) or, with `mode=hexagons`, as hexagons, with the share per gateway; `gateway_id` keeps the receptions of those gateways, `device_id` the positions of those devices with every reception, both together the union (decision D373); `lines=true` adds one `MultiLineString` per gateway (`kind: path`, the gateway's name, `receptions`): the lines from the drawn points to the location of the gateway that received them.
