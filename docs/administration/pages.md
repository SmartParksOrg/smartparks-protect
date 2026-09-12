# Pages per role

What each kind of user sees. The rule behind every page (decisions D133 and D134): the entity,
its state and the next action first; the machinery one click deeper, in the same place on
every object. There is no switch for detail: what a person sees follows the role only.

## One click deeper

A small health dot sits in the top right corner of the content on every page, for every signed-in account: green while every worker reports and no system alert is open, amber once one has lingered (a worker silent over 15 minutes, a system alert open over 30 minutes), red only after two polls without an answer; a click names the reason and server admins get the way to Server admin, System health.

The entity page and the device page have four tabs. Overview holds what a ranger needs: the
state, the health, a small map with the newest position, the assignments and the actions.
Data holds the records, positions and events, with the curate, deliveries and provenance
links on each. Connectivity holds what the networks say about the link, per data source: the
connection state, the gateways heard with the best one and its share, signal and frame-counter
gaps for LoRaWAN, the last satellite session for Iridium. Network holds the machinery of that object: identities, traffic, traces and
commands. The tab sits in the URL (`?tab=data`, `?tab=network`), so a link from a traffic
row, a gateway or a trace lands on the tab it means. A list shows the columns a person needs
first; the Columns picker adds the rest, per user.

## Project viewer

| Page | Shows | One click deeper |
| --- | --- | --- |
| Live map | Entities with their health, the layers panel (Entities, Devices, Features, Events, Coverage), tracks with the Tracks card and its length settings, recent events. The Devices tab is the device layer: every device of the project, off by default, with or without an entity; a device track is dashed. A click on an entity, a device, a track point or a gateway opens the same kind of panel: the object's state, then links to its page and its Data and Network tabs; a track point shows the fix and the measurements of that moment with its source event and trace; a gateway shows the devices it heard and "Show heard positions" narrows the coverage layer to it. The map fits to the project's entities and devices on every visit, and a "show on map" link switches a hidden object on and keeps it on. The entity and device panels carry the track and heatmap toggles as the same icon buttons as the layers panel's rows, and every tab of the layers panel has one Show all or Hide all toggle beside Fold all. The controls: the green Layers button top left, with the number of layers showing something, and under it the Feed button with the number of alerts and events this account has not seen yet (the feed lists the project's newest events with their alert state, a row centres the map on the event and opens its detail, an open alert can be acknowledged from its row, and a new alert shows a toast with a Show action while the map is open); beside the two, the number of events of the last 24 hours, which opens the Events page (the entity and device counts live on the layers panel's tabs); the strip top right (base map, 3D terrain under it on a server with a MapTiler key, which also adds the Satellite base map, draw, measure, and the Tracks and Heatmaps buttons only while a track or a heatmap is on); zoom, reset north and Locate bottom right, where Locate follows the phone's position with a dot and an accuracy ring until pressed again (a pan keeps the dot and stops the following). Draw (project admins) makes a point, line, polygon or circle into a feature: every tap places a marker, the length, area or radius updates while drawing, vertices can be dragged before the shape is saved, and a circle is kept as a polygon that remembers its centre and radius, named in its panel; a geofence, site or zone offers Create rule from its panel; Measure does the same with Done instead of Save and keeps nothing; a heatmap is switched on per entity or device like a track, from the row's button in the layers panel or the object's panel, and draws where it was over a look-back window, with a settings card for the radius in metres, the sensitivity and the look-back; the layers panel, the Tracks card and the object panel open under it from the right edge, from the bottom on a phone | Nothing more |
| All projects (server admins) | The project switcher's first entry: the live map, entities, devices, alerts, events, gateways and traffic over every project, with the project as the top level of the layers panel and a Project column in the lists; links go to the object's own project. Devices in no project appear under "Not in a project" on the device layer and in the devices list's project filter, where a selection can be assigned to a project at once, from each device's first data, with an entity per device if wanted. The other pages stay per project | Only server admins see the entry |
| Entities | Name, type, status, group, last seen, the device by name or "Assign device" for an entity nothing tracks (project admins), a map link. New entity: the type, then a searchable sub-type with its icon (the server's catalogue minus what the project hid under Settings), an optional icon of its own | The entity page |
| Entity page | Overview: the entity, the small map, the device tracking it with its health, the assignments | Data: positions and events; Connectivity: the link per data source, gateways heard and signal (LoRaWAN) or the last satellite session (Iridium); Network: the traffic and traces of the device tracking it |
| Devices | Name, type, status, serial, entity, group, last seen, health | The driver column through the Columns picker |
| Device page | Overview: device, the small map, health, project and entity assignments; "Assign to entity" (an entity of the project or a new one, from the guided start) and "Release" for project admins | Data: recent positions with curate, deliveries and provenance, log files, Bluetooth; Connectivity: the link per data source, gateways heard and signal (LoRaWAN) or the last satellite session (Iridium); Network: identities, traffic, commands |
| Alerts, Events | The open alerts and the recent events | Nothing more |
| Commands | The command timelines | Nothing more |
| Data explorer, Exports, Dashboards | The data | Nothing more |
| Network: Traffic, Gateways, Trace explorer | Not in the sidebar; one device's traffic and traces are on its Network tab. Gateways lists every gateway of the data sources the project's devices use: the ones that heard the project's devices in the window busiest first, then the silent ones, with a window and a source filter; names and locations come from the platform's gateway list, read daily and on Sync gateways under Server admin, Data sources | Project admins and server admins have the section |

## Project admin

Everything a viewer sees, plus the Network section (Traffic, Gateways, Trace explorer), Rules,
Automations, Integrations, Curation and the Project admin section (Members, Features, Groups,
Notifications, Settings).

## Server admin

Everything, plus the Server admin section (Needs attention, System health, Traffic, Backup
and recovery, System alerts, Automations, Notifications, Projects, Users, Devices, Data
sources, Gateways, Audit, AI policy, catalogues). The project pages are the same as a ranger's:
to check what a ranger sees, sign in as one.

## Where the machinery lives

- Identities, ports and frames: the device page's Network tab and Network, Traffic.
- Processing traces: Network, Trace explorer, and the provenance links on a position.
- Provider fields: the source event dialog reached from traffic rows and provenance links.
- Gateways: Network, Gateways, the map's Coverage tab and Server admin, Gateways.
