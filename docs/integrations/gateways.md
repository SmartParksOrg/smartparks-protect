# Gateways and connectivity

Gateways are separate objects from devices (architecture 20, decision D66). The registry is
server level: one row per (data source, provider gateway id) with a name, location, state,
last seen, the platform's latest counters and provider diagnostics as attributes. A project
sees the gateways that received its devices' uplinks.

## Where rows come from

- Receptions: every uplink's gateway list (`gateway_receptions`) registers the gateway, marks
  it online and records the reception's location when the platform sends one.
- Gateway events: the ChirpStack adapter subscribes to `gateway/+/event/stats` (counters and
  location) and `gateway/+/state/conn` (online, offline). They are stored as source events
  without a device and update the registry; nothing is published on the bus.
- Sync: Server admin, Data sources, Sync gateways reads the platform's gateway list through
  the adapter's management connector (names, descriptions, locations, states). Public networks
  without a gateway API (KPN, Netmore, akenza) only ever show what receptions reveal.

Administrators can override the name and location of a gateway under `PATCH /admin/gateways/{id}`.

## Screens

Network, Gateways lists the gateways that heard the project's devices in the window, busiest
first: state, source, receptions, devices, mean RSSI and SNR, last reception, location. The
detail shows the platform counters, links to the platform (when the data source has a gateway
link template), diagnostics and the devices heard.

Device connectivity lists every device with the number of gateways that heard it, the best
gateway and its share of the device's uplinks, mean signal and last reception, least covered
first. A device heard by one gateway only is at risk: when that gateway fails, the device is
silent. Network health and device health stay distinct: a device can be healthy but poorly
connected, or connected well while reporting internal faults.

## Where a gateway's position comes from

The registry keeps one position per gateway with its source and time. A platform's gateway list or gateway event places it (`platform`); coordinates that a platform sends on an uplink for the receiving gateway place it as well (`reception`; ChirpStack, The Things Stack and LORIOT send them per gateway, KPN's ThingPark for the best receiving gateway only); a position set by an administrator on the gateway (`admin`) is kept whatever the platform sends afterwards. Every reception keeps the platform's gateway fields as they came, so nothing is lost for a later network map or coverage analysis.

## Coverage

The live map's Coverage tab (decision D107) shows where the project's collars were heard. Every position is joined to the receptions of the same uplink, so a heard position carries the best RSSI among the gateways that heard it. Switch on "Heard positions", pick a period (a day to 90 days) and, if wanted, untick gateways to see the footprint of the rest. The positions show as dots coloured from red (weak, about -120 dBm) to green (strong, -80 dBm and better) at every zoom, the newest ten thousand in view when there are more (decision D123; the hexagon aggregation stays available to API users). Each gateway row shows how many heard positions it received and its share of all heard positions in view. The layer shows only where trackers were: a blank area may still have coverage. Positions that reached the platform without a LoRaWAN reception, such as a Bluetooth log, are not part of it.

## API

`GET /projects/{id}/gateways?hours=`, `GET /projects/{id}/gateways/{gateway_id}`,
`GET /projects/{id}/connectivity?hours=`, `GET /admin/gateways`, `PATCH /admin/gateways/{id}`,
`POST /data-sources/{id}/sync-gateways`.
- `GET /projects/{id}/coverage?bbox=&zoom=&hours=&gateway_id=`: heard positions in the window and viewport as points (the newest 10,000) or, with `mode=hexagons`, as hexagons, with the share per gateway.
