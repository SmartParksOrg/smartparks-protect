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

## API

`GET /projects/{id}/gateways?hours=`, `GET /projects/{id}/gateways/{gateway_id}`,
`GET /projects/{id}/connectivity?hours=`, `GET /admin/gateways`, `PATCH /admin/gateways/{id}`,
`POST /data-sources/{id}/sync-gateways`.
